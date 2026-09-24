from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Common interface so pipeline steps don't care which provider is used."""

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str: ...
