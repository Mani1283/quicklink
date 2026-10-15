"""URL shortener domain service with safe validation and privacy-minimal analytics."""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .config import MAX_EXPIRY_DAYS, MAX_URL_LENGTH
from .database import Database
from .models import DomainError, Link


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def validate_url(url: object) -> str:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise DomainError(f"url must be a non-empty string of at most {MAX_URL_LENGTH} characters")
    if any(ord(char) < 32 for char in url) or "\\" in url:
        raise DomainError("url contains invalid characters")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise DomainError("url must be an absolute http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise DomainError("URLs containing credentials are not allowed")
    try:
        parsed.port
    except ValueError as exc:
        raise DomainError("url contains an invalid port") from exc
    return url


class ShortenerService:
    def __init__(self, database: Database, code_length: int = 8):
        self.database = database
        self.code_length = code_length

    def create(self, url: object, expires_in_days: object = None) -> Link:
        normalized = validate_url(url)
        expiry = None
        if expires_in_days is not None:
            if isinstance(expires_in_days, bool) or not isinstance(expires_in_days, int):
                raise DomainError("expires_in_days must be an integer")
            if not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
                raise DomainError(f"expires_in_days must be between 1 and {MAX_EXPIRY_DAYS}")
            expiry = utc_now() + timedelta(days=expires_in_days)
        now = utc_now()
        with self.database.connect() as connection:
            for _ in range(5):
                code = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")[: self.code_length]
                try:
                    connection.execute(
                        "INSERT INTO links(code,url,created_at,expires_at) VALUES(?,?,?,?)",
                        (code, normalized, iso(now), iso(expiry)),
                    )
                    row = connection.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
                    return self._link(row)
                except sqlite3.IntegrityError:
                    continue
        raise DomainError("could not allocate a unique short code; retry the request", 503)

    def resolve(self, code: str) -> str:
        if not isinstance(code, str) or not code.isalnum() or not 4 <= len(code) <= 16:
            raise DomainError("short code was not found", 404)
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE links SET clicks=clicks+1,last_clicked_at=? "
                "WHERE code=? AND (expires_at IS NULL OR expires_at>?)",
                (iso(now), code, iso(now)),
            )
            if cursor.rowcount != 1:
                raise DomainError("short code was not found or has expired", 404)
            row = connection.execute("SELECT url FROM links WHERE code=?", (code,)).fetchone()
            return row["url"]

    def get(self, code: str) -> Link:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
        if row is None:
            raise DomainError("short code was not found", 404)
        link = self._link(row)
        if link.expires_at and link.expires_at <= utc_now():
            raise DomainError("short code was not found or has expired", 404)
        return link

    @staticmethod
    def _link(row: sqlite3.Row) -> Link:
        return Link(row["code"], row["url"], parse_time(row["created_at"]),
                    parse_time(row["expires_at"]), row["clicks"], parse_time(row["last_clicked_at"]))
