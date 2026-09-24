from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.llm.base import LLMClient


class GroqClient(LLMClient):
    def __init__(self, model: str | None = None):
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY missing — see README 'API keys'.")
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = model or settings.groq_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def generate(self, prompt: str, system: str | None = None) -> str:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content or ""
