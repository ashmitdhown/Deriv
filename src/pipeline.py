"""Pipeline orchestration with explicit stages:

LOAD_DATA -> INDEX_KB -> CLASSIFY_INTENT -> RETRIEVE_CONTEXT -> GENERATE_REPLY -> VALIDATE_OUTPUT -> WRITE_RESULTS

Components are injected, so classifier / retriever / generator / validator can be swapped independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.classifier import IntentClassifier, RuleBasedClassifier
from src.config import Settings, settings
from src.generator import OPENERS, UNPROCESSABLE, ReplyGenerator, build_generator
from src.models import _ID_RE, Article, ClassificationResult, DraftReply, Result, RetrievalResult, Signals, Ticket
from src.retriever import Retriever, TfidfRetriever
from src.safety import detect_account_specific, detect_injection
from src.utils import InputFileError, atomic_write_text, dumps, get_logger, load_json_list
from src.validator import OutputValidator, PolicyValidator

log = get_logger("pipeline")

STAGES = ("LOAD_DATA", "INDEX_KB", "CLASSIFY_INTENT", "RETRIEVE_CONTEXT", "GENERATE_REPLY", "VALIDATE_OUTPUT", "WRITE_RESULTS")


class PipelineError(Exception):
    """Fatal error: nothing is written."""


@dataclass
class TicketState:
    ticket: Ticket
    classification: ClassificationResult | None = None
    retrieval: RetrievalResult | None = None
    signals: Signals | None = None
    draft: DraftReply | None = None
    result: Result | None = None
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunOutput:
    results: list[dict[str, Any]]
    debug: dict[str, Any]


def _load_tickets(raw: list[Any], cfg: Settings) -> tuple[list[Ticket], list[dict[str, Any]], dict[str, int]]:
    """Validate tickets one by one. Bad tickets are rejected (reported), never turned into fake requests.

    A rejected ticket whose id is usable and unique is marked `emit_result`, so it still gets a
    safe "could not process, escalated" entry in results.json (every ticket gets one result).
    """
    if len(raw) > cfg.max_tickets:
        raise PipelineError(f"too many tickets ({len(raw)} > {cfg.max_tickets})")
    tickets: list[Ticket] = []
    positions: dict[str, int] = {}  # accepted ticket id -> index in the input file
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def reject(i: int, tid: str, reason: str) -> None:
        usable = bool(_ID_RE.match(tid)) and tid not in seen
        if usable:
            seen.add(tid)
        rejected.append({"ticket": tid, "index": i, "reason": reason, "emit_result": usable})

    for i, item in enumerate(raw):
        tid = item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), str) else f"#index{i}"
        tid = tid[:64]
        if not isinstance(item, dict):
            reject(i, tid, "not a JSON object")
            continue
        msg = item.get("message")
        if isinstance(msg, str) and len(msg) > cfg.max_message_chars:
            reject(i, tid, f"message exceeds {cfg.max_message_chars} characters")
            continue
        try:
            t = Ticket.model_validate(item)
        except ValidationError as e:
            fields = sorted({str(err["loc"][0]) if err["loc"] else "?" for err in e.errors()})
            reject(i, tid, f"invalid field(s): {', '.join(fields)}")
            continue
        if t.id in seen:
            rejected.append({"ticket": tid, "index": i, "reason": "duplicate ticket id", "emit_result": False})
            continue
        seen.add(t.id)
        positions[t.id] = i
        tickets.append(t)
    return tickets, rejected, positions


def _rejected_result(ticket_id: str) -> Result:
    """Safe placeholder for a ticket that failed input validation: nothing answered, always escalated."""
    return Result(
        ticket_id=ticket_id, intent="other", retrieved_articles=[],
        reply_draft=f"{OPENERS['other']} {UNPROCESSABLE}", grounded=False, confidence=0.0,
        needs_human_escalation=True, safety_flags=["insufficient_grounding", "low_confidence"],
    )


def _load_kb(raw: list[Any], cfg: Settings) -> list[Article]:
    """The KB is trusted configuration-grade data: any structural problem aborts the run."""
    if not raw:
        raise PipelineError("knowledge base is empty")
    if len(raw) > cfg.max_articles:
        raise PipelineError(f"too many articles ({len(raw)} > {cfg.max_articles})")
    arts, seen = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PipelineError(f"article at index {i} is not an object")
        if len(str(item.get("title", ""))) > cfg.max_title_chars or len(str(item.get("body", ""))) > cfg.max_body_chars:
            raise PipelineError(f"article at index {i} exceeds length limits")
        try:
            a = Article.model_validate(item)
        except ValidationError as e:
            raise PipelineError(f"article at index {i} is invalid: {[err['loc'] for err in e.errors()]}") from None
        if a.article_id in seen:
            raise PipelineError(f"duplicate article id {a.article_id!r}")
        seen.add(a.article_id)
        arts.append(a)
    return arts


class Pipeline:
    def __init__(
        self,
        classifier: IntentClassifier | None = None,
        retriever: Retriever | None = None,
        generator: ReplyGenerator | None = None,
        validator: OutputValidator | None = None,
        cfg: Settings = settings,
    ):
        self.cfg = cfg
        self.classifier = classifier or RuleBasedClassifier()
        self.retriever = retriever or TfidfRetriever(cfg)
        self.generator = generator or build_generator(cfg)
        self.validator = validator or PolicyValidator(cfg)
        self._positions: dict[str, int] = {}
        self._kb_by_id: dict[str, Article] = {}

    # ---- stages ----
    def load_data(self, tickets_path: Path, kb_path: Path) -> tuple[list[Ticket], list[dict[str, str]], list[Article]]:
        try:
            raw_t, raw_k = load_json_list(tickets_path), load_json_list(kb_path)
        except InputFileError as e:
            raise PipelineError(str(e)) from None
        return self.load_records(raw_t, raw_k)

    def load_records(self, raw_t: list[Any], raw_k: list[Any]) -> tuple[list[Ticket], list[dict[str, str]], list[Article]]:
        """LOAD_DATA from already-parsed JSON (used by the web demo)."""
        if not isinstance(raw_t, list) or not isinstance(raw_k, list):
            raise PipelineError("tickets and KB must be JSON arrays")
        tickets, rejected, self._positions = _load_tickets(raw_t, self.cfg)
        kb = _load_kb(raw_k, self.cfg)
        log.info("loaded %d ticket(s), rejected %d, %d article(s)", len(tickets), len(rejected), len(kb))
        return tickets, rejected, kb

    def index_kb(self, kb: list[Article]) -> None:
        self.retriever.index(kb)

    def classify_intent(self, st: TicketState) -> None:
        st.classification = self.classifier.classify(st.ticket.message)

    def retrieve_context(self, st: TicketState) -> None:
        # Query = ticket text + fixed topic terms for the predicted intent (and the advice-policy terms
        # when advice was detected, so mixed tickets also surface the policy article).
        from src.classifier import QUERY_EXPANSION

        c = st.classification
        assert c is not None
        terms = [QUERY_EXPANSION.get(c.intent, "")]
        if c.advice_detected and c.intent != "trading_advice_request":
            terms.append(QUERY_EXPANSION["trading_advice_request"])
        expansion = " ".join(t for t in terms if t)
        st.debug["query_expansion"] = expansion
        st.retrieval = self.retriever.search(f"{st.ticket.message} {expansion}".strip(), self.cfg.top_k)

    def _evidence_topic_mismatch(self, st: TicketState) -> bool:
        """Cross-check: classify the top article's *title* with the same classifier. If it points at a
        different support topic than the ticket, retrieval and classification disagree (content-based,
        no hardcoded article ids)."""
        from src.classifier import SUPPORT_INTENTS

        c, r = st.classification, st.retrieval
        assert c is not None and r is not None
        if not r.hits or c.intent not in SUPPORT_INTENTS:
            return False
        topic = self.classifier.classify(self._kb_by_id[r.hits[0].article_id].title).intent
        mismatch = topic in SUPPORT_INTENTS and topic != c.intent
        st.debug["evidence_topic"] = topic
        return mismatch

    def _signals(self, st: TicketState) -> Signals:
        c, r, msg = st.classification, st.retrieval, st.ticket.message
        assert c is not None and r is not None
        inj = detect_injection(msg)
        topic_mismatch = self._evidence_topic_mismatch(st)
        advice = c.advice_detected
        mixed = advice and c.intent != "trading_advice_request"
        return Signals(
            advice=advice,
            injection=bool(inj),
            account_specific=detect_account_specific(msg),
            policy_sensitive=c.intent == "withdrawal_issue" or "withdrawal_issue" in c.matched_support_intents,
            mixed_intent=mixed,
            conflicting=c.conflicting or topic_mismatch,
            kb_sanitized=False,
            language_ok=st.ticket.language.split("-")[0].split("_")[0] == "en",
            retrieval_sufficient=r.sufficient,
            retrieval_top_score=r.hits[0].score if r.hits else 0.0,
            classifier_certainty=c.certainty,
            rule_coverage=c.rule_coverage,
            intent=c.intent,
            injection_matches=inj,
        )

    def generate_reply(self, st: TicketState, kb_by_id: dict[str, Article]) -> None:
        assert st.retrieval is not None and st.classification is not None
        st.signals = self._signals(st)
        context = [kb_by_id[h.article_id] for h in st.retrieval.hits]  # only the selected snippets
        try:
            st.draft = self.generator.generate(st.ticket.message, st.classification.intent, context, st.signals)
            if not isinstance(st.draft, DraftReply):
                raise TypeError("generator returned a non-DraftReply object")
        except Exception as e:  # noqa: BLE001 - a broken generator must not crash the run
            log.warning("generator error on ticket %s (%s)", st.ticket.id, e.__class__.__name__)
            st.draft = DraftReply(reply="", cited_articles=[], notes=["generator_error"])
        if "kb_sanitized" in st.draft.notes:
            st.signals.kb_sanitized = True

    @staticmethod
    def _reported_articles(r: RetrievalResult) -> list[str]:
        """Article ids for `retrieved_articles`: the passing hits, or, if none passed, the single best
        candidate with a non-zero score (reported for traceability, never used as evidence; the
        ticket is flagged insufficient_grounding and escalated). Empty only with zero lexical overlap."""
        if r.hits:
            return [h.article_id for h in r.hits]
        return [r.weak_candidate] if r.weak_candidate else []

    def validate_output(self, st: TicketState, kb_by_id: dict[str, Article]) -> None:
        assert st.draft is not None and st.signals is not None and st.retrieval is not None and st.classification is not None
        report = self.validator.validate(
            ticket_id=st.ticket.id, message=st.ticket.message, intent=st.classification.intent, draft=st.draft,
            retrieved=self._reported_articles(st.retrieval), kb=kb_by_id, signals=st.signals,
        )
        st.result = report.result
        c, r = st.classification, st.retrieval
        st.debug = {
            "ticket_id": st.ticket.id,
            "message_chars": len(st.ticket.message),  # raw text deliberately omitted
            "predicted_intent": c.intent,
            "evidence_topic": st.debug.get("evidence_topic"),
            "query_expansion": st.debug.get("query_expansion", ""),  # classifier label of the top article's title
            "classifier": {"certainty": c.certainty, "rule_coverage": c.rule_coverage, "scores": c.scores,
                           "conflicting_signals": c.conflicting, "advice_detected": c.advice_detected},
            "retrieval": {
                "sufficient": r.sufficient,
                "threshold": self.cfg.min_relevance,
                "articles": [{"article_id": h.article_id, "title": kb_by_id[h.article_id].title, "score": h.score} for h in r.hits],
                "best_rejected_candidate": (
                    {"article_id": r.weak_candidate, "title": kb_by_id[r.weak_candidate].title, "score": r.best_score}
                    if r.weak_candidate else None),
            },
            "generator": st.draft.generator if isinstance(st.draft.generator, str) else "unknown",
            # Articles the final reply actually draws on (empty if the validator replaced the draft).
            "cited_articles": [] if report.repaired else [a for a in st.draft.cited_articles
                                                          if isinstance(a, str) and a in st.result.retrieved_articles],
            "generator_notes": [n for n in st.draft.notes if isinstance(n, str)],
            "validation_issues": report.issues,
            "fallback_used": report.repaired,
            "grounded": st.result.grounded,
            "confidence": st.result.confidence,
            "confidence_breakdown": report.confidence_breakdown,
            "safety_flags": list(st.result.safety_flags),
            "needs_human_escalation": st.result.needs_human_escalation,
            "escalation_reasons": report.escalation_reasons,
        }

    def write_results(self, out: RunOutput, results_path: Path, debug_path: Path) -> None:
        # Everything is serialized before anything is written; each file is replaced atomically.
        res_txt, dbg_txt = dumps(out.results), dumps(out.debug)
        atomic_write_text(debug_path, dbg_txt)
        atomic_write_text(results_path, res_txt)

    # ---- orchestration ----
    def process(self, tickets_path: Path | None = None, kb_path: Path | None = None) -> RunOutput:
        """Run all stages except WRITE_RESULTS (pure, reproducible)."""
        tickets, rejected, kb = self.load_data(tickets_path or self.cfg.tickets_path, kb_path or self.cfg.kb_path)
        return self._process_loaded(tickets, rejected, kb)

    def process_records(self, raw_tickets: list[Any], raw_kb: list[Any]) -> RunOutput:
        """Same as process() but from in-memory records; writes nothing."""
        return self._process_loaded(*self.load_records(raw_tickets, raw_kb))

    def _process_loaded(self, tickets: list[Ticket], rejected: list[dict[str, str]], kb: list[Article]) -> RunOutput:
        self.index_kb(kb)
        kb_by_id = self._kb_by_id = {a.article_id: a for a in kb}
        states = [TicketState(t) for t in tickets]
        for st in states:
            self.classify_intent(st)
        for st in states:
            self.retrieve_context(st)
        for st in states:
            self.generate_reply(st, kb_by_id)
        for st in states:
            self.validate_output(st, kb_by_id)
        # Results follow input order; rejected tickets with a usable id get a safe escalation entry.
        rows: list[tuple[int, dict[str, Any]]] = []
        for st in states:
            if st.result is not None:
                rows.append((self._positions.get(st.ticket.id, 0), st.result.model_dump(mode="json")))
        dbg_rows: list[tuple[int, dict[str, Any]]] = [(self._positions.get(st.ticket.id, 0), st.debug) for st in states]
        for rj in rejected:
            if rj["emit_result"]:
                res = _rejected_result(rj["ticket"])
                rows.append((rj["index"], res.model_dump(mode="json")))
                dbg_rows.append((rj["index"], {
                    "ticket_id": rj["ticket"], "predicted_intent": "other", "rejected_at": "LOAD_DATA",
                    "retrieval": {"sufficient": False, "articles": []}, "confidence": 0.0,
                    "safety_flags": list(res.safety_flags), "needs_human_escalation": True,
                    "escalation_reasons": [f"input failed validation ({rj['reason']}): not processed, escalated"],
                }))
        results = [r for _, r in sorted(rows, key=lambda x: x[0])]
        debug = {
            "stages": list(STAGES),
            "components": {
                "classifier": type(self.classifier).__name__, "retriever": type(self.retriever).__name__,
                "generator": type(self.generator).__name__, "validator": type(self.validator).__name__,
            },
            "summary": {
                "tickets_processed": len(results),
                "tickets_rejected": len(rejected),
                "escalated": sum(r["needs_human_escalation"] for r in results),
            },
            "rejected_tickets": rejected,
            "tickets": [d for _, d in sorted(dbg_rows, key=lambda x: x[0])],
        }
        return RunOutput(results, debug)

    def run(self, tickets_path: Path | None = None, kb_path: Path | None = None,
            results_path: Path | None = None, debug_path: Path | None = None) -> RunOutput:
        out = self.process(tickets_path, kb_path)
        self.write_results(out, results_path or self.cfg.results_path, debug_path or self.cfg.debug_path)
        log.info("wrote %d result(s)", len(out.results))
        return out
