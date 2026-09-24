"""Minimal pipeline: an ordered list of steps passing a shared context dict."""
from abc import ABC, abstractmethod
from typing import Any

from src.utils.logger import get_logger

log = get_logger("pipeline")


class Step(ABC):
    name: str = "step"

    @abstractmethod
    def run(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


class Pipeline:
    def __init__(self, steps: list[Step]):
        self.steps = steps

    def run(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = ctx or {}
        for step in self.steps:
            log.info("→ %s", step.name)
            ctx = step.run(ctx)
        return ctx
