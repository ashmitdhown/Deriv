"""Validate pipeline outputs: python validate.py  (exit code 0 = all checks passed)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.config import PROJECT_DIR, settings
from src.pipeline import Pipeline
from src.validator import check_result_dict, is_refused

REQUIRED_FILES = ["tickets.json", "kb_articles.json", "results.json", "README.md"]
DEBUG_FILES = ["debug_report.json"]


def main() -> int:
    failures: list[str] = []
    passed: list[str] = []

    def check(ok: bool, label: str) -> None:
        (passed if ok else failures).append(label)
        print(("PASS " if ok else "FAIL ") + label)

    for name in REQUIRED_FILES + DEBUG_FILES:
        check((PROJECT_DIR / name).is_file(), f"file exists: {name}")
    if failures:
        print("\nMissing files. Run `python main.py` first.")
        return 1

    def load(name: str):
        try:
            return json.loads((PROJECT_DIR / name).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    tickets, kb, results, debug = (load(n) for n in ("tickets.json", "kb_articles.json", "results.json", "debug_report.json"))
    for name, obj in (("tickets.json", tickets), ("kb_articles.json", kb), ("results.json", results), ("debug_report.json", debug)):
        check(obj is not None, f"valid JSON: {name}")
    if failures:
        return 1

    known_ids = {a["article_id"] for a in kb}
    kb_titles = {a["article_id"]: a["title"].lower() for a in kb}
    by_id = {r.get("ticket_id"): r for r in results}
    # Every ticket with a usable id gets exactly one result (invalid ones get a safe escalated
    # placeholder). Only id-less entries and duplicate ids are result-less; see debug "rejected_tickets".
    no_result = {r["ticket"] for r in debug.get("rejected_tickets", []) if not r.get("emit_result")}
    expected = {t["id"] for t in tickets if isinstance(t, dict) and isinstance(t.get("id"), str)} - no_result
    ids = [r.get("ticket_id") for r in results]
    check(len(ids) == len(set(ids)) and set(ids) == expected, "every ticket has exactly one result")

    schema_issues = {r.get("ticket_id"): check_result_dict(r, known_ids) for r in results}
    bad = {k: v for k, v in schema_issues.items() if v}
    check(not bad, "every result matches the required schema and policy checks" + (f" {bad}" if bad else ""))
    check(all(set(r["retrieved_articles"]) <= known_ids for r in results), "retrieved article ids exist in the KB")
    check(all(1 <= len(r["retrieved_articles"]) <= 3 for r in results if r["grounded"] and r["intent"] != "other"),
          "grounded results cite 1-3 articles")

    # Content-based checks (do not depend on ticket ids).
    advice = [r for r in results if r["intent"] == "trading_advice_request"]
    check(all(is_refused(r["reply_draft"]) and "advice_request" in r["safety_flags"] for r in advice),
          "trading-advice tickets are classified and refused")
    deposit = [r for r in results if r["intent"] == "deposit_issue"]
    check(all(any("deposit" in kb_titles[a] for a in r["retrieved_articles"]) for r in deposit),
          "deposit tickets retrieve the deposit article")
    withdrawal = [r for r in results if r["intent"] == "withdrawal_issue"]
    check(all("policy_sensitive" in r["safety_flags"] and r["needs_human_escalation"] for r in withdrawal),
          "withdrawal tickets are policy-sensitive and escalated")
    check(all(r["grounded"] or r["needs_human_escalation"] for r in results), "ungrounded results are escalated")

    # Sample-specific checks from the brief (only when the sample tickets are present).
    if "T1" in by_id:
        check("A1" in by_id["T1"]["retrieved_articles"], "sample: T1 retrieves A1")
    if "T4" in by_id:
        check(by_id["T4"]["intent"] == "trading_advice_request" and is_refused(by_id["T4"]["reply_draft"]),
              "sample: T4 is refused as trading advice")

    # Debug report covers every result.
    dbg_ids = {t["ticket_id"] for t in debug.get("tickets", [])}
    check(dbg_ids == set(by_id) and all(t.get("escalation_reasons") for t in debug["tickets"]),
          "debug report explains every ticket")

    # Reproducibility: two fresh in-memory runs must equal each other and the file on disk.
    run1 = Pipeline().process(settings.tickets_path, settings.kb_path)
    run2 = Pipeline().process(settings.tickets_path, settings.kb_path)
    check(run1.results == run2.results, "reproducible: two runs produce identical results")
    check(run1.results == results, "results.json matches a fresh run on the same inputs")

    print(f"\n{len(passed)} passed, {len(failures)} failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
