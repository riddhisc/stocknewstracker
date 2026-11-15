"""Optional NewsAPI adapter. Search still works when NEWS_API_KEY is empty."""

from __future__ import annotations

import os

from sources.base import Article, NewsSource, SourceError


class NewsApiSource(NewsSource):
    name = "newsapi"
    scopes = frozenset({"stock", "nifty", "dow"})
    default_priority = 100
    default_enabled = False
    default_timeout = 8

    def fetch(self, query: str) -> list[Article]:
        api_key = os.environ.get("NEWS_API_KEY", "").strip()
        if not api_key:
            raise SourceError("NEWS_API_KEY is not set")
        response = self.http.get(
            "https://newsapi.org/v2/everything",
            timeout=self.timeout,
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 10,
            },
            headers={"X-Api-Key": api_key},
        )
        payload = response.json()
        articles = []
        for item in payload.get("articles") or []:
            title = (item.get("title") or "").strip()
            url = item.get("url") or ""
            if not title or not url or title == "[Removed]":
                continue
            source_name = ((item.get("source") or {}).get("name")) or "NewsAPI"
            published = item.get("publishedAt") or ""
            if published and not published.endswith("Z"):
                published = published.replace("+00:00", "Z")
            articles.append(
                Article(
                    title=title,
                    url=url,
                    source=source_name,
                    published_at=published or "",
                    summary=item.get("description") or f"News about {query}",
                    kind="api",
                )
            )
        return articles
