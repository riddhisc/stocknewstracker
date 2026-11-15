"""Build the adapter list. Defaults match the previous RSS-first fetcher."""

from __future__ import annotations

from sources.http import HttpClient
from sources.newsapi import NewsApiSource
from sources.rss import GoogleNewsRssSource
from sources.scrapers import (
    CnbcSource,
    EconomicTimesNiftySource,
    EconomicTimesSource,
    FinancialExpressSource,
    GoogleNewsHtmlSource,
    LivemintSource,
    MarketWatchSource,
    NdtvSource,
    ReutersSource,
    YahooFinanceSource,
)

SOURCE_CLASSES = [
    GoogleNewsRssSource,
    YahooFinanceSource,
    EconomicTimesSource,
    EconomicTimesNiftySource,
    LivemintSource,
    GoogleNewsHtmlSource,
    ReutersSource,
    FinancialExpressSource,
    NdtvSource,
    MarketWatchSource,
    CnbcSource,
    NewsApiSource,
]


def build_sources(http=None, settings=None):
    """settings maps source name -> {enabled, priority, timeout}."""
    http = http or HttpClient()
    settings = settings or {}
    sources = []
    for cls in SOURCE_CLASSES:
        cfg = settings.get(cls.name) or {}
        source = cls(
            http=http,
            timeout=cfg.get("timeout"),
            priority=cfg.get("priority"),
            enabled=cfg.get("enabled"),
        )
        sources.append(source)
    sources.sort(key=lambda source: (source.priority, source.name))
    return sources
