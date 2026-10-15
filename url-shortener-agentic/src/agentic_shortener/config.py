"""Runtime configuration sourced from environment variables."""

import os
from pathlib import Path


HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DB_PATH = Path(os.getenv("SHORTENER_DB", "data/shortener.db"))
AUDIT_PATH = Path(os.getenv("ORCHESTRATION_AUDIT", "data/orchestration-audit.jsonl"))
ARTIFACTS_DIR = Path(os.getenv("ORCHESTRATION_ARTIFACTS", "artifacts/runs"))
POST_RATE_LIMIT = int(os.getenv("POST_RATE_LIMIT", "60"))
POST_RATE_WINDOW_SECONDS = int(os.getenv("POST_RATE_WINDOW_SECONDS", "60"))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_REPOSITORY_ROOTS = tuple(Path(path).expanduser() for path in
                                 os.getenv("ALLOWED_REPOSITORY_ROOTS", str(PROJECT_ROOT)).split(os.pathsep)
                                 if path.strip())
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "deterministic").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://{HOST}:{PORT}").rstrip("/")
MAX_URL_LENGTH = 2048
MAX_EXPIRY_DAYS = 3650
