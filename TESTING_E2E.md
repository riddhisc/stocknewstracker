# End-to-end testing – Indian Stock News Tracker

Automated, three-layer test-suite. **One command checks the whole application.**

```
pip install -r requirements-test.txt
python run_tests.py
```
(or double-click `run_tests.bat` on Windows)

| Flag | What it does |
|------|--------------|
| `--suite api / ui / unit` | run one layer only |
| `--headed --slowmo 400` | watch the browser click through the site |
| `--browser all` | Chromium + Firefox + WebKit |
| `--quick` | skip slow load tests |
| `--url http://127.0.0.1:5000` | test a local copy instead of the live site |
| `--destructive` | also test "Clear History" (wipes the shared history!) |

Output: a colour console summary + `reports/report.html` (with screenshots/traces of failures).

## What is tested

| Layer | Tools | Covers |
|-------|-------|--------|
| **API** (`e2e_tests/test_01_api.py`) | pytest, requests | all endpoints, news scraping returns data, history CRUD, cache, 400/404/405 handling, XSS/SQL/unicode/long input, exposed-secret-file checks, security headers, HTTPS redirect, concurrent users, response time |
| **UI / E2E** (`e2e_tests/test_02_ui.py`) | pytest, Playwright | page load, headlines section, search button + Enter key, history panel, Status button, Results page + all filter buttons, XSS in the UI, back/forward, 4 screen sizes, iPhone emulation, accessibility basics, no JS/server errors |
| **Unit** (`e2e_tests/test_03_unit_local.py`) | pytest, Flask test client, mocking | cache hit / force-refresh logic, history cap (50), error handling, input normalisation – offline and deterministic |
| **CI** (`.github/workflows/e2e.yml`) | GitHub Actions | runs on every push + daily scheduled health-check |

## Resume bullets (pick what you are comfortable defending)

- Built an automated test-suite (100+ tests) for a Flask web-scraping app using **pytest** and **Playwright**, covering API, end-to-end browser and unit layers.
- Wrote cross-browser E2E tests (Chromium/Firefox/WebKit, mobile emulation) that verify search, history, filters and live news fetching, with automatic screenshots/traces on failure.
- Isolated scraper logic with **mocks/fixtures** to unit-test caching, history limits and error handling deterministically.
- Added negative, security (XSS/SQL-injection input, exposed-file checks) and concurrency tests.
- Set up **CI with GitHub Actions** running the suite on every push plus a daily scheduled run that doubles as an uptime/scraper monitor; publishes HTML reports as artifacts.

## Interview talking points
- **Test pyramid**: many fast unit/API tests, fewer slow browser tests.
- **Why mock the scraper in unit tests but not in the live tests**: determinism vs. proving the real pipeline works.
- **Locators by role/text, not CSS ids**: tests survive markup changes.
- **Flaky-test handling**: retries on 502/503/504, generous timeouts for a free-tier host, traces for debugging.
