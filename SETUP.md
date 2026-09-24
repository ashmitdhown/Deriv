# Setup & Deployment Guide

This guide has two parts:
- **Part A** is for anyone who wants to run the project on their own machine.
- **Part B** is for anyone who wants to deploy it for others.

To learn how the pipeline works, see [README.md](README.md). For design decisions and how the brief's requirements are covered, see [DESIGN.md](DESIGN.md).

---

# Part A: Local setup

## A1. Prerequisites

| Requirement | Notes |
|---|---|
| Python **3.10 or newer** | Developed and tested on 3.14.3. Check with `python3 --version`. |
| pip and venv | Included with most Python installs. On Debian/Ubuntu: `sudo apt install python3-venv`. |
| ~200 MB of disk | Mostly for scikit-learn, NumPy and SciPy. |
| No API keys, no network at runtime | The default run is fully offline. Network is needed only for `pip install`. |

## A2. Install

```bash
git clone <repo-url> deriv-ticket-service
cd deriv-ticket-service

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt    # scikit-learn, pydantic, pytest
```

## A3. Run the pipeline

```bash
python main.py
```

This reads `tickets.json` and `kb_articles.json` from the project folder and writes `results.json` and `debug_report.json` next to them. Expected output:

```
Processed 5 ticket(s), rejected 0, escalated 1. Wrote results.json and debug_report.json to /path/to/project
```

You can point it at other files:

```bash
python main.py --tickets path/to/tickets.json --kb path/to/kb_articles.json --out-dir path/to/output/
```

| Exit code | Meaning |
|---|---|
| `0` | Success. Both output files were written. |
| `1` | Fatal input error: a missing or invalid file, or a bad or duplicate KB article. **Nothing was written**, and any previous outputs are left untouched. |

A bad *ticket* does not fail the run. That ticket gets a safe, escalated placeholder result instead.

## A4. Validate and test

```bash
python validate.py        # checks the outputs + reproducibility → "22 passed, 0 failed"
python -m pytest -q       # the full test suite, runs offline
```

## A5. Web demo (optional)

```bash
python demo/server.py                 # http://127.0.0.1:8000
python demo/server.py --port 9000     # use a different port
```

Open the URL in a browser. You can:
- type a ticket, or click one of the sample or adversarial examples;
- click **Run all sample tickets** to process all five at once.

The demo processes everything in memory and never writes files. Stop it with `Ctrl+C`.

## A6. Use your own data

Replace `tickets.json` and/or `kb_articles.json` with files of the same shape:

```json
[{ "id": "T1", "message": "customer text", "language": "en" }]
[{ "article_id": "A1", "title": "Short title", "body": "Help-center text." }]
```

Rules:
- IDs may contain only letters, digits, `_`, `.` and `-`, up to 64 characters.
- Messages must be 2000 characters or fewer.
- Article titles must be 200 characters or fewer and bodies 5000 or fewer.
- Article IDs must be unique.

After changing the KB, run `python validate.py` again. The retrieval thresholds in `src/config.py` were tuned on the 5 sample articles, so a much larger KB may need them adjusted (see B6).

## A7. Optional: LLM reply generator

This is off by default. **Turning it on sends ticket text and KB snippets to a third-party provider.**

```bash
pip install -r requirements-llm.txt
export LLM_ENABLED=true
export DEFAULT_PROVIDER=groq          # or: gemini
export GROQ_API_KEY=gsk_...           # or: GEMINI_API_KEY=...
python main.py
```

- `.env` is **not** loaded automatically. Export the variables yourself, or run `set -a; source .env; set +a`.
- If the key is missing or invalid, or the provider fails, each ticket falls back to the offline template generator. The run still completes, with a warning in the log.
- Trading-advice tickets are never sent to the LLM.

## A8. Configuration reference

**Environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `LLM_ENABLED` | `false` | Must be exactly `true` to use the LLM generator |
| `DEFAULT_PROVIDER` | `groq` | `groq` or `gemini` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | empty | Provider credentials |
| `GROQ_MODEL` / `GEMINI_MODEL` | `openai/gpt-oss-120b` / `gemini-flash-latest` | Model names |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs never contain ticket text. |

**Tunable settings in `src/config.py`:**

| Setting | Default | Effect |
|---|---|---|
| `min_relevance` | 0.08 | Articles scoring below this are not used as evidence |
| `strong_relevance` | 0.30 | Score that counts as full retrieval strength in the confidence score |
| `low_confidence_threshold` | 0.45 | Tickets below this confidence are escalated |
| `top_k` | 3 | Maximum number of articles (always clamped to 1–3) |
| `max_message_chars` | 2000 | Longer tickets get the safe placeholder |

## A9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: sklearn` or `pydantic` | The venv isn't active, or requirements aren't installed. Run `source .venv/bin/activate && pip install -r requirements.txt`. |
| scikit-learn fails to install | Your Python is too new or old for the available wheels. Use Python 3.10–3.14, or run `pip install --upgrade pip` first. |
| `ERROR: tickets.json: file not found` | Check the `--tickets` path. Default paths are relative to the project folder, not your current directory. |
| `ERROR: duplicate article id ...` | Two KB entries share an `article_id`. Fix the KB file. |
| `validate.py` says "results.json matches a fresh run" failed | The inputs changed after you last ran `main.py`. Run `python main.py` again. |
| Demo: `Address already in use` | Port 8000 is busy. Use `--port 9000`. |
| Demo page shows "Could not reach the demo server" | The server isn't running, or it's on a different port from the one in your browser URL. |
| LLM enabled but replies look templated | The LLM call failed and fell back. Check the `WARNING` lines in the log, your key, and that `requirements-llm.txt` is installed. |

