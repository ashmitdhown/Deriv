"""Local web demo: python demo/server.py [--port 8000]  ->  http://127.0.0.1:8000

Standard library only. Binds to localhost, caps request size, and runs the real offline
pipeline on the submitted tickets. Nothing is written to disk.
"""
from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.pipeline import Pipeline, PipelineError  # noqa: E402
from src.utils import load_json_list  # noqa: E402

MAX_BODY = 256 * 1024
MAX_DEMO_TICKETS = 50
INDEX_HTML = (Path(__file__).parent / "index.html").read_bytes()


def process(payload: object) -> tuple[int, dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tickets"), list):
        return 400, {"error": 'body must be {"tickets": [...], "kb"?: [...]}'}
    if len(payload["tickets"]) > MAX_DEMO_TICKETS:
        return 400, {"error": f"at most {MAX_DEMO_TICKETS} tickets per request"}
    kb = payload.get("kb") or load_json_list(settings.kb_path)
    try:
        out = Pipeline().process_records(payload["tickets"], kb)
    except PipelineError as e:
        return 422, {"error": str(e)}
    return 200, {"results": out.results, "debug": out.debug}


class Handler(BaseHTTPRequestHandler):
    server_version = "TicketDemo/1.0"

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: object) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif self.path == "/api/samples":
            self._json(200, {"tickets": load_json_list(settings.tickets_path), "kb": load_json_list(settings.kb_path)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/process":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"body must be <= {MAX_BODY} bytes"})
        try:
            payload = json.loads(self.rfile.read(length) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        try:
            status, body = process(payload)
        except Exception:  # noqa: BLE001 - never leak tracebacks to the client
            status, body = 500, {"error": "internal error"}
        self._json(status, body)

    def log_message(self, fmt: str, *args: object) -> None:  # request line only, no bodies
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    print(f"Demo running at http://{a.host}:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
