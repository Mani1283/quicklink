"""HTTP API for the URL shortener and engineering workflow."""

import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .config import (DB_PATH, HOST, PORT, POST_RATE_LIMIT, POST_RATE_WINDOW_SECONDS,
                     PUBLIC_BASE_URL)
from .database import Database
from .models import DomainError
from .orchestrator import Orchestrator
from .ratelimit import SlidingWindowRateLimiter
from .scenarios import SCENARIOS
from .shortener import ShortenerService


database = Database(DB_PATH)
shortener = ShortenerService(database)
orchestrator = Orchestrator(database)
post_rate_limiter = SlidingWindowRateLimiter(POST_RATE_LIMIT, POST_RATE_WINDOW_SECONDS)


class Handler(BaseHTTPRequestHandler):
    server_version = "AgenticShortener/0.1"
    MAX_BODY_BYTES = 64 * 1024

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/health":
                self._json(200, {"status": "ok"})
            elif path == "/openapi.json":
                schema_path = Path(__file__).with_name("openapi.json")
                self._json(200, json.loads(schema_path.read_text(encoding="utf-8")))
            elif path == "/api/orchestration/scenarios":
                self._json(200, {"scenarios": [self._public_scenario(key, value)
                                                for key, value in SCENARIOS.items()]})
            elif path == "/api/orchestration/metrics":
                self._json(200, orchestrator.metrics())
            elif path == "/api/orchestration/audit/verify":
                self._json(200, orchestrator.verify_audit())
            elif match := re.fullmatch(r"/api/links/([A-Za-z0-9]{4,16})", path):
                link = shortener.get(match.group(1))
                self._json(200, {"code": link.code, "url": link.url,
                                 "short_url": f"{PUBLIC_BASE_URL}/{link.code}",
                                 "created_at": link.created_at.isoformat(),
                                 "expires_at": link.expires_at.isoformat() if link.expires_at else None,
                                 "clicks": link.clicks,
                                 "last_clicked_at": link.last_clicked_at.isoformat()
                                 if link.last_clicked_at else None})
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})", path):
                self._json(200, orchestrator.get_run(match.group(1)))
            elif re.fullmatch(r"/[A-Za-z0-9]{4,16}", path):
                destination = shortener.resolve(path[1:])
                self.send_response(302)
                self.send_header("Location", destination)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self._json(404, {"error": "not found"})
        except DomainError as exc:
            self._json(exc.status, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "run not found"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            allowed, retry_after = post_rate_limiter.allow(self.client_address[0])
            if not allowed:
                self._json(429, {"error": "request rate limit exceeded", "retry_after_seconds": retry_after},
                           {"Retry-After": str(retry_after)})
                return
            payload = self._read_json()
            if path == "/api/shorten":
                link = shortener.create(payload.get("url"), payload.get("expires_in_days"))
                self._json(201, {"code": link.code, "short_url": f"{PUBLIC_BASE_URL}/{link.code}",
                                 "url": link.url, "created_at": link.created_at.isoformat(),
                                 "expires_at": link.expires_at.isoformat() if link.expires_at else None})
            elif path == "/api/orchestration/runs":
                run = orchestrator.create_run(payload.get("scenario"), payload.get("request"),
                                              payload.get("repository_path"))
                self._json(201, run)
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})/approvals", path):
                run = orchestrator.decide(match.group(1), payload.get("gate_id"),
                                           payload.get("decision"), payload.get("actor"),
                                           payload.get("rationale", ""))
                self._json(200, run)
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})/replan", path):
                run = orchestrator.replan(match.group(1), payload.get("request"),
                                          payload.get("actor", ""), payload.get("rationale", ""))
                self._json(200, run)
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})/retry", path):
                run = orchestrator.retry(match.group(1), payload.get("stage_id"),
                                         payload.get("actor", ""), payload.get("rationale", ""))
                self._json(200, run)
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})/rollback", path):
                run = orchestrator.rollback(match.group(1), payload.get("stage_id"),
                                            payload.get("actor", ""), payload.get("rationale", ""))
                self._json(200, run)
            elif match := re.fullmatch(r"/api/orchestration/runs/([0-9a-fA-F-]{36})/stop", path):
                run = orchestrator.stop(match.group(1), payload.get("actor", ""),
                                         payload.get("rationale", ""))
                self._json(200, run)
            else:
                self._json(404, {"error": "not found"})
        except DomainError as exc:
            self._json(exc.status, {"error": str(exc)})
        except KeyError:
            self._json(404, {"error": "run not found"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > self.MAX_BODY_BYTES:
            raise ValueError("request body must be at most 64 KiB")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON request body must be an object")
        return value

    def _json(self, status, value, extra_headers=None):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _public_scenario(key, value):
        return {"id": key, "title": value["title"], "description": value["description"],
                "stages": value["stages"]}

    def log_message(self, format, *args):
        # Default request logs can contain user-controlled paths; keep access logs out of stdout.
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"URL shortener and orchestration API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
