from pathlib import Path

import pytest

from config_loader import ConfigError, load_config

_SOURCES = """
sources:
  - name: google_news_rss
    enabled: true
    priority: 1
    timeout: 6
"""


def _write(tmp_path, body):
    path = Path(tmp_path) / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_ticker_names_the_field(tmp_path):
    path = _write(
        tmp_path,
        "cache_ttl_seconds: 30\nindices: []\nwatchlist:\n  - name: Only Name\n" + _SOURCES,
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "watchlist[0].ticker"
    assert str(caught.value).startswith("watchlist[0].ticker:")


def test_bad_cache_ttl_names_the_field(tmp_path):
    path = _write(
        tmp_path,
        "cache_ttl_seconds: 0\nindices: []\nwatchlist: []\n" + _SOURCES,
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "cache_ttl_seconds"


def test_unknown_source_names_the_field(tmp_path):
    path = _write(
        tmp_path,
        """
cache_ttl_seconds: 30
indices: []
watchlist: []
sources:
  - name: not_a_source
    enabled: true
    priority: 1
    timeout: 6
""",
    )
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "sources[0].name"


def test_client_b_example_loads():
    config = load_config("config.client_b.example.yaml")
    assert [row["ticker"] for row in config.watchlist] == ["AAPL", "MSFT", "JPM"]
    assert config.source_settings["newsapi"]["enabled"] is True
    assert config.source_settings["economic_times"]["enabled"] is False
    assert config.indices[0]["id"] == "DOWJONES"
