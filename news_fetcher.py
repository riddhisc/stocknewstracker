"""Orchestrate source adapters. RSS is preferred; HTML scrapers are the fallback.

Public methods still return a list of article dicts. The list may carry
`.stale` and `.failed_sources` when an earlier cached copy is served because
live sources failed. Cache entries stay `{"data", "fetched_at"}`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from logutil import log_event
from sources.base import SourceError
from sources.dedupe import dedupe_articles
from sources.registry import build_sources
from sources.rss import articles_from_feed

# One short Bing query each. They run together; the page does not wait on HTML scrapers.
TRENDING_TOPICS = (
    {"id": "markets", "title": "Markets", "query": "India Sensex Nifty stock market"},
    {"id": "companies", "title": "Companies", "query": "Reliance TCS Infosys HDFC Bank shares"},
    {"id": "policy", "title": "Policy", "query": "RBI policy India budget SEBI regulation"},
    {"id": "global", "title": "Global", "query": "Wall Street crude oil global cues India"},
    {"id": "earnings", "title": "Earnings", "query": "India quarterly results earnings guidance"},
)

NIFTY_NAMES = {"NIFTY50", "NIFTY", "NIFTY 50"}
DOW_NAMES = {"DOWJONES", "DOW JONES", "DOW"}


def _direct_href(url):
    """Prefer the publisher URL inside a Bing click redirect. Other http(s) links pass through."""
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host.endswith("bing.com") and "apiclick" in parsed.path:
        raw = unquote(parse_qs(parsed.query).get("url", [""])[0]).strip()
        if raw.startswith(("http://", "https://")):
            return raw
    return text


class NewsList(list):
    def __init__(self, items, stale=False, failed_sources=None):
        super().__init__(items)
        self.stale = stale
        self.failed_sources = list(failed_sources or [])


class NewsFetcher:
    def __init__(self, sources=None):
        self.sources = sources if sources is not None else build_sources()
        self.stock_symbols = {
            "vedanta": ["VEDL", "VEDANTA"],
            "reliance": ["RELIANCE", "RIL"],
            "tcs": ["TCS", "TATA CONSULTANCY"],
            "infosys": ["INFY", "INFOSYS"],
            "hdfc bank": ["HDFCBANK", "HDFC BANK"],
            "icici bank": ["ICICIBANK", "ICICI BANK"],
            "sbi": ["SBIN", "STATE BANK OF INDIA"],
            "tata motors": ["TATAMOTORS", "TATA MOTORS"],
            "wipro": ["WIPRO"],
            "asian paints": ["ASIANPAINT", "ASIAN PAINTS"],
            "hdfc life": ["HDFCLIFE", "HDFC LIFE"],
            "bajaj finance": ["BAJFINANCE", "BAJAJ FINANCE"],
            "bajaj finserv": ["BAJAJFINSV", "BAJAJ FINSERV"],
            "sun pharma": ["SUNPHARMA", "SUN PHARMA"],
            "maruti": ["MARUTI", "MARUTI SUZUKI"],
            "axis bank": ["AXISBANK", "AXIS BANK"],
            "kotak bank": ["KOTAKBANK", "KOTAK BANK"],
            "lt": ["LT", "LARSEN & TOUBRO"],
            "hcl tech": ["HCLTECH", "HCL TECHNOLOGIES"],
            "bharti airtel": ["BHARTIARTL", "BHARTI AIRTEL"],
        }
        self.extra_aliases = {}
        self.news_cache = {}
        self.cache_expiry = 300
        self._markets_path = Path(__file__).resolve().parent / "data" / "markets_now.json"
        self._markets_lock = threading.Lock()
        self._markets_thread = None

    def set_cache_ttl(self, seconds):
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            return
        if seconds > 0:
            self.cache_expiry = seconds

    def apply_source_settings(self, settings):
        by_name = {source.name: source for source in self.sources}
        for name, cfg in (settings or {}).items():
            source = by_name.get(name)
            if source is None or not isinstance(cfg, dict):
                continue
            if "enabled" in cfg:
                source.enabled = bool(cfg["enabled"])
            if "priority" in cfg:
                source.priority = cfg["priority"]
            if "timeout" in cfg:
                source.timeout = cfg["timeout"]
        self.sources.sort(key=lambda source: (source.priority, source.name))

    def fetch_news(self, stock, days_back=7, force=False):
        upper = (stock or "").upper()
        if upper in NIFTY_NAMES:
            return self.fetch_index_news("NIFTY50", force=force)
        if upper in DOW_NAMES:
            return self.fetch_index_news("DOWJONES", force=force)
        return self._fetch(stock, self._search_queries(stock), "stock", [stock], force=force)

    def fetch_index_news(self, index_name, force=False):
        if index_name == "NIFTY50":
            queries = [
                "Nifty 50",
                "Nifty50",
                "NSE index",
                "NSE Nifty",
                "Indian market index",
                "Sensex today",
            ]
            scope = "nifty"
        elif index_name == "DOWJONES":
            queries = [
                "Dow Jones",
                "DJIA",
                "Dow Jones Industrial Average",
                "US market index",
                "Wall Street index",
                "S&P 500 today",
            ]
            scope = "dow"
        else:
            queries = [index_name]
            scope = "stock"
        return self._fetch(index_name, queries, scope, [index_name], force=force, index=True)

    def markets_snapshot(self):
        """Saved strip for the homepage. Does not call Bing. A stale or missing file refreshes in the background."""
        payload = self._read_markets()
        fresh = bool(payload) and self._markets_fresh(payload)
        if not fresh:
            self._ensure_refresh(wait=False)
        sections = self._normalize(payload.get("sections") if payload else None)
        return sections, bool(payload) and not fresh

    def fetch_trending(self, force=False):
        """Five topics. A fresh file returns at once. A stale file returns at once and refreshes behind it.

        A missing file waits for one Bing pass. Returns (sections, stale, cached).
        """
        payload = None if force else self._read_markets()
        if payload and self._markets_fresh(payload):
            log_event(logging.INFO, "news_cache", symbol="TRENDING", outcome="hit")
            return self._normalize(payload.get("sections")), False, True
        if payload and not force:
            self._ensure_refresh(wait=False)
            log_event(logging.WARNING, "news_fetch", symbol="TRENDING", outcome="stale")
            return self._normalize(payload.get("sections")), True, True
        self._ensure_refresh(wait=True)
        payload = self._read_markets()
        sections = self._normalize(payload.get("sections") if payload else None)
        return sections, False, False

    def _ensure_refresh(self, wait):
        with self._markets_lock:
            thread = self._markets_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._refresh_job, name="markets-now", daemon=True)
                self._markets_thread = thread
                thread.start()
        if wait:
            thread.join(timeout=12)

    def _refresh_job(self):
        previous = self._read_markets()
        loaded = self._load_trending()
        merged = self._merge_topics(previous, loaded)
        if any(section.get("news") for section in merged):
            self._write_markets(merged)

    def _load_trending(self):
        bing = next((source for source in self.sources if source.name == "bing_news_rss" and source.enabled), None)
        if bing is None:
            return self._normalize(None)
        bing.http.allowed(bing.build_url(TRENDING_TOPICS[0]["query"]))
        with ThreadPoolExecutor(max_workers=len(TRENDING_TOPICS)) as pool:
            futures = [pool.submit(self._trending_topic, bing, topic) for topic in TRENDING_TOPICS]
            return [future.result() for future in futures]

    def _trending_topic(self, bing, topic):
        news = []
        try:
            response = bing.http.get(
                bing.build_url(topic["query"]), timeout=3, attempts=1, pace=False
            )
            articles = articles_from_feed(
                response.text, topic["query"], limit=4, default_source="Bing News"
            )
        except Exception as exc:
            log_event(
                logging.WARNING,
                "source_fetch",
                source="bing_news_rss",
                outcome="error",
                error=exc.__class__.__name__,
                topic=topic["id"],
            )
            articles = []
        for article in articles:
            href = _direct_href(article.url)
            if not article.title or not href:
                continue
            payload = article.as_dict()
            payload["url"] = href
            news.append(payload)
            break
        return {"id": topic["id"], "title": topic["title"], "news": news}

    def _normalize(self, sections):
        by_id = {}
        for section in sections or []:
            if isinstance(section, dict) and section.get("id"):
                by_id[section["id"]] = section
        normalized = []
        for topic in TRENDING_TOPICS:
            current = by_id.get(topic["id"]) or {}
            news = []
            for item in current.get("news") or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = _direct_href(item.get("url"))
                if not title or not url:
                    continue
                news.append({
                    "title": title,
                    "url": url,
                    "source": str(item.get("source") or "").strip(),
                    "published_at": str(item.get("published_at") or ""),
                    "type": item.get("type") or "rss",
                })
                break
            normalized.append({"id": topic["id"], "title": topic["title"], "news": news})
        return normalized

    def _merge_topics(self, previous, loaded):
        prior = self._normalize(previous.get("sections") if isinstance(previous, dict) else None)
        fresh = self._normalize(loaded)
        merged = []
        for old, new in zip(prior, fresh):
            merged.append({
                "id": new["id"],
                "title": new["title"],
                "news": new["news"] or old["news"],
            })
        return merged

    def _markets_fresh(self, payload):
        fetched_at = payload.get("fetched_at") if isinstance(payload, dict) else None
        if not isinstance(fetched_at, (int, float)):
            return False
        return time.time() - fetched_at < self.cache_expiry

    def _read_markets(self):
        try:
            payload = json.loads(self._markets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
            return None
        return payload

    def _write_markets(self, sections):
        payload = {"fetched_at": time.time(), "sections": self._normalize(sections)}
        self._markets_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._markets_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._markets_path)

    def _search_queries(self, stock):
        terms = [stock]
        key = stock.lower()
        if key in self.stock_symbols:
            terms.extend(self.stock_symbols[key])
        if key in self.extra_aliases:
            terms.extend(self.extra_aliases[key])
        for alias_key, aliases in self.extra_aliases.items():
            if stock.lower() in {alias_key, *(item.lower() for item in aliases)}:
                terms.extend(aliases)
                terms.append(alias_key)
        if "limited" not in stock.lower() and "ltd" not in stock.lower():
            terms.append(f"{stock} Limited")
        if stock.isupper() and len(stock) <= 10:
            terms.append(f"{stock} stock")
            terms.append(f"{stock} share")
        if key == "vedanta" or stock.upper() == "VEDL":
            terms.extend(["VEDL", "Vedanta"])
        elif key == "infosys" or stock.upper() == "INFY":
            terms.extend(["INFY", "Infosys"])
        unique = []
        seen = set()
        for term in terms:
            marker = term.lower()
            if marker in seen or not str(term).strip():
                continue
            seen.add(marker)
            unique.append(term)
        return unique

    def _fetch(self, key, queries, scope, symbols, force=False, index=False):
        if not force:
            cached = self._cache_get(key)
            if cached is not None:
                log_event(logging.INFO, "news_cache", symbol=key, outcome="hit")
                return NewsList(cached, stale=False)
        current_queries = queries[:2] or [key]
        log_event(
            logging.INFO,
            "news_fetch",
            symbol=key,
            scope=scope,
            queries=current_queries,
        )
        rss_queries = [f"{term} market" if index else f"{term} stock market" for term in current_queries]
        articles, failed = self._run_rss(rss_queries)
        if not articles:
            fallback, fallback_failed = self._run_fallback(scope, current_queries[0])
            articles.extend(fallback)
            failed.extend(fallback_failed)
        return self._finish(key, articles, failed, symbols)

    def _enabled(self, predicate):
        return [source for source in self.sources if source.enabled and predicate(source)]

    def _run_rss(self, queries):
        sources = self._enabled(lambda source: "rss" in source.scopes)
        articles = []
        failed = []
        if not sources or not queries:
            return articles, failed
        workers = min(4, len(queries) * len(sources))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for source in sources:
                for query in queries:
                    futures.append(pool.submit(self._call_source, source, query))
            for future in as_completed(futures):
                batch, ok, name = future.result()
                articles.extend(batch)
                if not ok and name not in failed:
                    failed.append(name)
        return articles, failed

    def _run_fallback(self, scope, query):
        sources = self._enabled(
            lambda source: "rss" not in source.scopes and scope in source.scopes
        )
        articles = []
        failed = []
        for source in sources:
            batch, ok, name = self._call_source(source, query)
            articles.extend(batch)
            if not ok and name not in failed:
                failed.append(name)
        return articles, failed

    def _call_source(self, source, query):
        started = time.perf_counter()
        try:
            articles = source.fetch(query)
        except SourceError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            source.mark_failure(exc, latency_ms)
            log_event(
                logging.WARNING,
                "source_fetch",
                source=source.name,
                outcome="error",
                latency_ms=round(latency_ms, 1),
                error=str(exc)[:240],
            )
            return [], False, source.name
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            source.mark_failure(exc.__class__.__name__, latency_ms)
            log_event(
                logging.WARNING,
                "source_fetch",
                source=source.name,
                outcome="error",
                latency_ms=round(latency_ms, 1),
                error=exc.__class__.__name__,
            )
            return [], False, source.name
        latency_ms = (time.perf_counter() - started) * 1000
        degraded = bool(getattr(source.http, "last_degraded", False))
        source.mark_success(latency_ms, degraded=degraded)
        log_event(
            logging.INFO,
            "source_fetch",
            source=source.name,
            outcome="degraded" if degraded else "ok",
            latency_ms=round(latency_ms, 1),
            count=len(articles),
        )
        for article in articles:
            if query and not article.symbols:
                article.symbols = []
        return articles, True, source.name

    def _finish(self, key, articles, failed, symbols):
        for article in articles:
            if symbols:
                article.symbols = list(dict.fromkeys([*article.symbols, *symbols]))
        unique = dedupe_articles(articles)
        if unique:
            payload = [article.as_dict() for article in unique]
            self._cache_put(key, payload)
            log_event(logging.INFO, "news_fetch", symbol=key, outcome="ok", count=len(payload))
            return NewsList(payload, stale=False, failed_sources=failed)
        previous = [
            item for item in (self._cache_peek(key) or [])
            if isinstance(item, dict) and item.get("type") != "info"
        ]
        if previous and failed:
            log_event(
                logging.WARNING,
                "news_fetch",
                symbol=key,
                outcome="stale",
                failed_sources=failed,
                count=len(previous),
            )
            return NewsList(previous, stale=True, failed_sources=failed)
        log_event(logging.INFO, "news_fetch", symbol=key, outcome="empty", failed_sources=failed)
        return NewsList([], stale=False, failed_sources=failed)

    def _cache_put(self, key, articles):
        self.news_cache[key] = {"data": articles, "fetched_at": time.time()}

    def _cache_get(self, key):
        entry = self.news_cache.get(key)
        if not isinstance(entry, dict):
            return None
        fetched_at = entry.get("fetched_at")
        data = entry.get("data")
        if not isinstance(fetched_at, (int, float)) or not isinstance(data, list):
            return None
        if time.time() - fetched_at >= self.cache_expiry:
            return None
        if data and all(isinstance(item, dict) and item.get("type") == "info" for item in data):
            return None
        return data

    def _cache_peek(self, key):
        entry = self.news_cache.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), list):
            return None
        return entry["data"]
