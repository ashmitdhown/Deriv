"""Output validation. Independently re-checks every draft; never trusts the generator's claims.

Responsibilities:
  * schema / type / label / article-id checks (strict pydantic `Result`)
  * trading-advice policy: advice tickets must be refused; no recommendation language anywhere
  * forbidden claims: invented outcomes, completed actions, promised timelines
  * grounding: every reply sentence must be an approved policy phrase or a (customerized)
    sentence from an article that was actually retrieved
  * repair: on any hard failure the reply is replaced by a safe fallback and escalated
  * confidence, safety flags and escalation (via src.safety)
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError

from src.config import Settings, settings
from src.generator import APPROVED_SENTENCES, EDUCATION, HANDOFF, NO_EVIDENCE, OPENERS, REFUSAL, usable_kb_sentences
from src.models import INTENTS, SAFETY_FLAGS, Article, DraftReply, Result, Signals, ValidationReport
from src.safety import compute_confidence, decide_flags_and_escalation
from src.utils import normalize_text, split_sentences

MAX_REPLY_CHARS = 4000

# Language that would amount to trading advice or market prediction in OUR reply.
_ADVICE_OUT = [re.compile(p, re.I) for p in (
    r"\b(you should|i('d| would)? recommend|we recommend|i suggest|consider) (buy|sell|invest|trad|go long|go short)",
    r"\b(buy|sell|invest in|go long on|short)\b.{0,30}\b(now|today|tomorrow|this week)\b",
    r"\b(will|is going to|is likely to|should) (go up|rise|increase|climb|gain|go down|fall|drop)\b",
    r"\bguarantee(d|s)? (profit|returns?|gains?|income)\b",
    r"\b(sure|safe|best) (bet|trade|investment|pick)\b",
)]

# Claims we can never make without account access.
_FORBIDDEN_CLAIMS = [re.compile(p, re.I) for p in (
    r"\b(your|the) (payment|deposit|withdrawal|transaction|transfer|funds?|balance)\b.{0,40}\b(has been|was|is now|is|have been|were)\b\s*(successful|successfully|approved|credited|completed|processed|confirmed|released|sent)\b",
    r"\bi('ve| have)? (reset|unlocked|approved|credited|refunded|processed|fixed|restored|verified)\b",
    r"\bwe('ve| have) (reset|unlocked|approved|credited|refunded|processed|fixed|restored|verified)\b",
    r"\b(will|should) be (approved|credited|processed|unlocked|released|completed|refunded)\b",
    r"\bwithin \d+\s*(seconds?|minutes?|mins?|hours?|hrs?|days?|business days?|weeks?)\b",
    r"\b(in|after) \d+\s*(minutes?|hours?|days?|business days?)\b",
    r"\b(your account|the account) (is|has been) (unlocked|verified|approved|restored)\b",
)]


def _canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(s).lower()).strip()


# Present in both the full refusal and the mixed-ticket refusal.
REFUSAL_MARKER = "can't provide market predictions, profit guarantees, or recommendations"


def is_refused(reply: str) -> bool:
    return _canon(REFUSAL_MARKER) in _canon(reply)


class OutputValidator(ABC):
    @abstractmethod
    def validate(self, *, ticket_id: str, message: str, intent: str, draft: DraftReply, retrieved: list[str],
                 kb: dict[str, Article], signals: Signals) -> ValidationReport: ...


def check_result_dict(obj: Any, known_ids: set[str]) -> list[str]:
    """Schema-level check for an already-written result (used by validate.py and tests)."""
    issues: list[str] = []
    try:
        r = Result.model_validate(obj)
    except ValidationError as e:
        return [f"schema: {err['loc']}: {err['msg']}" for err in e.errors()]
    if r.intent not in INTENTS:
        issues.append("unknown intent")
    bad = [a for a in r.retrieved_articles if a not in known_ids]
    if bad:
        issues.append(f"unknown article ids: {bad}")
    if any(f not in SAFETY_FLAGS for f in r.safety_flags):
        issues.append("unknown safety flag")
    if r.intent == "trading_advice_request" and not is_refused(r.reply_draft):
        issues.append("trading advice request not refused")
    if not r.grounded and not (r.needs_human_escalation or "insufficient_grounding" in r.safety_flags):
        issues.append("ungrounded result neither flagged nor escalated")
    return issues


class PolicyValidator(OutputValidator):
    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg

    # ---- individual checks ----
    @staticmethod
    def _strip_approved(reply: str) -> str:
        # Approved policy phrases (e.g. the refusal, the withdrawal caveat) mention the very things
        # they disclaim; remove them so only the remaining content is checked.
        for s in APPROVED_SENTENCES:
            reply = reply.replace(s, " ")
        return reply

    @classmethod
    def advice_violations(cls, reply: str) -> list[str]:
        text = cls._strip_approved(reply)
        return [p.pattern for p in _ADVICE_OUT if p.search(text)]

    @classmethod
    def forbidden_claims(cls, reply: str) -> list[str]:
        text = cls._strip_approved(reply)
        return [p.pattern for p in _FORBIDDEN_CLAIMS if p.search(text)]

    @staticmethod
    def ungrounded_sentences(reply: str, cited: list[str], kb: dict[str, Article]) -> list[str]:
        allowed = {_canon(s) for s in APPROVED_SENTENCES}
        for aid in cited:
            if aid in kb:
                sents, _ = usable_kb_sentences(kb[aid])
                allowed |= {_canon(s) for s in sents}
        return [s for s in split_sentences(reply) if _canon(s) not in allowed]

    def safe_fallback(self, intent: str, signals: Signals) -> str:
        if signals.advice:
            return " ".join([OPENERS["trading_advice_request"], REFUSAL, EDUCATION] + ([HANDOFF] if signals.mixed_intent else []))
        return " ".join([OPENERS.get(intent, OPENERS["other"]), NO_EVIDENCE])

    # ---- main entry ----
    def validate(self, *, ticket_id: str, message: str, intent: str, draft: DraftReply, retrieved: list[str],
                 kb: dict[str, Article], signals: Signals) -> ValidationReport:
        issues: list[str] = []
        fallback = False

        # 1. Structural sanity of the draft itself (generators may be buggy or hostile).
        reply = draft.reply if isinstance(draft.reply, str) else ""
        reply = normalize_text(reply)
        cited = draft.cited_articles if isinstance(draft.cited_articles, list) else []
        if not reply:
            issues.append("empty or non-string reply")
            fallback = True
        if len(reply) > MAX_REPLY_CHARS:
            issues.append("reply too long")
            fallback = True
        if not all(isinstance(c, str) for c in cited):
            issues.append("non-string citation")
            fallback, cited = True, []
        stray = [c for c in cited if c not in retrieved]
        if stray:  # citing something that was not retrieved (or doesn't exist) is not allowed
            issues.append(f"cited articles not retrieved: {stray}")
            fallback = True
        if intent not in INTENTS:
            issues.append("unknown intent from classifier")
            intent = "other"

        # 2. Policy checks.
        if not fallback:
            adv = self.advice_violations(reply)
            if adv:
                issues.append("reply contains trading-advice language")
                fallback = True
            claims = self.forbidden_claims(reply)
            if claims:
                issues.append("reply contains unsupported outcome/timeline claims")
                fallback = True
            if signals.advice and not is_refused(reply):
                issues.append("advice request not refused")
                fallback = True

        # 3. Grounding (recomputed here, independent of anything the generator asserts).
        if fallback:
            reply, cited = self.safe_fallback(intent, signals), []  # fallback uses approved phrases only
        loose = self.ungrounded_sentences(reply, cited, kb)
        approved = {_canon(a) for a in APPROVED_SENTENCES}
        kb_sentences_used = sum(1 for s in split_sentences(reply) if _canon(s) not in approved) - len(loose)
        if loose:
            issues.append(f"{len(loose)} reply sentence(s) not traceable to retrieved KB content")
        is_refusal = signals.advice and not signals.mixed_intent
        grounded = not loose and (is_refusal or kb_sentences_used > 0)

        # 4. Confidence, flags, escalation.
        conf, breakdown = compute_confidence(signals, grounded=grounded, fallback_used=fallback, cfg=self.cfg)
        flags, escalate, reasons = decide_flags_and_escalation(
            signals, grounded=grounded, confidence=conf, fallback_used=fallback, cfg=self.cfg)

        result = Result(
            ticket_id=ticket_id,
            intent=intent,  # type: ignore[arg-type]
            retrieved_articles=[r for r in retrieved if r in kb][:3],
            reply_draft=reply,
            grounded=grounded,
            confidence=conf,
            needs_human_escalation=escalate,
            safety_flags=flags,  # type: ignore[arg-type]
        )
        return ValidationReport(result, issues, fallback, breakdown, reasons)
