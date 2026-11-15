# Runbook

## Deploy

### PythonAnywhere

In a Bash console:

```text
cd ~/stocknewstracker
git pull
```

Open the Web tab and click Reload. On the free plan, set Run until to 15 February 2027 (three months from 15 November 2026) and renew it before that date.

The virtualenv must already have `pip install -r requirements.txt`. Set env vars in the WSGI file or the Web tab, not in a committed `.env`.

Use a home-directory path for history, for example:

```text
HISTORY_DB=/home/YOUR_USER/stocknewstracker/search_history.db
CONFIG_PATH=/home/YOUR_USER/stocknewstracker/config.yaml
ENABLE_SUMMARY=false
FLASK_DEBUG=false
LOG_LEVEL=INFO
```

Set `NEWS_API_KEY` only if `newsapi` is enabled in the YAML. Set `ANTHROPIC_API_KEY` only if `ENABLE_SUMMARY=true`.

### Docker

```text
docker build -t stocknewstracker .
docker run -p 8080:8080 -v stock-history:/data -e ENABLE_SUMMARY=false stocknewstracker
```

The process user is uid 10001. The image health check calls `GET /health`.

### Render

Connect the repo. `render.yaml` starts gunicorn on `$PORT`. Put secrets in the Render dashboard.

## Read /health

`GET /health` returns JSON:

- `status` is `ok` when every enabled source is ok, `degraded` when at least one is degraded or down but another is still ok, and `down` when every enabled source is down.
- Each source has `name`, `status` (`ok`, `degraded`, `down`), `last_success`, `last_error`, `latency_ms`, and `enabled`.
- HTTP 200 for `ok` and `degraded`. HTTP 503 only when every enabled source is down.
- The desk Status button reads the same payload.

A source that has never been called stays `ok` with a null `last_success`. That means the process is up, not that the site was fetched.

## Incident: Google News blocked by robots.txt

Google News publishes `Disallow: /` for this app's User-Agent and does not allow `/rss`. The source returns nothing. The desk showed an empty headline list, and Status said `blocked by robots.txt` with that source `down`. `/health` lists `google_news_rss` (and the HTML reader) as `down`, `last_error` `blocked by robots.txt`, while the overall status stays `degraded` if another source is still ok. HTTP stays 200 unless every enabled source is down.

Do not ignore `robots.txt`. Search uses Bing News RSS, which allows this client. If Bing later blocks the feed or changes the XML, `/health` will show `bing_news_rss` as `down` or the parse count will be 0. Leave the disallow in place, point the RSS adapter at another feed that permits this User-Agent, and keep serving the last cached headlines with `stale: true` until that feed answers.

## Source down, or the HTML changed

1. Open `/health` and read `last_error` for that source.
2. `blocked by robots.txt` means do not work around the block. Leave the source enabled so the panel stays honest, or set `enabled: false` in `config.yaml` and reload.
3. `timeout` or `HTTP 403` / `HTTP 404`: the adapter already retried. Later searches still return other sources. If an older cache exists, the search response has `stale: true`.
4. A selector that used to match and now returns `count: 0` in the logs means the page HTML changed. Update `parse()` in that adapter and add a fixture under `tests/fixtures/`. Do not point tests at the live site.
5. Reload the process after the YAML or code change. On PythonAnywhere that is Web tab Reload. In Docker, rebuild and replace the container.

## Rotate API keys

Do this at the provider first, then update the host. Never put the new value in git.

1. **NewsAPI.** The name `NEWS_API_KEY` was committed in `.env` in the initial commit, with a real value. Revoke that key in the NewsAPI dashboard and create a new one. The running app does not need a key unless the `newsapi` source is enabled.
2. **Anthropic.** If `ANTHROPIC_API_KEY` was ever pasted into a host or a chat, rotate it in the Anthropic console. The app only reads it when `ENABLE_SUMMARY=true`.
3. **SMTP and Telegram.** `SMTP_PASS` and `TELEGRAM_BOT_TOKEN` live in GitHub Actions secrets for `.github/workflows/daily.yml`. Rotate them in the provider, then update the repository secrets. The Flask app does not read them.

The old NewsAPI value is still in git history after it was removed from the tree. Purge it locally, then force-push only if you accept a history rewrite. These commands are for the repo owner to run. They were not run as part of the portfolio work.

```text
pip install git-filter-repo
git filter-repo --path .env --invert-paths
```

BFG alternative, from a fresh clone:

```text
java -jar bfg.jar --delete-files .env
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

After either tool, `git push --force` is required for the remote to drop the old commit. Agree that with anyone else who has cloned the repo. Rotating the key matters even if history is purged.

## Onboard a client

1. Copy `config.example.yaml` to a new file, for example `config.client_c.yaml`. Do not edit `data/watchlist.json` for this. That file is the results calendar.
2. Replace `watchlist` with the client's names, tickers, and aliases.
3. Set `indices` to the tabs they should see.
4. Set `sources`: `enabled`, `priority`, and `timeout`. Turn off scrapers they do not need. Leave `newsapi` disabled unless they have a key.
5. Check the file:

```text
python -c "from config_loader import load_config; load_config('config.client_c.yaml')"
```

A bad field is named in the error.
6. On the host, set `CONFIG_PATH` to that file and reload. `GET /api/watchlist/news` should list the new tickers. The results script keeps using `data/watchlist.json` until you edit that file on purpose.
