import app


def test_health_returns_source_status():
    client = app.app.test_client()
    response = client.get("/health")
    body = response.get_json()
    assert response.status_code in {200, 503}
    assert body["status"] in {"ok", "degraded", "down"}
    names = {row["name"] for row in body["sources"]}
    assert "google_news_rss" in names
    sample = body["sources"][0]
    assert "last_success" in sample
    assert "last_error" in sample
    assert sample["status"] in {"ok", "degraded", "down"}


def test_health_marks_degraded_when_one_enabled_source_is_down():
    client = app.app.test_client()
    source = next(item for item in app.news_fetcher.sources if item.name == "yahoo_finance")
    previous = (source.status, source.last_error, source.last_success_at)
    source.mark_failure("timeout", 10)
    try:
        response = client.get("/health")
        body = response.get_json()
        assert response.status_code == 200
        assert body["status"] == "degraded"
        row = next(item for item in body["sources"] if item["name"] == "yahoo_finance")
        assert row["status"] == "down"
        assert row["last_error"] == "timeout"
    finally:
        source.status, source.last_error, source.last_success_at = previous
