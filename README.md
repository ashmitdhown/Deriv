# Deriv

Generic automation/pipeline scaffold with a swappable LLM layer (Gemini +
Groq). Problem statement TBD — see [CLAUDE.md](CLAUDE.md) for architecture
and [MEMORY.md](MEMORY.md) for project history/decisions.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then edit .env and paste in your keys (see below)
python scripts/check_keys.py    # confirms both providers respond
python main.py --provider groq --input "hello"
```

## Getting your API keys

### Gemini (Google AI Studio)
1. Go to **https://aistudio.google.com/apikey**
2. Sign in with a Google account.
3. Click **Create API key** → choose a Google Cloud project (or let it
   create one for you).
4. Copy the key (starts with `AIza...`).
5. Paste it into `.env` as `GEMINI_API_KEY=AIza...`.
6. Free tier is available with rate limits; no credit card required to start.

### Groq
1. Go to **https://console.groq.com/keys**
2. Sign in / create an account.
3. Click **Create API Key**, name it, copy the value (starts with `gsk_...`).
4. Paste it into `.env` as `GROQ_API_KEY=gsk_...`.
5. Groq's free tier gives generous rate limits on open-weight models
   (Llama, etc.) — good for fast iteration.

### Never commit `.env`
`.env` is already in `.gitignore`. Only `.env.example` (no real values) is
tracked in git. If a key ever leaks into a commit, revoke/rotate it
immediately from the provider's console.

## Verifying your setup
```bash
python scripts/check_keys.py
```
Expect:
```
gemini: ✅ OK
groq: ✅ OK
```
If a key is missing/invalid you'll see a ❌ with the error instead.

## Project layout
See [CLAUDE.md](CLAUDE.md#architecture).
