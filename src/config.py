"""Central configuration. Paths are project-relative; nothing is read from ticket/KB/model content."""
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # File locations (overridable via CLI, never via input content)
    tickets_path: Path = PROJECT_DIR / "tickets.json"
    kb_path: Path = PROJECT_DIR / "kb_articles.json"
    results_path: Path = PROJECT_DIR / "results.json"
    debug_path: Path = PROJECT_DIR / "debug_report.json"

    # Input limits
    max_message_chars: int = 2000
    max_title_chars: int = 200
    max_body_chars: int = 5000
    max_tickets: int = 1000
    max_articles: int = 500
    min_query_chars: int = 3

    # Retrieval
    top_k: int = 3  # clamped to 1..3
    min_relevance: float = 0.08  # cosine below this is "no sufficient evidence"
    strong_relevance: float = 0.30  # cosine at/above this counts as full retrieval signal
    relative_cutoff: float = 0.5  # extra articles must score >= this fraction of the best hit

    # Escalation
    low_confidence_threshold: float = 0.45

    # Optional LLM generator: OFF by default, explicit opt-in only
    llm_enabled: bool = field(default_factory=lambda: _env("LLM_ENABLED").lower() == "true")
    default_provider: str = field(default_factory=lambda: _env("DEFAULT_PROVIDER", "groq"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-flash-latest"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "openai/gpt-oss-120b"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))


settings = Settings()
