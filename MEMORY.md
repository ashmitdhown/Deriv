# Project Memory

Running log of decisions, context, and things worth remembering about this
project that aren't obvious from the code itself. Newest entries at the top.

---

## 2026-09-24 — Model names went stale
- Original defaults (`gemini-2.5-flash`, `llama-3.3-70b-versatile`) 404'd: Gemini
  retired 2.5-flash for new users; Groq dropped the Llama 3.3 model.
- Now `GEMINI_MODEL=gemini-flash-latest` (alias, won't go stale) and
  `GROQ_MODEL=openai/gpt-oss-120b`. List available models with the SDKs'
  `models.list()` if these break again.
- Gemini occasionally returns transient 5xx; the tenacity retry wraps this, but
  `RetryError` hides the real cause — inspect `.last_attempt.exception()`.

## 2026-09-24 — Initial scaffold
- Repo started empty; no problem statement given yet. Set up a generic
  automation/pipeline skeleton (see [CLAUDE.md](CLAUDE.md)) so real work can
  start immediately once the task is defined.
- Chose two LLM providers per user request: **Gemini** (Google) and **Groq**
  (fast open-weight model hosting). Both wired behind a common
  `LLMClient` interface in `src/llm/` so switching or A/B-testing providers
  is a one-line change (`DEFAULT_PROVIDER` in `.env` or `--provider` flag).
- `DEFAULT_PROVIDER=groq` was picked arbitrarily (cheaper/faster for
  iteration) — revisit once real latency/quality/cost needs are known.
- API key setup guide lives in [README.md](README.md).

<!-- Add new entries above this line -->
