"""Evaluator may swap in similar tickets with other ids/wording: behaviour must come from content."""
import pytest

from src.validator import is_refused
from tests.conftest import ticket


@pytest.mark.parametrize("msg,intent,article", [
    ("My card top-up hasn't shown in my balance yet", "deposit_issue", "A1"),
    ("My payout was rejected, why?", "withdrawal_issue", "A3"),
    ("I can't sign in, it says my account is locked", "account_lock", "A4"),
    ("The password reset link never shows up in my inbox", "password_reset", "A2"),
    ("Which crypto should I buy right now to double my money?", "trading_advice_request", "A5"),
])
def test_paraphrased_tickets(run, msg, intent, article):
    res, dbg = run([ticket(msg, "Q9")])
    r = res["Q9"]
    assert r["intent"] == intent and article in r["retrieved_articles"]
    if intent == "trading_advice_request":
        assert is_refused(r["reply_draft"])
    if intent == "withdrawal_issue":
        assert "policy_sensitive" in r["safety_flags"] and r["needs_human_escalation"]


def test_non_english_escalated(run):
    res, _ = run([ticket("No me llega el correo para restablecer la contraseña", "ES", lang="es")])
    assert res["ES"]["needs_human_escalation"]


def test_query_expansion_recorded(run):
    _, dbg = run([ticket("My payout was rejected")])
    assert dbg["tickets"][0]["query_expansion"] == "withdrawal declined review"
