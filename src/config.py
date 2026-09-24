"""Central config: loads .env once, exposes typed settings."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "groq")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
