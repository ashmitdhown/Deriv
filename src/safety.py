"""Deterministic safety detectors, confidence scoring and escalation rules.

These checks run on every ticket independently of the classifier and generator, so
malicious wording cannot switch them off. They are pattern-based heuristics and can be
evaded by sufficiently novel phrasing — see README "Known limitations".
"""
from __future__ import annotations

import re

from src.config import Settings
from src.models import Signals

# ---------- detectors ----------

# Requests for market predictions / recommendations / profit. Applied to a de-obfuscated
# copy of the text (see _squash) so "b u y" or "pr0fit" style tricks are partly covered.
_ADVICE_PATTERNS = [
    r"\bwhich (asset|stock|coin|crypto|currency|pair|share|market|option|index)s?\b",
    r"\bwhat (asset|stock|coin|crypto|currency|pair|share|option|index)s? (should|to|will|would)\b",
    r"\b(will|would|is going to|gonna) (go|move|rise|climb|drop|fall|pump|moon)( up| down)?\b",
    r"\bgo(ing)? (up|down) (today|tomorrow|this week|soon)\b",
    r"\b(going to|gonna|expected to|likely to|about to) (go up|go down|rise|fall|drop|climb|pump|crash|moon|increase|decrease|rally)\b",
    r"\b(bitcoin|btc|eth|ethereum|crypto|gold|oil|forex|stocks?|shares?|eur ?usd|gbp ?usd|nasdaq|s ?& ?p)\b.{0,30}\b(rise|fall|go up|go down|pump|crash|rally|price (target|prediction))\b",
    r"\b(make|making|earn|earning|guarantee[ds]?|maximi[sz]e) (a |some |more |quick |easy |big )?(profit|profits|money|returns?|gains?)\b",
    r"\bprofit(able)? (trade|trades|asset|strategy|signal|signals|pick|picks)\b",
    r"\b(should i|shall i|do i|when to|when should i) (buy|sell|invest|trade|go long|go short)\b",
    r"\b(recommend|suggest|tip|tips|pick|picks|signals?) (an? |me |some |any )?(asset|stock|coin|trade|trades|investment|market)s?\b",
    r"\b(market|price) (prediction|predictions|forecast|forecasts|direction)\b",
    r"\bpredict (the )?(market|price|prices)\b",
    r"\b(best|top|hot) (asset|stock|coin|crypto|trade|investment)s?\b",
    r"\b(investment|trading|financial) advice\b",
    r"\b(trading|trade|buy|sell|forex|crypto|market) (signals?|tips?|calls?|picks?)\b",
    r"\bsure[- ]?(fire|win|thing) (trade|bet|profit)\b",
]
_ADVICE_RE = [re.compile(p) for p in _ADVICE_PATTERNS]

# Attempts to steer the system rather than ask for support.
_INJECTION_PATTERNS = {
    "override_instructions": r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instruction|instructions|rules|policy|policies|prompt|guidelines|above|previous|prior)\b",
    "reveal_prompt": r"\b(reveal|show|print|repeat|leak|display|output)\b.{0,30}\b(system prompt|prompt|instructions|hidden|configuration|config|api key|secret)s?\b",
    "role_change": r"\b(you are now|act as|pretend (to be|you are)|roleplay as|from now on you)\b",
    "fake_outcome": r"\b(pretend|say|tell me|confirm|state|claim)\b.{0,40}\b(was|is|has been|been)\b.{0,20}\b(successful|succeeded|approved|credited|completed|processed|unlocked)\b",
    "schema_tamper": r"\b(return|output|respond|reply|use|change|modify|add)\b.{0,40}\b(json|schema|format|field|fields|key|keys)\b",
    "force_field": r"\b(set|mark|make)\b.{0,20}\b(grounded|confidence|escalation|needs_human_escalation|safety_flags|intent)\b",
    "policy_evasion": r"\b(do not|don't|dont|never)\b.{0,15}\b(follow|apply|obey|use)\b.{0,20}\b(policy|policies|rules|guidelines)\b",
    "markup": r"(<\s*/?\s*(system|assistant|script|instructions?)\b|\[\s*/?\s*(system|inst)\s*\]|```)",
    "exfil_url": r"\b(https?://|www\.)\S+",
}
_INJECTION_RE = {k: re.compile(v) for k, v in _INJECTION_PATTERNS.items()}

# Asks that require looking at a specific customer's data we do not have.
_ACCOUNT_SPECIFIC_RE = re.compile(
    r"\b(my (account|balance|transaction|transactions|payment|deposit|withdrawal|payout|top-?up|verification|documents?|kyc|card|funds|money)"
    r"|why was my|why is my|check my|status of my|where is my|what happened to my|look (up|into) my)\b"
)

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def _squash(text: str) -> str:
    """Lowercase, undo simple leetspeak, and re-join single letters separated by spaces/dots."""
    t = text.lower().translate(_LEET)
    t = re.sub(r"\b(?:[a-z][\s.\-_*]){2,}[a-z]\b", lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), t)
    return re.sub(r"\s+", " ", t)


