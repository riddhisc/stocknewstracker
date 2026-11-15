"""Shared article shape and the adapter contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


class SourceError(Exception):
    """Raised when a source cannot be fetched. An empty match list is not an error."""


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: str
    summary: str
    symbols: list[str] = field(default_factory=list)
    kind: str = "rss"

    def as_dict(self):
        summary = self.summary or ""
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": summary,
            "description": summary,
            "symbols": list(self.symbols),
            "type": self.kind,
        }


class NewsSource:
    """Fetch normalized articles for one query and report health."""

    name = "source"
    scopes = frozenset({"stock"})
    default_timeout = 6
    default_priority = 100
    default_enabled = True

    def __init__(self, http, timeout=None, priority=None, enabled=None):
        self.http = http
        self.timeout = self.default_timeout if timeout is None else timeout
        self.priority = self.default_priority if priority is None else priority
        self.enabled = self.default_enabled if enabled is None else enabled
        self.status = "ok"
        self.last_success_at = None
        self.last_error = None
        self.last_latency_ms = None
        self.consecutive_failures = 0

    def fetch(self, query: str) -> list[Article]:
        raise NotImplementedError

    def mark_success(self, latency_ms, degraded=False):
        self.last_success_at = utc_now_iso()
        self.last_latency_ms = round(latency_ms, 1)
        self.last_error = None
        self.consecutive_failures = 0
        self.status = "degraded" if degraded else "ok"

    def mark_failure(self, message, latency_ms):
        self.last_latency_ms = round(latency_ms, 1)
        self.last_error = str(message)[:300]
        self.consecutive_failures += 1
        self.status = "degraded" if self.last_success_at else "down"

    def health(self):
        return {
            "name": self.name,
            "status": self.status,
            "last_success": self.last_success_at,
            "last_error": self.last_error,
            "latency_ms": self.last_latency_ms,
            "enabled": self.enabled,
        }
