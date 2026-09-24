"""Typed models: validated inputs, the strict output schema, and internal pipeline records."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from src.utils import normalize_text

Intent = Literal[
    "deposit_issue",
    "password_reset",
    "withdrawal_issue",
    "account_lock",
    "trading_advice_request",
    "other",
]
INTENTS: tuple[str, ...] = Intent.__args__  # type: ignore[attr-defined]

SafetyFlagName = Literal[
    "advice_request",
    "insufficient_grounding",
    "policy_sensitive",
    "low_confidence",
    "account_specific_request",
    "mixed_intent",
    "suspicious_input",
]
SAFETY_FLAGS: tuple[str, ...] = SafetyFlagName.__args__  # type: ignore[attr-defined]

_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class Ticket(BaseModel):
    """Validated, normalized input ticket. Text is data, never instructions."""

    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    message: str
    language: str = "en"

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9_.-]{1,64}")
        return v

    @field_validator("message")
    @classmethod
    def _check_message(cls, v: str) -> str:
        v = normalize_text(v)
        if not v:
            raise ValueError("message is empty after normalization")
        return v

    @field_validator("language")
    @classmethod
    def _check_lang(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[a-z]{2,3}([-_][a-z0-9]{2,8})?$", v):
            raise ValueError("language must look like a language code")
        return v


class Article(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    article_id: str
    title: str
    body: str

    @field_validator("article_id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("article_id must match [A-Za-z0-9_.-]{1,64}")
        return v

    @field_validator("title", "body")
    @classmethod
    def _check_text(cls, v: str) -> str:
        v = normalize_text(v)
        if not v:
            raise ValueError("text is empty after normalization")
        return v


class Result(BaseModel):
    """Required per-ticket output schema. Strict: wrong types and unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ticket_id: str
    intent: Intent
    retrieved_articles: list[str] = Field(max_length=3)
    reply_draft: str = Field(min_length=1, max_length=4000)
    grounded: StrictBool
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    needs_human_escalation: StrictBool
    safety_flags: list[SafetyFlagName]

    @field_validator("retrieved_articles", "safety_flags")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate entries")
        return v


class LLMDraft(BaseModel):
    """Schema an optional LLM generator must return; anything else is rejected."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reply: str = Field(min_length=1, max_length=4000)
    cited_articles: list[str] = Field(max_length=3)


# ---- internal records (not part of the output schema) ----


@dataclass(frozen=True)
class Hit:
    article_id: str
    score: float


@dataclass
class RetrievalResult:
    hits: list[Hit]  # only hits that passed the relevance threshold
    sufficient: bool
    best_score: float  # best raw score even if below threshold (0.0 if none)
    weak_candidate: str | None = None  # best article id when nothing passed the threshold


@dataclass
class ClassificationResult:
    intent: str
    certainty: float  # 0..1 heuristic margin, NOT a calibrated probability
    rule_coverage: float  # 0..1 how much lexicon evidence backed the top intent
    scores: dict[str, float]
    matched_support_intents: list[str]
    advice_detected: bool
    conflicting: bool


@dataclass
class DraftReply:
    reply: str
    cited_articles: list[str]
    refusal_only: bool = False
    generator: str = "template"
    notes: list[str] = field(default_factory=list)


@dataclass
class Signals:
    """Deterministic safety signals for one ticket, shared by generator, validator and confidence logic."""

    advice: bool
    injection: bool
    account_specific: bool
    policy_sensitive: bool
    mixed_intent: bool
    conflicting: bool
    kb_sanitized: bool
    language_ok: bool
    retrieval_sufficient: bool
    retrieval_top_score: float
    classifier_certainty: float
    rule_coverage: float
    intent: str
    injection_matches: list[str] = field(default_factory=list)
    advice_matches: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    result: Result
    issues: list[str]
    repaired: bool
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    escalation_reasons: list[str] = field(default_factory=list)
