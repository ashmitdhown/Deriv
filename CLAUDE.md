# Deriv — Project Notes for Claude

## Status
Secure AI customer-support ticket processor (problem statement from the user's master
prompt; `Projectidea.md` is empty). Offline by default. See README.md for full docs.

## Architecture
Pipeline (`src/pipeline.py`): LOAD_DATA -> INDEX_KB -> CLASSIFY_INTENT -> RETRIEVE_CONTEXT
-> GENERATE_REPLY -> VALIDATE_OUTPUT -> WRITE_RESULTS. Components injected via ABCs:
- `src/classifier.py` RuleBasedClassifier · `src/retriever.py` TfidfRetriever
- `src/generator.py` TemplateReplyGenerator (default) / LLMReplyGenerator (opt-in, uses `src/llm/`)
- `src/validator.py` PolicyValidator (independent grounding/policy/schema checks)
- `src/safety.py` advice/injection detectors, confidence + escalation rules
- `src/models.py` strict pydantic `Result` schema; `src/config.py` paths/limits/thresholds

## Conventions
- Never branch on ticket IDs; behaviour must come from content.
- Replies may contain only approved phrases (`APPROVED_SENTENCES`) or customerized KB sentences —
  anything else is marked ungrounded by the validator. Adding template text = add it to that set.
- Never echo ticket text into replies/logs/debug report.
- LLM path stays off unless `LLM_ENABLED=true`; `.env` is not auto-loaded.

## Commands
```bash
pip install -r requirements.txt
python main.py && python validate.py && python -m pytest -q
python demo/server.py   # web demo on http://127.0.0.1:8000
```
