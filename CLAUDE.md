# Deriv — Project Notes for Claude

## Status
Scaffold only. The actual problem statement is **not yet defined** — this repo
was set up as a ready-to-extend automation/pipeline skeleton so real logic can
be dropped in as soon as the task is known. Don't assume domain specifics
(e.g. trading, Deriv.com's API) unless the user says so — "Deriv" here is just
the folder/project name.

## Architecture
- `src/config.py` — loads `.env`, exposes a single `settings` object.
- `src/llm/` — provider-agnostic LLM layer.
  - `base.py`: `LLMClient` ABC with `.generate(prompt, system=None)`.
  - `gemini_client.py`, `groq_client.py`: concrete implementations.
  - `factory.py`: `get_llm(provider)` — `provider` is `"gemini"` | `"groq"`,
    defaults to `DEFAULT_PROVIDER` from `.env`.
- `src/pipeline/` — minimal step-based pipeline (`Step.run(ctx) -> ctx`,
  `Pipeline.run()` chains steps left to right). See `steps.py` for the
  current placeholder: Ingest → LLMProcess → SaveOutput.
- `main.py` — CLI entrypoint: `python main.py --provider groq --input "..."`.
- `scripts/check_keys.py` — smoke-tests both API keys are working.
- `tests/` — pytest; run with `pytest`.
- `data/raw`, `data/processed`, `outputs/` — gitignored except `.gitkeep`.

## Conventions
- All new pipeline logic should be a `Step` subclass in `src/pipeline/steps.py`
  (or a new module under `src/pipeline/`), not inlined in `main.py`.
- Never hardcode API keys — read them via `src.config.settings`.
- Keep provider-specific code inside `src/llm/`; the rest of the codebase
  should only ever call `get_llm()`.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GEMINI_API_KEY / GROQ_API_KEY
python scripts/check_keys.py   # verify both keys work
python main.py --provider groq
```

## Next steps (once problem statement is known)
1. Define real `Step`s in `src/pipeline/steps.py` for actual ingestion/logic.
2. Update `Ingest` to read real input (file, API, queue, etc.) instead of the
   placeholder string.
3. Add any new deps to `requirements.txt`.
