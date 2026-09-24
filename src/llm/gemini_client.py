from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.llm.base import LLMClient


class GeminiClient(LLMClient):
    def __init__(self, model: str | None = None):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY missing — see README 'API keys'.")
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = model or settings.gemini_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def generate(self, prompt: str, system: str | None = None) -> str:
        config = types.GenerateContentConfig(system_instruction=system) if system else None
        resp = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
        return resp.text or ""
