"""HTTP helper: timeout, bounded retries, User-Agent, robots.txt, low rate."""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlparse

import requests

from logutil import log_event
from sources.base import SourceError

USER_AGENT = (
    "StockNewsTracker/1.0 (+https://github.com/riddhisc/stocknewstracker; portfolio)"
)


def rules_for_agent(text, user_agent):
    """Rules for the most specific matching group. An empty list allows every URL."""
    groups = []
    agents = []
    rules = []
    seen_rule = False

    def flush():
        nonlocal agents, rules, seen_rule
        if agents:
            groups.append((agents, rules))
        agents = []
        rules = []
        seen_rule = False

    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if seen_rule:
                flush()
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and agents:
            seen_rule = True
            rules.append((key == "allow", value))
    flush()

    product = (user_agent or "").split("/", 1)[0].strip().lower()
    wildcard = None
    for group_agents, group_rules in groups:
        if any(agent not in {"", "*"} and agent in product for agent in group_agents):
            return group_rules
        if "*" in group_agents and wildcard is None:
            wildcard = group_rules
    return wildcard or []


def path_allowed(rules, url):
    """Longest robots match wins. A failed or empty rule list does not block."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    query_path = path + (("?" + parsed.query) if parsed.query else "")
    best_len = -1
    best_allow = True
    for allow, rule in rules or []:
        if rule == "" and not allow:
            continue
        end = rule.endswith("$")
        pattern = rule[:-1] if end else rule
        target = query_path if "?" in rule else path
        if not _rule_matches(pattern, target, end):
            continue
        length = len(rule)
        if length > best_len or (length == best_len and allow and not best_allow):
            best_len = length
            best_allow = allow
    return best_allow


def _rule_matches(pattern, target, end):
    if pattern == "":
        return not end or target == ""
    regex = re.escape(pattern).replace(r"\*", ".*")
    if end:
        return re.fullmatch(regex, target) is not None
    return re.match(regex, target) is not None
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

    def get(self, url, timeout, params=None, headers=None, attempts=None, pace=True):
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

        if pace:
            self._pace(url)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            **(headers or {}),
        }
        last_error = "request failed"
        tries = self.max_attempts if attempts is None else max(1, int(attempts))
        for attempt in range(tries):
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
            if attempt < tries - 1:
                time.sleep(0.4 * (2 ** attempt))

        self._local.degraded = False
        log_event(
            logging.WARNING,
            "source_request",
            outcome="error",
            url=url,
            error=last_error,
            attempts=tries,
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
        rules = self._robots_for(base)
        if rules is None:
            return True
        try:
            return path_allowed(rules, url)
        except Exception:
            return True

    def _robots_for(self, base):
        with self._robots_lock:
            if base in self._robots:
                return self._robots[base]
        rules = None
        try:
            response = requests.get(
                base + "/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=4,
            )
            if response.status_code == 200 and response.text.strip():
                rules = rules_for_agent(response.text, self.user_agent)
            else:
                # A missing or refused robots.txt is not a disallow.
                rules = []
        except requests.RequestException as exc:
            log_event(
                logging.INFO,
                "robots",
                outcome="skip",
                url=base + "/robots.txt",
                error=exc.__class__.__name__,
            )
        with self._robots_lock:
            self._robots[base] = rules
        return rules

    def _pace(self, url):
        host = urlparse(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            earliest = self._next.get(host, now)
            wait = max(0.0, earliest - now)
            self._next[host] = max(earliest, now) + self.min_interval
        if wait:
            time.sleep(wait)
