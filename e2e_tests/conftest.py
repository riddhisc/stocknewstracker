"""
Shared fixtures for the Indian Stock News Tracker test-suite.

* `site`        -> small HTTP client with retries/timeouts (used by API tests)
* `destructive` -> True only when run with --destructive (tests that wipe the
                   shared search history on the live site are opt-in)

`--base-url` comes from the pytest-base-url plugin (installed with
pytest-playwright); the default is set in pytest.ini.
"""
import time

import pytest
import requests

DEFAULT_URL = "https://ridz111.pythonanywhere.com"


def pytest_addoption(parser):
    parser.addoption(
        "--destructive",
        action="store_true",
        default=False,
        help="Also run tests that clear ALL search history on the target site.",
    )


def pytest_configure(config):
    if not getattr(config.option, "base_url", None):
        config.option.base_url = DEFAULT_URL


class SiteClient:
    """requests.Session wrapper: default timeout + retry on flaky gateway errors
    (free PythonAnywhere accounts can be slow to wake up)."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "StockNewsTracker-TestSuite/1.0"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 60)
        url = path if path.startswith("http") else self.base + path
        last_exc = None
        for attempt in range(3):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code in (502, 503, 504) and attempt < 2:
                    time.sleep(3)
                    continue
                return resp
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                time.sleep(3)
        raise last_exc

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


@pytest.fixture(scope="session")
def site(base_url):
    client = SiteClient(base_url)
    client.get("/")  # warm-up: wake the app before the real tests start
    return client


@pytest.fixture(scope="session")
def destructive(pytestconfig):
    return pytestconfig.getoption("--destructive")
