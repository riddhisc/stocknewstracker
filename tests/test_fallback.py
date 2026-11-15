import pytest
import requests

import sources.http as http_module
from news_fetcher import NewsFetcher
from sources.base import Article, NewsSource, SourceError
from sources.http import HttpClient


class _Down(NewsSource):
    name = "google_news_rss"
    scopes = frozenset({"rss"})

    def fetch(self, query):
        raise SourceError("timeout")


class _Ok(NewsSource):
    name = "yahoo_finance"
    scopes = frozenset({"stock"})
    default_priority = 10

    def fetch(self, query):
        return [
            Article(
                title="Infosys keeps guidance",
                url="https://example.com/infy",
                source="Desk",
                published_at="2026-01-02T00:00:00Z",
                summary="Guidance unchanged.",
                kind="scrape",
            )
        ]


def test_one_failing_source_does_not_drop_the_other():
    fetcher = NewsFetcher(sources=[_Down(http=None), _Ok(http=None)])
    result = fetcher.fetch_news("INFY", force=True)
    assert result.stale is False
    assert result[0]["title"] == "Infosys keeps guidance"
    assert "google_news_rss" in result.failed_sources


def test_empty_result_is_not_a_fake_story():
    fetcher = NewsFetcher(sources=[_Down(http=None)])
    result = fetcher.fetch_news("AAVAS", force=True)
    assert list(result) == []
    assert result.stale is False
    assert "AAVAS" not in fetcher.news_cache


def test_total_failure_serves_earlier_copy():
    fetcher = NewsFetcher(sources=[_Down(http=None)])
    fetcher.news_cache["INFY"] = {
        "data": [{
            "title": "Earlier Infosys copy",
            "url": "https://example.com/old",
            "source": "Desk",
            "published_at": "2026-01-01T00:00:00Z",
            "summary": "old",
            "description": "old",
            "symbols": ["INFY"],
            "type": "rss",
        }],
        "fetched_at": 0,
    }
    result = fetcher.fetch_news("INFY", force=True)
    assert result.stale is True
    assert result[0]["title"] == "Earlier Infosys copy"


def test_http_timeout_becomes_source_error(monkeypatch):
    def timed_out(*_args, **_kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(http_module.requests, "get", timed_out)
    client = HttpClient(min_interval=0, max_attempts=1)
    with pytest.raises(SourceError):
        client.get("https://example.com/rss", timeout=0.1)
