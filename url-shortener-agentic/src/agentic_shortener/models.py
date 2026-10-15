"""Typed domain records."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: datetime
    expires_at: datetime | None
    clicks: int
    last_clicked_at: datetime | None


class DomainError(ValueError):
    """Expected request or domain failure with an HTTP-safe message."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
