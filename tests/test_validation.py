import pytest

from src.models import DraftReply, Result
from src.validator import PolicyValidator, check_result_dict
from tests.test_generation import sig

V = PolicyValidator()
GOOD = {"ticket_id": "T1", "intent": "deposit_issue", "retrieved_articles": ["A1"], "reply_draft": "x",
        "grounded": True, "confidence": 0.5, "needs_human_escalation": False, "safety_flags": []}


@pytest.mark.parametrize("patch", [
    {"intent": "refund"}, {"retrieved_articles": ["A1", "A1"]}, {"confidence": 1.5}, {"confidence": -0.1},
    {"confidence": "0.5"}, {"grounded": "true"}, {"grounded": 1}, {"needs_human_escalation": "no"},
    {"safety_flags": ["made_up_flag"]}, {"extra_field": 1}, {"retrieved_articles": ["A1", "A2", "A3", "A4"]},
    {"reply_draft": ""},
])
def test_schema_rejections(patch):
    assert check_result_dict({**GOOD, **patch}, {"A1", "A2", "A3", "A4", "A5"})


def test_missing_field_rejected():
    bad = dict(GOOD); bad.pop("confidence")
    assert check_result_dict(bad, {"A1"})


def test_unknown_article_rejected():
    assert check_result_dict({**GOOD, "retrieved_articles": ["Z9"]}, {"A1"})


def test_good_result_ok():
    assert check_result_dict(GOOD, {"A1"}) == []
    Result.model_validate(GOOD)


def _validate(kb, reply, cited, retrieved, **s):
    return V.validate(ticket_id="X", message="m", intent=s.get("intent", "deposit_issue"),
                      draft=DraftReply(reply, cited), retrieved=retrieved, kb={a.article_id: a for a in kb}, signals=sig(**s))


def test_generator_grounded_claim_not_trusted(kb_articles):
    rep = _validate(kb_articles, "Thanks for reaching out. Your issue is fully resolved and all is fine.", ["A1"], ["A1"])
    assert not rep.result.grounded and rep.result.needs_human_escalation
    assert "insufficient_grounding" in rep.result.safety_flags


def test_forbidden_claims_trigger_fallback(kb_articles):
    for bad in ["Your deposit has been credited.", "Your withdrawal will be approved within 24 hours.",
                "I have unlocked your account."]:
        rep = _validate(kb_articles, bad, ["A1"], ["A1"])
        assert rep.repaired and rep.result.needs_human_escalation and bad not in rep.result.reply_draft


def test_advice_language_blocked(kb_articles):
    rep = _validate(kb_articles, "You should buy gold today, it will go up.", [], ["A1"])
    assert rep.repaired and "buy gold" not in rep.result.reply_draft
