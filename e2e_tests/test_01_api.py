"""
LAYER 1 - API / HTTP TESTS (live site, no browser needed)

Checks every endpoint of the Flask backend: availability, the news search
(web-scraping) pipeline, search history, caching, bad/hostile input,
basic security hygiene and light load.

Run only this layer:   python run_tests.py --suite api
"""
import concurrent.futures as cf
import statistics
import warnings
from datetime import datetime

import pytest

pytestmark = pytest.mark.api

LARGE_CAPS = ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
INDICES = ["NIFTY 50", "SENSEX"]
QA_STOCK = "QATESTSTOCK"  # unique name so we never touch real users' history


# --------------------------------------------------------------------------- helpers
def as_json(resp):
    try:
        return resp.json()
    except ValueError:
        pytest.fail(
            f"Expected JSON but got {resp.headers.get('content-type')}: {resp.text[:200]!r}"
        )


def post_search(site, stock, refresh=False):
    return site.post(
        "/search",
        data={"stock": stock, "force_refresh": "true" if refresh else "false"},
    )


def assert_valid_news_item(item):
    """Schema-agnostic check: a news item is a non-empty dict that carries some
    readable text and at least one http(s) link."""
    assert isinstance(item, dict) and item, f"News item is empty/not a dict: {item!r}"
    strings = [v for v in item.values() if isinstance(v, str) and v.strip()]
    assert strings, f"News item has no text: {item!r}"
    assert any(s.startswith(("http://", "https://")) for s in strings), (
        f"News item has no link: {item!r}"
    )


@pytest.fixture
def qa_cleanup(site):
    yield
    site.delete(f"/api/history/{QA_STOCK}")


# --------------------------------------------------------------------------- 1. availability
class TestAvailability:
    def test_homepage_returns_200_html(self, site):
        r = site.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_homepage_has_expected_content(self, site):
        html = site.get("/").text
        assert "Indian Stock News Tracker" in html
        assert "<input" in html, "search input missing from page"

    def test_results_page_returns_200(self, site):
        r = site.get("/results")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_unknown_page_is_404_not_500(self, site):
        assert site.get("/this-page-does-not-exist-qa").status_code == 404

    def test_favicon_does_not_crash(self, site):
        assert site.get("/favicon.ico").status_code < 500

    def test_http_redirects_to_https(self, site):
        if not site.base.startswith("https://"):
            pytest.skip("target is not HTTPS (local run)")
        r = site.get(site.base.replace("https://", "http://", 1), allow_redirects=False)
        assert r.status_code in (301, 302, 307, 308)
        assert r.headers["location"].startswith("https://")


# --------------------------------------------------------------------------- 2. news search (scraping)
class TestSearchEndpoint:
    def test_missing_stock_is_rejected(self, site):
        r = site.post("/search", data={})
        assert r.status_code == 400
        assert "error" in as_json(r)

    def test_empty_stock_is_rejected(self, site):
        r = site.post("/search", data={"stock": ""})
        assert r.status_code == 400
        assert "error" in as_json(r)

    def test_get_not_allowed_on_search(self, site):
        assert site.get("/search").status_code == 405

    @pytest.mark.parametrize("stock", LARGE_CAPS + INDICES)
    def test_news_is_fetched_for_stock(self, site, stock):
        r = post_search(site, stock)
        assert r.status_code == 200, r.text[:300]
        data = as_json(r)
        assert isinstance(data.get("news"), list), "'news' must be a list"
        assert len(data["news"]) > 0, (
            f"No news returned for {stock} - scraper may be blocked or broken"
        )

    def test_news_items_are_well_formed(self, site):
        news = as_json(post_search(site, "RELIANCE"))["news"]
        assert news, "no news to validate"
        for item in news[:15]:
            assert_valid_news_item(item)

    def test_force_refresh_returns_fresh_news(self, site):
        r = post_search(site, "TCS", refresh=True)
        assert r.status_code == 200
        assert isinstance(as_json(r)["news"], list)

    def test_repeat_search_is_consistent(self, site):
        first = as_json(post_search(site, "INFY"))["news"]
        second = as_json(post_search(site, "INFY"))["news"]
        assert isinstance(first, list) and isinstance(second, list)
        assert len(second) > 0

    def test_response_contains_history(self, site, qa_cleanup):
        data = as_json(post_search(site, QA_STOCK))
        assert isinstance(data.get("history"), list)


# --------------------------------------------------------------------------- 3. /api/news
class TestNewsEndpoint:
    def test_requires_a_parameter(self, site):
        assert site.get("/api/news").status_code == 400

    @pytest.mark.parametrize("stock", ["TCS", "RELIANCE"])
    def test_stock_news(self, site, stock):
        r = site.get("/api/news", params={"stock": stock})
        assert r.status_code == 200
        assert isinstance(as_json(r)["news"], list)

    @pytest.mark.parametrize("index", ["NIFTY50", "DOWJONES"])
    def test_market_index_news(self, site, index):
        r = site.get("/api/news", params={"index": index})
        assert r.status_code == 200
        news = as_json(r)["news"]
        assert isinstance(news, list) and len(news) > 0, f"no news for {index}"

    def test_invalid_index_rejected(self, site):
        assert site.get("/api/news", params={"index": "NOTANINDEX"}).status_code == 400


