from src.config import settings
from src.llm.base import LLMClient


def get_llm(provider: str | None = None) -> LLMClient:
    provider = (provider or settings.default_provider).lower()
    if provider == "gemini":
        from src.llm.gemini_client import GeminiClient
        return GeminiClient()
    if provider == "groq":
        from src.llm.groq_client import GroqClient
        return GroqClient()
    raise ValueError(f"Unknown provider: {provider}")
