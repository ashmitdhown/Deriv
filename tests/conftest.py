import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.config import PROJECT_DIR, settings
from src.models import Article
from src.pipeline import Pipeline

SAMPLE_KB = json.loads((PROJECT_DIR / "kb_articles.json").read_text())
SAMPLE_TICKETS = json.loads((PROJECT_DIR / "tickets.json").read_text())


@pytest.fixture
def kb_articles() -> list[Article]:
    return [Article(**a) for a in SAMPLE_KB]


@pytest.fixture
def run(tmp_path: Path):
    """run(tickets, kb=None, **pipeline_kwargs) -> (results_by_id, debug) using temp files."""

    def _run(tickets, kb=None, **kwargs):
        tp, kp = tmp_path / "tickets.json", tmp_path / "kb.json"
        tp.write_text(json.dumps(tickets))
        kp.write_text(json.dumps(kb if kb is not None else SAMPLE_KB))
        cfg = replace(settings, llm_enabled=False)
        out = Pipeline(cfg=cfg, **kwargs).run(tp, kp, tmp_path / "results.json", tmp_path / "debug_report.json")
        return {r["ticket_id"]: r for r in out.results}, out.debug

    return _run


def ticket(msg, tid="X1", lang="en"):
    return {"id": tid, "message": msg, "language": lang}
