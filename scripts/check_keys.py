"""Quick smoke test: pings both providers with a tiny prompt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.factory import get_llm  # noqa: E402

for provider in ("gemini", "groq"):
    try:
        print(f"{provider}: ✅ {get_llm(provider).generate('Reply with just: OK').strip()}")
    except Exception as e:
        print(f"{provider}: ❌ {e}")
