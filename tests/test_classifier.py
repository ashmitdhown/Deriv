import pytest

from src.classifier import RuleBasedClassifier

clf = RuleBasedClassifier()


@pytest.mark.parametrize("msg,intent", [
    ("I deposited by bank card two hours ago but my balance still shows zero.", "deposit_issue"),
    ("I forgot my password and I am not receiving the reset email.", "password_reset"),
    ("Why was my withdrawal declined after verification?", "withdrawal_issue"),
    ("Can you tell me which asset will go up today so I can make profit?", "trading_advice_request"),
    ("My account was locked after too many login attempts.", "account_lock"),
    ("What are your office opening hours?", "other"),
    ("Is bitcoin going to rise tomorrow?", "trading_advice_request"),
    ("Should I buy EURUSD now?", "trading_advice_request"),
    ("Give me some trading signals please", "trading_advice_request"),
])
def test_labels(msg, intent):
    assert clf.classify(msg).intent == intent


def test_certainty_and_coverage_bounded():
    for m in ["deposit withdrawal password locked", "", "zzz", "deposit"]:
        c = clf.classify(m)
        assert 0.0 <= c.certainty <= 1.0 and 0.0 <= c.rule_coverage <= 1.0


def test_conflicting_signals_detected():
    c = clf.classify("My deposit failed and my withdrawal was also declined")
    assert c.conflicting and set(c.matched_support_intents) >= {"deposit_issue", "withdrawal_issue"}


def test_advice_obfuscation_detected():
    assert clf.classify("W h i c h  a s s e t will go up? I want to make pr0fit").intent == "trading_advice_request"