def detect_advice(text: str) -> list[str]:
    t = _squash(text)
    return sorted({m.group(0) for r in _ADVICE_RE for m in [r.search(t)] if m})


def detect_injection(text: str) -> list[str]:
    t = _squash(text)
    return sorted(k for k, r in _INJECTION_RE.items() if r.search(t))


def detect_account_specific(text: str) -> bool:
    return bool(_ACCOUNT_SPECIFIC_RE.search(text.lower()))


# ---------- confidence & escalation ----------


def compute_confidence(sig: Signals, *, grounded: bool, fallback_used: bool, cfg: Settings) -> tuple[float, dict[str, float]]:
    """Deterministic heuristic in [0, 1]. Not a calibrated probability.

    base = 0.5 * retrieval_strength + 0.3 * classifier_certainty + 0.2 * rule_coverage
    minus penalties for fallback, conflicting signals, suspicious input, missing grounding.
    A refusal of pure trading advice is policy-certain, so its retrieval term is set to 1.
    """
    if sig.intent == "trading_advice_request" and not sig.mixed_intent:
        retrieval_strength = 1.0
    else:
        retrieval_strength = min(1.0, sig.retrieval_top_score / cfg.strong_relevance) if sig.retrieval_sufficient else 0.0
    parts = {
        "retrieval": round(0.5 * retrieval_strength, 4),
        "classifier": round(0.3 * sig.classifier_certainty, 4),
        "coverage": round(0.2 * sig.rule_coverage, 4),
    }
    penalties = {
        "fallback_used": 0.2 if fallback_used else 0.0,
        "conflicting_signals": 0.15 if (sig.conflicting or sig.mixed_intent) else 0.0,
        "suspicious_input": 0.1 if (sig.injection or sig.kb_sanitized) else 0.0,
        "ungrounded": 0.2 if not grounded else 0.0,
        "unsupported_language": 0.1 if not sig.language_ok else 0.0,
    }
    raw = sum(parts.values()) - sum(penalties.values())
    conf = round(min(1.0, max(0.0, raw)), 3)
    breakdown = {**parts, **{f"-{k}": v for k, v in penalties.items() if v}, "final": conf}
    return conf, breakdown


def decide_flags_and_escalation(
    sig: Signals, *, grounded: bool, confidence: float, fallback_used: bool, cfg: Settings
) -> tuple[list[str], bool, list[str]]:
    """Return (safety_flags, needs_human_escalation, human-readable reasons)."""
    flags: set[str] = set()
    reasons: list[str] = []
    escalate = False

    if sig.advice:
        flags.add("advice_request")
        reasons.append("trading/investment advice requested: refused per policy"
                       + ("" if sig.mixed_intent else " (a pure advice request needs no escalation)"))
    if sig.mixed_intent:
        flags.add("mixed_intent")
        escalate = True
        reasons.append("ticket mixes a support issue with an advice request: escalated for human review")
    if sig.policy_sensitive:
        flags.add("policy_sensitive")
        escalate = True
        reasons.append("withdrawal issues are policy-sensitive: outcome depends on account status/compliance review")
    if sig.account_specific:
        flags.add("account_specific_request")
        if sig.intent != "trading_advice_request":
            reasons.append("mentions account-specific data not available in the local KB: general KB guidance given, flagged")
    if sig.injection or sig.kb_sanitized:
        flags.add("suspicious_input")
        escalate = True
        what = []
        if sig.injection:
            what.append(f"ticket contains instruction-like content ({', '.join(sig.injection_matches)})")
        if sig.kb_sanitized:
            what.append("retrieved KB text contained instruction-like content that was excluded")
        reasons.append("; ".join(what) + ": treated as data, escalated")
    if not sig.retrieval_sufficient and sig.intent != "trading_advice_request":
        flags.add("insufficient_grounding")
        escalate = True
        reasons.append("no KB article passed the relevance threshold")
    if not grounded:
        flags.add("insufficient_grounding")
        escalate = True
        reasons.append("reply could not be fully traced to retrieved KB content")
    if fallback_used:
        escalate = True
        reasons.append("generator output failed validation: replaced with safe fallback")
    if sig.conflicting and not sig.mixed_intent:
        escalate = True
        reasons.append("conflicting signals: ticket matches several intents, or the top article covers a different topic")
    if not sig.language_ok:
        escalate = True
        reasons.append("ticket language is not supported by the English-only KB/templates")
    if confidence < cfg.low_confidence_threshold:
        flags.add("low_confidence")
        escalate = True
        reasons.append(f"confidence {confidence} below threshold {cfg.low_confidence_threshold}")
    if sig.intent == "other" and not escalate:
        escalate = True
        reasons.append("intent could not be mapped to a supported category")
    if not escalate:
        reasons.append("not escalated: reply is grounded in retrieved KB content (or is a policy refusal) and no escalation trigger fired")

    ordered = [f for f in ("advice_request", "insufficient_grounding", "policy_sensitive", "low_confidence",
                           "account_specific_request", "mixed_intent", "suspicious_input") if f in flags]
    return ordered, escalate, reasons
