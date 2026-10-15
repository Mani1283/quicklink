"""SQLite schema and short-lived connection management."""

import sqlite3
import uuid
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS links (
    code TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    clicks INTEGER NOT NULL DEFAULT 0 CHECK(clicks >= 0),
    last_clicked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_links_expiry ON links(expires_at);
CREATE TABLE IF NOT EXISTS orchestration_runs (
    run_id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    request TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_version INTEGER NOT NULL DEFAULT 1,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orchestration_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES orchestration_runs(run_id),
    at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    stage_id TEXT,
    actor TEXT,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON orchestration_events(run_id, event_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self._memory = str(path) == ":memory:"
        self.path = f"file:shortener-{uuid.uuid4().hex}?mode=memory&cache=shared" if self._memory else str(path)
        if self.path != ":memory:":
            if not self._memory:
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._anchor = self.connect() if self._memory else None
        connection = self._anchor or self.connect()
        connection.executescript(SCHEMA)
        if not self._memory:
            connection.close()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False, uri=self._memory)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection
