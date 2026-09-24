"""Placeholder steps: Ingest → Process (LLM) → Output. Replace once the problem is known."""
import json
from pathlib import Path
from typing import Any

from src.llm.factory import get_llm
from src.pipeline.base import Step


class Ingest(Step):
    name = "ingest"

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx.setdefault("input", "Say hello and confirm the pipeline works.")
        return ctx


class LLMProcess(Step):
    name = "llm_process"

    def __init__(self, provider: str | None = None, system: str | None = None):
        self.provider, self.system = provider, system

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx["output"] = get_llm(self.provider).generate(ctx["input"], system=self.system)
        return ctx


class SaveOutput(Step):
    name = "save_output"

    def __init__(self, path: str = "outputs/result.json"):
        self.path = Path(path)

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(ctx, indent=2, default=str))
        return ctx
