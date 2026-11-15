"""Structured logs for the request and source path. Never log secret values."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_SECRET_EXACT = {
    "key",
    "apikey",
    "api_key",
    "token",
    "password",
    "secret",
    "authorization",
    "smtp_pass",
}
_QUERY_REDACT = {"apikey", "api_key", "key", "token", "access_token"}
_configured = False


def configure_logging():
    global _configured
    if _configured:
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger("stocktracker")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _configured = True


def redact_url(url):
    if not isinstance(url, str) or "://" not in url:
        return url
    parsed = urlparse(url)
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _QUERY_REDACT:
            pairs.append((key, "REDACTED"))
        else:
            pairs.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def _is_secret_field(name):
    lowered = str(name).lower().replace("-", "_")
    if lowered in _SECRET_EXACT:
        return True
    return (
        lowered.endswith("_key")
        or lowered.endswith("_token")
        or lowered.endswith("_password")
        or "secret" in lowered
    )


def _safe_value(key, value):
    if _is_secret_field(key):
        return None
    if isinstance(value, str):
        if "://" in value:
            return redact_url(value)[:500]
        if any(hint in value.lower() for hint in ("apikey=", "api_key=", "bearer ")):
            return "[redacted]"
        return value[:500]
    return value


def log_event(level, event, **fields):
    configure_logging()
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
    }
    for key, value in fields.items():
        safe = _safe_value(key, value)
        if safe is not None:
            payload[key] = safe
    logging.getLogger("stocktracker").log(level, json.dumps(payload, default=str))
