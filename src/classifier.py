"""Intent classification. Default: deterministic weighted-lexicon rules (no model, no network)."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from src.models import ClassificationResult
from src.safety import detect_advice

SUPPORT_INTENTS = ("deposit_issue", "password_reset", "withdrawal_issue", "account_lock")

# (regex, weight). Phrases weigh more than single words. Matched on lowercased text.
LEXICON: dict[str, list[tuple[str, float]]] = {
    "deposit_issue": [
        (r"\bdeposit(s|ed|ing)?\b", 2.0), (r"\btop[- ]?up\b", 1.5), (r"\bfund(ed|ing)? (my )?account\b", 1.5),
        (r"\bbalance\b", 1.0), (r"\bbank card\b", 1.0), (r"\bcard payment\b", 1.0), (r"\bnot (been )?credited\b", 1.5),
        (r"\bpayment\b", 0.5), (r"\btransaction\b", 0.5),
    ],
    "password_reset": [
        (r"\bpassword\b", 2.0), (r"\breset (link|email|e-mail)\b", 2.0), (r"\bforgot\b", 1.0),
        (r"\breset\b", 1.0), (r"\bcan'?t remember\b", 0.5),
    ],
    "withdrawal_issue": [
        (r"\bwithdraw(al|als|n|ing)?\b", 2.0), (r"\bcash ?out\b", 1.5), (r"\bpayout\b", 1.5),
        (r"\bdeclined\b", 0.5), (r"\brejected\b", 0.5),
    ],
    "account_lock": [
        (r"\block(ed)?\b", 2.0), (r"\blocked out\b", 1.0), (r"\bblocked\b", 1.0), (r"\bsuspended\b", 1.0),
        (r"\b(login|log in|sign[- ]?in) attempts?\b", 1.5), (r"\btoo many\b", 1.0), (r"\bcan'?t (log|sign) ?in\b", 1.0),
    ],
}
_LEXICON_RE = {k: [(re.compile(p), w) for p, w in v] for k, v in LEXICON.items()}
# Fixed topic terms appended to the retrieval query once an intent is predicted. Bridges simple
# vocabulary gaps (e.g. "payout" vs "withdrawal"). Never contains ticket text; deterministic.
QUERY_EXPANSION: dict[str, str] = {
    "deposit_issue": "card deposit processing",
    "password_reset": "password reset email",
    "withdrawal_issue": "withdrawal declined review",
    "account_lock": "account lock failed sign-in attempts",
    "trading_advice_request": "investment trading advice market predictions asset recommendations",
    "other": "",
}

# Score at which evidence counts as "full coverage" for an intent.
COVERAGE_SATURATION = 3.0
# Minimum score for an intent to count as present at all.
PRESENCE_THRESHOLD = 1.5


class IntentClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> ClassificationResult: ...


class RuleBasedClassifier(IntentClassifier):
    """Weighted keyword scoring + independent advice detector.

    The advice detector (src.safety.detect_advice) always runs; if it fires and no support
    intent is present the label is trading_advice_request. If both are present the support
    intent is kept as the primary label and the ticket is marked mixed (handled downstream).
    """

    def classify(self, text: str) -> ClassificationResult:
        low = text.lower()
        scores = {intent: round(sum(w for r, w in rules if r.search(low)), 3) for intent, rules in _LEXICON_RE.items()}
        advice = bool(detect_advice(text))
        scores["trading_advice_request"] = 3.0 if advice else 0.0

        present = sorted((i for i in SUPPORT_INTENTS if scores[i] >= PRESENCE_THRESHOLD), key=lambda i: (-scores[i], i))
        ranked = sorted(SUPPORT_INTENTS, key=lambda i: (-scores[i], i))
        top, second = scores[ranked[0]], scores[ranked[1]]

        if present:
            intent = present[0]
            certainty = (top - second) / top if top else 0.0
            coverage = min(1.0, top / COVERAGE_SATURATION)
        elif advice:
            intent, certainty, coverage = "trading_advice_request", 1.0, 1.0
        else:
            intent, certainty, coverage = "other", 0.0, 0.0

        # Two support intents both clearly present with a small margin = conflicting signals.
        conflicting = len(present) >= 2 and (top - second) < 1.0
        return ClassificationResult(
            intent=intent,
            certainty=round(max(0.0, min(1.0, certainty)), 3),
            rule_coverage=round(coverage, 3),
            scores=scores,
            matched_support_intents=present,
            advice_detected=advice,
            conflicting=conflicting,
        )
