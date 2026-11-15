# Decisions

## 1. Source adapters, RSS first

Headline sites fail independently. Each one is a `NewsSource` with `fetch(query)` and `health()`. The orchestrator catches a timeout or `SourceError`, logs the source name and latency, and keeps articles from the others. Query search uses Bing News RSS, which this agent is allowed to fetch. Google News RSS is still listed, and a real `Disallow` keeps it from being requested. The older HTML readers run only when RSS returns nothing, which keeps request volume down.

An earlier cache entry is served with `stale: true` when the live calls fail. The response shape stays `{"data", "fetched_at"}` inside the cache.

## 2. SQLite for search history

`search_history.json` was local clutter and a poor fit for two requests at once. The standard library `sqlite3` stores the last 50 searches. `HISTORY_DB` chooses the file, and Docker mounts it at `/data`. If `search_history.json` is present, it is imported once and then ignored. SQLAlchemy was not added.

Summary text uses a second table in the same file, keyed by article URL.

## 3. YAML for a customer, JSON for results

A new desk should be a file change. `config.yaml` holds tickers, aliases, source priority, timeouts, cache TTL, and index tabs. Startup validation names the bad field.

`data/watchlist.json` stays the input for `scripts/refresh_results.py` and the reminder script. Mixing the two lists would let a news-only alias change a result date.

## 4. robots.txt and one User-Agent

The HTTP client sends `StockNewsTracker/1.0`, waits briefly between calls to the same host, and skips a URL that `robots.txt` disallows. That blocks Google News and MarketWatch for this agent. Working around the file would make the portfolio a scraper that ignores the site's rules, so those sources report `down` and the rest of the desk still answers.

Retries stop at three, with exponential backoff. A 404 or 403 is not retried.

## 5. Summaries behind a flag

`ENABLE_SUMMARY` defaults to false, so search never depends on Anthropic. The call uses the existing `requests` library, an eight-second timeout, and `ANTHROPIC_API_KEY` only in the request header. The key is not logged. A missing key, HTTP error, or timeout returns the same articles with no summary. Successful text is cached by URL so the same story is not sent again.
