import json
from unittest.mock import patch

import requests

from history_store import HistoryStore
from summaries import apply_summaries, parse_summary_text


def _article(url="https://example.com/tcs"):
    return {
        "title": "TCS keeps margin guidance",
        "url": url,
        "source": "Mint",
        "summary": "The company left its margin band unchanged.",
        "description": "The company left its margin band unchanged.",
        "type": "rss",
    }


def _store(tmp_path):
    return HistoryStore(tmp_path / "summaries.db", json_path=tmp_path / "missing.json")


def test_disabled_does_not_call_the_network(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SUMMARY", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with patch("summaries.requests.post") as post:
        result = apply_summaries([_article()], "TCS", _store(tmp_path))
    post.assert_not_called()
    assert "llm_summary" not in result[0]


def test_missing_key_returns_articles(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SUMMARY", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("summaries.requests.post") as post:
        result = apply_summaries([_article()], "TCS", _store(tmp_path))
    post.assert_not_called()
    assert result[0]["title"] == "TCS keeps margin guidance"
    assert "llm_summary" not in result[0]


def test_summary_is_cached_by_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SUMMARY", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    body = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "summary": "Margins held steady. Demand from banks stayed firm. The tone is constructive.",
                "sentiment": "positive",
            }),
        }]
    }
    response = type("Response", (), {})()
    response.status_code = 200
    response.json = lambda: body
    store = _store(tmp_path)
    with patch("summaries.requests.post", return_value=response) as post:
        first = apply_summaries([_article()], "TCS", store)
        second = apply_summaries([_article()], "TCS", store)
        assert post.call_count == 1
        sent_url = post.call_args.args[0]
        assert "api.anthropic.com" in sent_url
        assert "test-key-not-real" not in sent_url
        assert post.call_args.kwargs["headers"]["x-api-key"] == "test-key-not-real"
    assert first[0]["sentiment"] == "positive"
    assert second[0]["llm_summary"].startswith("Margins held")
    assert "positive" == store.get_summary("https://example.com/tcs")["sentiment"]


def test_timeout_returns_articles_without_summaries(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_SUMMARY", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with patch("summaries.requests.post", side_effect=requests.Timeout("slow")):
        result = apply_summaries([_article()], "TCS", _store(tmp_path))
    assert result[0]["title"] == "TCS keeps margin guidance"
    assert "llm_summary" not in result[0]


def test_parse_summary_text_accepts_fenced_json():
    summary, sentiment = parse_summary_text(
        '```json\n{"summary": "Orders improved. Collections were flat. The read is mixed.", "sentiment": "Neutral"}\n```'
    )
    assert sentiment == "neutral"
    assert summary.startswith("Orders improved")