---

# Part B: Deployment

## B1. Choose a deployment mode

| Mode | When to use it | What it runs |
|---|---|---|
| **Batch job** (recommended) | Process ticket exports on a schedule, or in CI | `python main.py` |
| **Web demo** | Showcase it to a team on an internal network | `python demo/server.py` behind a reverse proxy |

> **The web demo is not a production API.** It uses Python's built-in HTTP server and has **no authentication, no TLS and no rate limiting**. To expose it beyond localhost, you **must** put it behind a reverse proxy that adds those, as shown below. For real customer data, run it only on an internal network.

## B2. Batch job

The pipeline is a single command with clear exit codes, so any scheduler can run it.

**cron** (every 15 minutes):

```cron
*/15 * * * * cd /opt/ticket-service && .venv/bin/python main.py --tickets /data/in/tickets.json --out-dir /data/out >> /var/log/ticket-service.log 2>&1
```

**CI job** (GitHub Actions example):

```yaml
jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - run: python main.py && python validate.py && python -m pytest -q
      - uses: actions/upload-artifact@v4
        with: { name: results, path: "results.json\ndebug_report.json" }
```

Output files are replaced atomically, so a downstream consumer never reads a half-written `results.json`. If a run fails, the previous file is left in place and the exit code is `1`. Alert on that exit code.

## B3. Web demo on a server (Linux, systemd + nginx)

**1. Install it as a dedicated, unprivileged user:**

```bash
sudo useradd --system --home /opt/ticket-service --shell /usr/sbin/nologin ticketsvc
sudo git clone <repo-url> /opt/ticket-service
cd /opt/ticket-service
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo chown -R ticketsvc: /opt/ticket-service
```

**2. Create a systemd service** at `/etc/systemd/system/ticket-demo.service`. Keep the server bound to `127.0.0.1` so only nginx can reach it.

```ini
[Unit]
Description=Ticket triage web demo
After=network.target

[Service]
User=ticketsvc
WorkingDirectory=/opt/ticket-service
ExecStart=/opt/ticket-service/.venv/bin/python demo/server.py --host 127.0.0.1 --port 8000
Restart=on-failure
Environment=LOG_LEVEL=INFO
# hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadOnlyPaths=/opt/ticket-service

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ticket-demo
sudo systemctl status ticket-demo
```

**3. Put nginx in front** to add TLS, basic auth and rate limiting:

```bash
sudo apt install nginx apache2-utils
sudo htpasswd -c /etc/nginx/.ticket-demo-users demo      # set a password
```

Create `/etc/nginx/sites-available/ticket-demo`:

```nginx
limit_req_zone $binary_remote_addr zone=ticketdemo:10m rate=5r/s;

server {
    listen 443 ssl;
    server_name demo.example.internal;
    ssl_certificate     /etc/ssl/certs/demo.crt;      # e.g. from certbot
    ssl_certificate_key /etc/ssl/private/demo.key;

    auth_basic           "Ticket demo";
    auth_basic_user_file /etc/nginx/.ticket-demo-users;
    client_max_body_size 256k;                          # matches the server's own cap

    location / {
        limit_req zone=ticketdemo burst=10 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_read_timeout 30s;
    }
}
server { listen 80; server_name demo.example.internal; return 301 https://$host$request_uri; }
```

```bash
sudo ln -s /etc/nginx/sites-available/ticket-demo /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## B4. Container (optional)

The project has no Dockerfile by design, since it isn't needed to run it. If your platform needs a container image, this minimal one works:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --system app && chown -R app /app
USER app
EXPOSE 8000
# Inside a container, the server must listen on 0.0.0.0. Expose it only through an authenticating proxy.
CMD ["python", "demo/server.py", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t ticket-service .
docker run --rm -p 127.0.0.1:8000:8000 ticket-service          # web demo, localhost only
docker run --rm -v "$PWD/out:/app/out" ticket-service python main.py --out-dir /app/out   # batch
```

## B5. Pre-deployment security checklist

- [ ] The demo server is bound to `127.0.0.1`, or reachable only through the proxy.
- [ ] TLS, authentication and rate limiting are set up on the proxy.
- [ ] `LLM_ENABLED` is unset, **or** a data-processing agreement is in place with the provider and API keys come from a secret store, never from the repo.
- [ ] `.env` is not in the deployed image or repo (it is already in `.gitignore`).
- [ ] The service runs as an unprivileged user with a read-only code directory.
- [ ] Log retention is set. Logs contain IDs and counts, never ticket text.
- [ ] `python validate.py` and `python -m pytest -q` pass on the deployed build.
- [ ] Reviewers understand that `confidence` is a heuristic and that escalated tickets **must** go to a human.

## B6. Operating it

- **Updating the KB:** replace `kb_articles.json`, run `python main.py && python validate.py`, then spot-check `debug_report.json`. Look at retrieval scores, `insufficient_grounding` counts and escalation reasons.
- **Retuning:** if many relevant tickets escalate with "no KB article passed the relevance threshold", lower `min_relevance` in `src/config.py` a little. If irrelevant articles are being used, raise it. Re-run the tests after any change.
- **Monitoring:** watch the `escalated` count in the run summary and the ratio of `insufficient_grounding` and `suspicious_input` flags in `debug_report.json`. Also watch for the batch job exiting with code `1`.
- **Upgrading dependencies:** `pip install -U -r requirements.txt`, then `python -m pytest -q && python validate.py`. The version ranges in `requirements.txt` stop major-version jumps.
