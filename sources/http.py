"""HTTP helper: timeout, bounded retries, User-Agent, robots.txt, low rate."""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from logutil import log_event
from sources.base import SourceError

USER_AGENT = (
    "StockNewsTracker/1.0 (+https://github.com/riddhisc/stocknewstracker; portfolio)"
)
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, user_agent=USER_AGENT, min_interval=0.5, max_attempts=3):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._next = {}
        self._lock = threading.Lock()
        self._robots = {}
        self._robots_lock = threading.Lock()
        self._local = threading.local()

    def get(self, url, timeout, params=None, headers=None):
        self._local.degraded = False
        if not self.allowed(url):
            log_event(
                logging.WARNING,
                "source_request",
                outcome="blocked",
                url=url,
                error="robots.txt",
            )
            raise SourceError("blocked by robots.txt")

        self._pace(url)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            **(headers or {}),
        }
        last_error = "request failed"
        for attempt in range(self.max_attempts):
            started = time.perf_counter()
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
            except requests.Timeout:
                last_error = "timeout"
            except requests.RequestException as exc:
                last_error = exc.__class__.__name__
            else:
                elapsed_ms = (time.perf_counter() - started) * 1000
                status = response.status_code
                if status == 200 and len(response.text) > 100:
                    self._local.degraded = attempt > 0
                    return response
                if status in _RETRY_STATUSES:
                    last_error = f"HTTP {status}"
                else:
                    log_event(
                        logging.WARNING,
                        "source_request",
                        outcome="error",
                        url=url,
                        status=status,
                        latency_ms=round(elapsed_ms, 1),
                        attempt=attempt + 1,
                    )
                    raise SourceError(f"HTTP {status}")
            if attempt < self.max_attempts - 1:
                time.sleep(0.4 * (2 ** attempt))

        self._local.degraded = False
        log_event(
            logging.WARNING,
            "source_request",
            outcome="error",
            url=url,
            error=last_error,
            attempts=self.max_attempts,
        )
        raise SourceError(last_error)

    @property
    def last_degraded(self):
        return bool(getattr(self._local, "degraded", False))

    def allowed(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots_for(base)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _robots_for(self, base):
        with self._robots_lock:
            if base in self._robots:
                return self._robots[base]
        parser = None
        try:
            response = requests.get(
                base + "/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=4,
            )
            if response.status_code == 200 and response.text.strip():
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
        except requests.RequestException as exc:
            log_event(
                logging.INFO,
                "robots",
                outcome="skip",
                url=base + "/robots.txt",
                error=exc.__class__.__name__,
            )
        with self._robots_lock:
            self._robots[base] = parser
        return parser

    def _pace(self, url):
        host = urlparse(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            earliest = self._next.get(host, now)
            wait = max(0.0, earliest - now)
            self._next[host] = max(earliest, now) + self.min_interval
        if wait:
            time.sleep(wait)
