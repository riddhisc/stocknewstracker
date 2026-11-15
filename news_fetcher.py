"""Orchestrate source adapters. RSS is preferred; HTML scrapers are the fallback.

Public methods still return a list of article dicts. The list may carry
`.stale` and `.failed_sources` when an earlier cached copy is served because
live sources failed. Cache entries stay `{"data", "fetched_at"}`.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

from logutil import log_event
from sources.base import SourceError, utc_now_iso
from sources.dedupe import dedupe_articles
from sources.registry import build_sources

NIFTY_NAMES = {"NIFTY50", "NIFTY", "NIFTY 50"}
DOW_NAMES = {"DOWJONES", "DOW JONES", "DOW"}


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
        placeholder = {
            "title": f"No recent news found for {key}",
            "description": "Try another search term or check back later for updates.",
            "summary": "Try another search term or check back later for updates.",
            "url": "https://www.google.com/search?q=" + quote_plus(f"{key} stock news"),
            "source": "Info",
            "published_at": utc_now_iso(),
            "symbols": list(symbols),
            "type": "info",
        }
        if key == "NIFTY50":
            placeholder["description"] = "Try again later for market updates."
            placeholder["summary"] = placeholder["description"]
        elif key == "DOWJONES":
            placeholder["description"] = "Try again later for market updates."
            placeholder["summary"] = placeholder["description"]
        self._cache_put(key, [placeholder])
        log_event(logging.INFO, "news_fetch", symbol=key, outcome="empty", failed_sources=failed)
        return NewsList([placeholder], stale=False, failed_sources=failed)

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
        return data

    def _cache_peek(self, key):
        entry = self.news_cache.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), list):
            return None
        return entry["data"]
