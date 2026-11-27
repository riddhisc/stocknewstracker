# End-to-end testing - Indian Stock News Tracker

Automated test-suite for the live site. **One command checks the whole application.**

```
pip install -r requirements-test.txt
python run_tests.py
```
(or double-click `run_tests.bat` on Windows)

| Flag | What it does |
|------|--------------|
| `--suite api / ui / e2e / unit` | run one layer (`e2e` = api + ui, `unit` = the project's own `tests/` folder) |
| `--headed --slowmo 400` | watch the browser click through the site |
| `--channel chrome` | use the installed Google Chrome (auto-detected if Playwright's browser can't start) |
| `--browser all` | Chromium + Firefox + WebKit |
| `--quick` | skip slow load tests |
| `--url http://127.0.0.1:5000` | test a local copy instead of the live site |
| `--destructive` | also test "Clear History" (wipes the shared history!) |

Output: a colour console summary + `reports/report.html` (screenshots/traces of failures).

## What is tested

| Layer | Tools | Covers |
|-------|-------|--------|
| **API** (`e2e_tests/test_01_api.py`) | pytest, requests | every endpoint, news scraping returns data, history CRUD, cache, 400/404/405 handling, XSS/SQL/unicode/long input, exposed-file checks, security headers, HTTPS redirect, concurrent users, response time. Includes a circuit-breaker so an outage fails fast. |
| **UI / E2E** (`e2e_tests/test_02_ui.py`) | pytest, Playwright | page load, headlines, search button + Enter, history panel, Status, Results page + filters, XSS in the UI, back/forward, 4 screen sizes, iPhone emulation, accessibility basics, no JS/server errors |
| **Unit** (`tests/`) | pytest, fixtures, mocks | adapters, fallback, config, robots, summaries, health (offline, deterministic) |
| **CI** (`.github/workflows/`) | GitHub Actions | tests on every push + daily scheduled check |

## Resume bullets (use what you can defend)

- Built an automated test-suite (~70 tests) for a Flask web-scraping app using **pytest** and **Playwright**: API, end-to-end browser and unit layers.
- Wrote cross-browser E2E tests (Chromium/Firefox/WebKit, mobile emulation) with automatic screenshots/traces on failure.
- Unit-tested scrapers with **fixtures and mocks** so tests are deterministic and offline.
- Added negative, security (XSS/SQL-injection input, exposed-file checks) and concurrency tests.
- Set up **CI with GitHub Actions**: runs on every push plus a daily scheduled run that doubles as an uptime/scraper monitor.
- Tests found real issues (no HTTP->HTTPS redirect, source-file exposure checks, history recording) that were then fixed.
