import os
import tempfile
import unittest
from unittest.mock import patch

_history = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
_history.close()
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db.close()
os.environ["HISTORY_FILE"] = _history.name
os.environ["HISTORY_DB"] = _db.name

import app


class SmokeTests(unittest.TestCase):
    def setUp(self):
        app.news_cache.clear()
        self.client = app.app.test_client()

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Indian Stock News Tracker", response.data)

    def test_search_requires_stock(self):
        response = self.client.post("/search", data={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["news"], [])

    def test_search_caches_articles_and_cache_status(self):
        sample = [{
            "title": "TCS rises",
            "description": "sample",
            "url": "https://example.com/tcs",
            "source": "Test",
            "published_at": "2026-11-14T00:00:00Z",
            "type": "info",
        }]
        with patch.object(app.news_fetcher, "fetch_news", return_value=sample):
            response = self.client.post("/search", data={"stock": "TCS"})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["news"][0]["title"], "TCS rises")

        status = self.client.get("/api/cache-status/TCS")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.get_json()["hasCache"])

        with patch.object(app.news_fetcher, "fetch_news") as fetch_news:
            cached = self.client.post("/search", data={"stock": "TCS"})
            fetch_news.assert_not_called()
        self.assertEqual(cached.get_json()["news"][0]["title"], "TCS rises")

    def test_history_round_trip(self):
        empty = self.client.get("/api/history")
        self.assertEqual(empty.status_code, 200)
        self.assertIsInstance(empty.get_json(), list)

        cleared = self.client.delete("/api/history")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(self.client.get("/api/history").get_json(), [])


if __name__ == "__main__":
    unittest.main()
