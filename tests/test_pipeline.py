import json

from src.config import PROJECT_DIR
from src.models import Result
from src.pipeline import STAGES, Pipeline
from src.validator import is_refused
from tests.conftest import SAMPLE_TICKETS


def test_stage_order():
    assert STAGES == ("LOAD_DATA", "INDEX_KB", "CLASSIFY_INTENT", "RETRIEVE_CONTEXT",
                      "GENERATE_REPLY", "VALIDATE_OUTPUT", "WRITE_RESULTS")


def test_sample_data_end_to_end(run):
    res, dbg = run(SAMPLE_TICKETS)
    assert set(res) == {t["id"] for t in SAMPLE_TICKETS}
    for r in res.values():
        Result.model_validate(r)
    assert "A1" in res["T1"]["retrieved_articles"]
    assert res["T4"]["intent"] == "trading_advice_request" and is_refused(res["T4"]["reply_draft"])
    assert "advice_request" in res["T4"]["safety_flags"]
    assert res["T3"]["needs_human_escalation"] and "policy_sensitive" in res["T3"]["safety_flags"]
    assert {"T1", "T2", "T3", "T5"} <= {k for k, r in res.items() if r["grounded"]}


def test_ids_do_not_drive_behaviour(run):
    renamed = [dict(t, id=f"Z{i}") for i, t in enumerate(reversed(SAMPLE_TICKETS))]
    res, _ = run(renamed)
    advice = [r for r in res.values() if r["intent"] == "trading_advice_request"]
    assert len(advice) == 1 and is_refused(advice[0]["reply_draft"])


def test_reproducible(tmp_path):
    a = Pipeline().process(PROJECT_DIR / "tickets.json", PROJECT_DIR / "kb_articles.json")
    b = Pipeline().process(PROJECT_DIR / "tickets.json", PROJECT_DIR / "kb_articles.json")
    assert json.dumps(a.results) == json.dumps(b.results) and a.debug == b.debug


def test_debug_report_contents(run):
    _, dbg = run(SAMPLE_TICKETS)
    t1 = next(t for t in dbg["tickets"] if t["ticket_id"] == "T1")
    assert t1["predicted_intent"] == "deposit_issue"
    assert t1["retrieval"]["articles"][0]["title"] == "Card deposit processing times"
    assert t1["escalation_reasons"]


def test_llm_disabled_by_default():
    from src.config import settings
    from src.generator import TemplateReplyGenerator
    assert not settings.llm_enabled
    assert isinstance(Pipeline().generator, TemplateReplyGenerator)