# --------------------------------------------------------------------------- 4. history
class TestHistory:
    def test_history_is_a_list(self, site):
        r = site.get("/api/history")
        assert r.status_code == 200
        assert isinstance(as_json(r), list)

    def test_search_is_recorded_with_correct_fields(self, site, qa_cleanup):
        post_search(site, QA_STOCK)
        entries = [h for h in as_json(site.get("/api/history")) if h.get("stock") == QA_STOCK]
        assert entries, "search was not recorded in history"
        entry = entries[-1]
        assert {"stock", "timestamp", "count"} <= set(entry)
        assert isinstance(entry["count"], int)
        datetime.fromisoformat(entry["timestamp"])  # must be valid ISO-8601

    def test_delete_single_history_item(self, site):
        post_search(site, QA_STOCK)
        r = site.delete(f"/api/history/{QA_STOCK}")
        assert r.status_code == 200
        remaining = [h for h in as_json(site.get("/api/history")) if h.get("stock") == QA_STOCK]
        assert remaining == []

    def test_delete_missing_item_is_harmless(self, site):
        assert site.delete("/api/history/NEVERSEARCHED999").status_code == 200

    def test_history_is_capped_at_50(self, site):
        assert len(as_json(site.get("/api/history"))) <= 50

    def test_clear_all_history(self, site, destructive):
        if not destructive:
            pytest.skip("wipes shared history - run with --destructive to enable")
        assert site.delete("/api/history").status_code == 200
        assert as_json(site.get("/api/history")) == []


# --------------------------------------------------------------------------- 5. cache
class TestCache:
    def test_cache_status_after_search(self, site, qa_cleanup):
        post_search(site, "RELIANCE")
        r = site.get("/api/cache-status/RELIANCE")
        assert r.status_code == 200, (
            "cache-status endpoint errored after a search - check that the cache "
            "value format matches what the endpoint expects"
        )
        assert as_json(r)["hasCache"] is True

    def test_cache_status_for_unknown_stock(self, site):
        r = site.get("/api/cache-status/NEVERSEARCHED999")
        assert r.status_code == 200
        assert as_json(r)["hasCache"] is False


# --------------------------------------------------------------------------- 6. hostile / odd input
ODD_INPUTS = {
    "xss": "<script>alert(1)</script>",
    "sql_injection": "' OR 1=1 --",
    "path_traversal": "../../etc/passwd",
    "unicode_hindi": "रिलायंस",
    "emoji": "📈🚀",
    "very_long": "A" * 3000,
    "spaces_and_symbols": "M&M / Tata-Motors (Ltd.)",
}


class TestRobustness:
    @pytest.mark.parametrize("value", ODD_INPUTS.values(), ids=ODD_INPUTS.keys())
    def test_weird_input_never_causes_server_error(self, site, value):
        r = post_search(site, value)
        if len(value) < 100:  # tidy up the history entry we just created
            site.delete(f"/api/history/{value.replace('/', '%2F')}")
        assert r.status_code in (200, 400, 413, 414), (
            f"Server error {r.status_code} for input {value[:40]!r}: {r.text[:200]}"
        )
        if r.status_code == 200:
            assert isinstance(as_json(r)["news"], list)


# --------------------------------------------------------------------------- 7. security hygiene
class TestSecurity:
    @pytest.mark.parametrize(
        "path",
        ["/.env", "/search_history.json", "/app.py", "/news_fetcher.py",
         "/requirements.txt", "/.git/config", "/Dockerfile"],
    )
    def test_source_and_secret_files_not_exposed(self, site, path):
        r = site.get(path)
        assert r.status_code in (403, 404, 405), f"{path} is publicly readable!"

    def test_security_headers_report(self, site):
        """Informational: warns (does not fail) about missing hardening headers."""
        h = {k.lower(): v for k, v in site.get("/").headers.items()}
        wanted = ["x-content-type-options", "x-frame-options",
                  "strict-transport-security", "content-security-policy"]
        missing = [x for x in wanted if x not in h]
        if missing:
            warnings.warn(f"Missing security headers (recommended): {', '.join(missing)}")



# --------------------------------------------------------------------------- 8. performance / light load
@pytest.mark.slow
class TestPerformance:
    def test_homepage_median_load_time(self, site):
        times = [site.get("/").elapsed.total_seconds() for _ in range(5)]
        median = statistics.median(times)
        assert median < 8, f"Homepage too slow: median {median:.2f}s ({times})"

    def test_concurrent_visitors(self, site):
        """10 simultaneous visitors must all get a 200."""
        with cf.ThreadPoolExecutor(max_workers=5) as pool:
            codes = list(pool.map(lambda _: site.get("/").status_code, range(10)))
        assert codes == [200] * 10, f"Status codes under load: {codes}"

    def test_concurrent_searches(self, site):
        stocks = ["TCS", "INFY", "RELIANCE", "HDFCBANK"]
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(lambda s: post_search(site, s).status_code, stocks))
        assert codes == [200] * 4, f"Status codes under load: {codes}"

    def test_search_response_time(self, site):
        r = post_search(site, "WIPRO", refresh=True)
        assert r.status_code == 200
        assert r.elapsed.total_seconds() < 45, f"Search took {r.elapsed.total_seconds():.1f}s"
