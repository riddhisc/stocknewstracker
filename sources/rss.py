"""Google News RSS. This is the preferred source."""

from __future__ import annotations

from urllib.parse import quote_plus

import feedparser

from sources.base import Article, NewsSource, utc_now_iso
from sources.dates import parse_rss_date, to_iso


def articles_from_feed(xml_text, query, limit=12):
    feed = feedparser.parse(xml_text or "")
    articles = []
    for entry in feed.entries[:limit]:
        title = getattr(entry, "title", "") or ""
        if not title.strip():
            continue
        published = utc_now_iso()
        parsed = getattr(entry, "published_parsed", None)
        if parsed:
            try:
                from datetime import datetime
                published = to_iso(datetime(*parsed[:6]))
            except (TypeError, ValueError):
                published = utc_now_iso()
        elif getattr(entry, "published", None):
            published = to_iso(parse_rss_date(entry.published))
        source = "Google News"
        entry_source = getattr(entry, "source", None)
        if entry_source is not None and getattr(entry_source, "title", None):
            source = entry_source.title
        link = getattr(entry, "link", "") or ""
        summary = getattr(entry, "summary", "") or f"News about {query}"
        articles.append(
            Article(
                title=title.strip(),
                url=link,
                source=source,
                published_at=published,
                summary=summary,
                kind="rss",
            )
        )
    return articles


class GoogleNewsRssSource(NewsSource):
    name = "google_news_rss"
    scopes = frozenset({"rss"})
    default_priority = 1
    default_timeout = 6

    def build_url(self, query):
        return (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        )

    def fetch(self, query: str) -> list[Article]:
        response = self.http.get(self.build_url(query), timeout=self.timeout)
        return articles_from_feed(response.text, query)
