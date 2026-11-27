"""
LAYER 3 - UNIT / INTEGRATION TESTS (local, offline)

Imports your real app.py and drives it with Flask's test client while the
web-scraper (NewsFetcher) is replaced by a MOCK. That makes these tests:
  * instant and 100% deterministic (no internet, no news-site blocking)
  * able to test logic the live site can't easily show: cache hits,
    force-refresh, history capping, error handling, input normalisation.

These tests auto-skip if app.py (or its dependencies) are not available,
e.g. when the test folder is run outside the project.

Run only this layer:   python run_tests.py --suite unit
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent


def fake_item(label):
    return {
        "title": f"Headline about {label}",
        "link": f"https://news.example.com/{label}",
        "source": "ExampleNews",
        "published": "2026-01-01",
    }


class FakeFetcher:
    """Stands in for news_fetcher.NewsFetcher - records every call."""

    def __init__(self):
        self.stock_calls, self.index_calls = [], []

    def fetch_news(self, stock):
        self.stock_calls.append(stock)
        return [fake_item(stock)]

    def fetch_index_news(self, index):
        self.index_calls.append(index)
        return [fake_item(index)]


@pytest.fixture(scope="module")
def appmod(tmp_path_factory):
    if not (REPO_ROOT / "app.py").exists():
        pytest.skip("app.py not found next to the tests/ folder")
    os.environ["HISTORY_FILE"] = str(tmp_path_factory.mktemp("hist") / "history.json")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        module = importlib.import_module("app")
    except Exception as exc:  # missing dependency, etc.
        pytest.skip(f"cannot import app.py locally: {exc!r}")
    needed = ("app", "news_cache", "news_fetcher", "NewsFetcher", "HISTORY_FILE")
    missing = [n for n in needed if not hasattr(module, n)]
    if missing:
        pytest.skip(f"app.py has a different structure (missing {missing}); "
                    "these unit tests target the original single-file layout")
    return module


@pytest.fixture(autouse=True)
def clean_state(appmod):
    appmod.news_cache.clear()
    hist = Path(appmod.HISTORY_FILE)
    if hist.exists():
        hist.unlink()
    yield


@pytest.fixture
def fake(appmod, monkeypatch):
    f = FakeFetcher()
    monkeypatch.setattr(appmod, "news_fetcher", f)
    monkeypatch.setattr(appmod, "NewsFetcher", lambda: f)
    return f


@pytest.fixture
def client(appmod):
    return appmod.app.test_client()


def search(client, stock, refresh=False):
    return client.post("/search", data={"stock": stock, "force_refresh": str(refresh).lower()})


# ----------------------------------------------------------------------------
class TestPages:
    def test_home_renders(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"<html" in r.data.lower()

    def test_unknown_route_404(self, client):
        assert client.get("/nope").status_code == 404


class TestSearch:
    def test_missing_stock_400(self, client, fake):
        r = client.post("/search", data={})
        assert r.status_code == 400
        assert r.get_json()["error"]

    def test_returns_news_from_fetcher(self, client, fake):
        r = search(client, "TCS")
        assert r.status_code == 200
        assert r.get_json()["news"] == [fake_item("TCS")]

    def test_second_search_uses_cache(self, client, fake):
        search(client, "TCS")
        search(client, "TCS")
        assert fake.stock_calls == ["TCS"], "fetcher should only be called once (cache hit)"

    def test_force_refresh_bypasses_cache(self, client, fake):
        search(client, "TCS")
        search(client, "TCS", refresh=True)
        assert fake.stock_calls == ["TCS", "TCS"]

    def test_non_list_result_is_normalised(self, client, fake, monkeypatch):
        monkeypatch.setattr(fake, "fetch_news", lambda s: None)
        r = search(client, "ZZZ")
        assert r.status_code == 200
        assert r.get_json()["news"] == []

    def test_non_dict_items_are_filtered_out(self, client, fake, monkeypatch):
        monkeypatch.setattr(fake, "fetch_news", lambda s: [fake_item("A"), "junk", 42, None])
        assert search(client, "MIX").get_json()["news"] == [fake_item("A")]

    def test_fetcher_crash_returns_500_json_not_a_stacktrace(self, client, fake, monkeypatch):
        def boom(_):
            raise RuntimeError("site blocked us")

        monkeypatch.setattr(fake, "fetch_news", boom)
        r = search(client, "BAD")
        assert r.status_code == 500
        body = r.get_json()
        assert "error" in body and body["news"] == []


class TestHistory:
    def test_search_is_recorded(self, client, fake):
        search(client, "INFY")
        hist = client.get("/api/history").get_json()
        assert hist[-1]["stock"] == "INFY"
        assert hist[-1]["count"] == 1
        assert "timestamp" in hist[-1]

    def test_history_capped_at_50(self, client, fake):
        for i in range(60):
            search(client, f"S{i}")
        hist = client.get("/api/history").get_json()
        assert len(hist) == 50
        assert hist[-1]["stock"] == "S59"
        assert hist[0]["stock"] == "S10"

    def test_delete_item_is_case_insensitive(self, client, fake):
        search(client, "TCS")
        search(client, "INFY")
        assert client.delete("/api/history/tcs").status_code == 200
        assert [h["stock"] for h in client.get("/api/history").get_json()] == ["INFY"]

    def test_clear_all(self, client, fake):
        search(client, "TCS")
        assert client.delete("/api/history").status_code == 200
        assert client.get("/api/history").get_json() == []


class TestApiNews:
    def test_requires_param(self, client, fake):
        assert client.get("/api/news").status_code == 400

    def test_stock_param(self, client, fake):
        r = client.get("/api/news?stock=TCS")
        assert r.status_code == 200 and r.get_json()["news"] == [fake_item("TCS")]

    @pytest.mark.parametrize("index", ["NIFTY50", "DOWJONES"])
    def test_index_param(self, client, fake, index):
        r = client.get(f"/api/news?index={index}")
        assert r.status_code == 200
        assert fake.index_calls == [index]

    def test_invalid_index_400(self, client, fake):
        assert client.get("/api/news?index=FOO").status_code == 400


class TestCacheStatus:
    def test_unknown_stock(self, client, fake):
        r = client.get("/api/cache-status/NOPE")
        assert r.status_code == 200 and r.get_json()["hasCache"] is False

    def test_known_stock_after_search(self, client, fake):
        """If this fails with a 500, the endpoint expects a (data, timestamp) tuple
        in the cache but /search stores a plain list - a real inconsistency."""
        search(client, "TCS")
        r = client.get("/api/cache-status/TCS")
        assert r.status_code == 200
        assert r.get_json()["hasCache"] is True
