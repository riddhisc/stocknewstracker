import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import schedule
from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

import results_board
from config_loader import load_config
from history_store import HistoryStore
from logutil import configure_logging, log_event
from news_fetcher import NewsFetcher
from summaries import apply_summaries

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

configure_logging()

app = Flask(__name__, static_folder='static')
CORS(app)
news_fetcher = NewsFetcher()

# One cache shape for every stock: {"data": [articles], "fetched_at": unix time}.
# Readers must use cache_get(); the value is not a tuple.
news_cache = {}
watchlist_snapshot = None
watchlist_snapshot_at = 0.0
watchlist_refresh_lock = threading.Lock()
# config.yaml is the news desk. data/watchlist.json is the results calendar
# read by scripts/refresh_results.py. They are not the same list.
APP_CONFIG = load_config()
NEWS_CACHE_TTL_SECONDS = APP_CONFIG.cache_ttl_seconds
news_fetcher.set_cache_ttl(APP_CONFIG.cache_ttl_seconds)
news_fetcher.apply_source_settings(APP_CONFIG.source_settings)
news_fetcher.extra_aliases = dict(APP_CONFIG.alias_map)

def cache_put(stock, articles):
    news_cache[stock] = {
        "data": articles if isinstance(articles, list) else [],
        "fetched_at": time.time(),
    }

def _cache_entry(stock):
    """Return (articles, fresh) for a {"data", "fetched_at"} entry.

    Expired entries stay in memory so a failed fetch can still serve them
    with stale=true. Fresh reads go through cache_get().
    """
    entry = news_cache.get(stock)
    if not isinstance(entry, dict):
        return None, False
    articles = entry.get("data")
    fetched_at = entry.get("fetched_at")
    if not isinstance(articles, list) or not isinstance(fetched_at, (int, float)):
        news_cache.pop(stock, None)
        return None, False
    fresh = time.time() - fetched_at < NEWS_CACHE_TTL_SECONDS
    return articles, fresh

def real_articles(articles):
    """Drop the old 'no news' placeholder so it is not counted as a story."""
    if not isinstance(articles, list):
        return []
    return [
        item for item in articles
        if isinstance(item, dict) and item.get("type") != "info" and item.get("title")
    ]

def cache_get(stock):
    """Return cached articles, or None when missing or older than the TTL."""
    articles, fresh = _cache_entry(stock)
    kept = real_articles(articles)
    if not fresh or not kept:
        return None
    return kept

def cache_peek(stock):
    """Return the last real articles even when the TTL has passed."""
    articles, _fresh = _cache_entry(stock)
    return real_articles(articles)

# SQLite replaces search_history.json. HISTORY_FILE is only the one-time import.
HISTORY_DB = os.environ.get("HISTORY_DB", "search_history.db")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "search_history.json")
history_store = HistoryStore(HISTORY_DB, HISTORY_FILE)
# Search history is now browser-local. Clear the legacy shared search rows once
# on startup so an older server database cannot expose another user's searches.
history_store.clear()

def update_news_cache():
    for stock in list(news_cache.keys()):
        news = news_fetcher.fetch_news(stock)
        if getattr(news, "stale", False):
            continue
        cache_put(stock, list(news) if isinstance(news, list) else [])

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Schedule news updates every 15 minutes
schedule.every(15).minutes.do(update_news_cache)

# Start the scheduler in a separate thread
scheduler_thread = threading.Thread(target=run_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

def load_history():
    return history_store.load()

def attach_summaries(news, query):
    """Optional. Missing key or API failure must not change the headline list."""
    if not isinstance(news, list):
        return news
    try:
        return apply_summaries(news, query, history_store)
    except Exception as exc:
        log_event(logging.WARNING, "summary", outcome="error", error=exc.__class__.__name__)
        return news

SYMBOLS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'symbols.json')

def load_symbols():
    try:
        with open(SYMBOLS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log_event(logging.WARNING, "symbols_read", outcome="error", error=exc.__class__.__name__)
        return []
    symbols = []
    seen = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get('symbol', '')).strip().upper()
        name = str(item.get('name', '')).strip()
        if not symbol or not name or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append({'symbol': symbol, 'name': name})
    return symbols

SYMBOLS = load_symbols()
_symbols_mtime = None

def get_symbols():
    """Reload the local list when symbols.json changes, without a manual restart."""
    global SYMBOLS, _symbols_mtime
    try:
        mtime = os.path.getmtime(SYMBOLS_PATH)
    except OSError:
        return SYMBOLS
    if mtime != _symbols_mtime:
        SYMBOLS = load_symbols()
        _symbols_mtime = mtime
    return SYMBOLS

def match_symbols(query, limit=12):
    q = (query or '').strip().lower()
    if not q:
        return []
    buckets = {key: [] for key in ('symbol_prefix', 'name_prefix', 'symbol_contains', 'name_contains')}
    for item in get_symbols():
        symbol = item['symbol'].lower()
        name = item['name'].lower()
        if symbol.startswith(q):
            buckets['symbol_prefix'].append(item)
        elif name.startswith(q):
            buckets['name_prefix'].append(item)
        elif q in symbol:
            buckets['symbol_contains'].append(item)
        elif q in name:
            buckets['name_contains'].append(item)
    results = []
    seen = set()
    for key in ('symbol_prefix', 'name_prefix', 'symbol_contains', 'name_contains'):
        for item in sorted(buckets[key], key=lambda row: (row['symbol'], row['name'])):
            if item['symbol'] in seen:
                continue
            seen.add(item['symbol'])
            results.append({'symbol': item['symbol'], 'name': item['name']})
            if len(results) >= limit:
                return results
    return results

def _quiet_source(source):
    text = str(source or "").strip()
    if not text or text.lower() in {"bing news", "bing", "unknown source"}:
        return "Bing"
    return text

def _short_ago(value):
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - moment.astimezone(timezone.utc)).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    return moment.strftime("%d %b")

def _circulating_cards():
    sections, stale = news_fetcher.markets_snapshot()
    cards = []
    for section in sections:
        item = (section.get("news") or [None])[0] or {}
        cards.append({
            "id": section["id"],
            "title": section["title"],
            "headline": item.get("title") or "",
            "url": item.get("url") or "",
            "source": _quiet_source(item.get("source")) if item.get("title") else "",
            "when": _short_ago(item.get("published_at")),
        })
    return cards, stale

@app.route('/')
def home():
    circulating, circulating_stale = _circulating_cards()
    return render_template(
        'index.html',
        indices=APP_CONFIG.indices,
        circulating=circulating,
        circulating_stale=circulating_stale,
    )

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/search', methods=['POST'])
def search():
    try:
        stock = request.form.get('stock')
        force_refresh = request.form.get('force_refresh') == 'true'
        
        if not stock:
            return jsonify({'error': 'Stock symbol is required', 'news': []}), 400
        
        served_cached = False
        stale = False
        news = None if force_refresh else cache_get(stock)
        if news is not None:
            served_cached = True
            log_event(logging.INFO, "search", symbol=stock, outcome="cache")
        else:
            log_event(
                logging.INFO,
                "search",
                symbol=stock,
                outcome="refresh" if force_refresh else "fetch",
            )
            news = news_fetcher.fetch_news(stock, force=force_refresh)
            stale = bool(getattr(news, "stale", False))
            if not isinstance(news, list):
                log_event(
                    logging.WARNING,
                    "search",
                    symbol=stock,
                    outcome="coerce",
                    error=type(news).__name__,
                )
                try:
                    news = list(news) if news else []
                except TypeError:
                    news = []
            news = real_articles(news)
            if stale:
                previous = cache_peek(stock)
                if previous and not news:
                    news = previous
            elif news:
                cache_put(stock, news)

        if served_cached:
            news = real_articles(news)

        news = attach_summaries(news, stock)
        return jsonify({
            'news': news,
            'history': [],
            'cached': served_cached,
            'stale': stale,
        })
    except Exception as e:
        log_event(logging.ERROR, "search", outcome="error", error=e.__class__.__name__)
        previous = []
        try:
            previous = cache_peek(stock) or []
        except Exception:
            previous = []
        previous = real_articles(previous)
        if previous:
            return jsonify({
                'news': previous,
                'history': [],
                'cached': False,
                'stale': True,
            })
        return jsonify({
            'error': f"Server error: {e.__class__.__name__}",
            'news': [],
            'history': [],
            'stale': False,
        }), 500

@app.route('/api/suggest')
def suggest_symbols():
    return jsonify(match_symbols(request.args.get('q', '')))

@app.route('/health')
def health():
    """Process health plus one row per source. Disabled sources stay in the list."""
    reports = []
    enabled_statuses = []
    for source in news_fetcher.sources:
        report = source.health()
        reports.append(report)
        if report.get("enabled"):
            enabled_statuses.append(report.get("status"))
    if not enabled_statuses or set(enabled_statuses) <= {"ok"}:
        overall = "ok"
    elif set(enabled_statuses) == {"down"}:
        overall = "down"
    else:
        overall = "degraded"
    # 200 while the process can still serve cached headlines. 503 only when
    # every enabled source is down.
    code = 503 if overall == "down" else 200
    return jsonify({"status": overall, "sources": reports}), code

@app.route('/api/watchlist/news')
def watchlist_news():
    """Latest headlines for every name in config.yaml.

    Read-only. data/watchlist.json is a different list: it drives
    scripts/refresh_results.py and is not read here.
    """
    global watchlist_snapshot, watchlist_snapshot_at
    now = time.time()
    if watchlist_snapshot is None:
        watchlist_snapshot = _build_watchlist_snapshot()
        watchlist_snapshot_at = now
    elif now - watchlist_snapshot_at >= NEWS_CACHE_TTL_SECONDS:
        if watchlist_refresh_lock.acquire(blocking=False):
            threading.Thread(target=_refresh_watchlist_snapshot, daemon=True).start()
    return jsonify({"items": watchlist_snapshot, "cached": True, "stale": now - watchlist_snapshot_at >= NEWS_CACHE_TTL_SECONDS})


def _build_watchlist_snapshot():
    items = []
    for row in APP_CONFIG.watchlist:
        key = row["name"]
        news = cache_get(key)
        stale = False
        if news is None:
            news = cache_peek(key)
            stale = bool(news)
        if news is None:
            fetched = news_fetcher.fetch_news(key)
            stale = bool(getattr(fetched, "stale", False))
            news = real_articles(list(fetched))
            if news and not stale:
                cache_put(key, news)
        items.append({
            "name": row["name"],
            "ticker": row["ticker"],
            "aliases": row["aliases"],
            "news": real_articles(list(news or []))[:8],
            "stale": stale,
        })
    return items


def _refresh_watchlist_snapshot():
    global watchlist_snapshot, watchlist_snapshot_at
    try:
        watchlist_snapshot = _build_watchlist_snapshot()
        watchlist_snapshot_at = time.time()
    finally:
        watchlist_refresh_lock.release()

@app.route('/api/history', methods=['GET'])
def get_history():
    # Deliberately empty: search history belongs to the current browser only.
    return jsonify([])

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    return jsonify({"message": "History cleared"})

@app.route('/api/history/<stock>', methods=['DELETE'])
def delete_history_item(stock):
    return jsonify({"message": f"History for {stock} deleted"})

@app.route('/api/cache-status/<stock>', methods=['GET'])
def check_cache_status(stock):
    """Check if a stock has cached news data available within the TTL.

    Entries are {"data", "fetched_at"}. This route used to unpack the stored
    value as a tuple, which crashed when the cache held a list of articles.
    """
    return jsonify({
        "stock": stock,
        "hasCache": cache_get(stock) is not None
    })

@app.route('/api/markets-now', methods=['GET'])
def markets_now():
    """Five topics from data/markets_now.json. Bing runs only when that file is stale or missing."""
    try:
        sections, stale, cached = news_fetcher.fetch_trending()
    except Exception as exc:
        log_event(logging.WARNING, "markets_now", outcome="error", error=exc.__class__.__name__)
        sections, stale, cached = [], True, False
    return jsonify({"sections": sections, "stale": stale, "cached": cached})

def _iso_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None

def _when_label(date_text, status=None):
    day = _iso_date(date_text)
    if day is None:
        return "Not announced"
    delta = (day - datetime.now().date()).days
    if delta <= 0:
        days_since = abs(delta)
        if days_since > 5:
            return None
        return "Result announced today" if days_since == 0 else f"Result announced {days_since} day{'s' if days_since != 1 else ''} ago"
    if delta == 1:
        label = "in 1 day"
    else:
        label = f"in {delta} days"
    return f"Expected {label}" if status == "estimated" else label

def _load_results():
    """Read data/results.json. The request never calls a market-data library."""
    root = Path(app.root_path)
    results_path = root / "data" / "results.json"
    watch_path = root / "data" / "watchlist.json"
    if not results_path.is_file():
        return {"missing": True, "items": [], "updated_at": None, "stale": False}
    try:
        payload = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log_event(logging.WARNING, "results", outcome="unreadable")
        return {"missing": True, "items": [], "updated_at": None, "stale": False}
    names = {}
    if watch_path.is_file():
        try:
            rows = json.loads(watch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rows = []
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("symbol"):
                    names[str(row["symbol"]).upper()] = row.get("name") or row["symbol"]
    if not isinstance(payload, dict):
        return {"missing": True, "items": [], "updated_at": None, "stale": False}
    # Results are refreshed by the daily workflow. Treat anything older than
    # one day as stale so the desk never presents multi-day-old data as fresh.
    cutoff = datetime.now().astimezone() - timedelta(days=1)
    items = []
    newest = None
    section_stale = False
    for symbol, block in payload.items():
        if not isinstance(block, dict):
            continue
        symbol = str(symbol).upper()
        nxt = block.get("next_result") if isinstance(block.get("next_result"), dict) else {}
        quarters = block.get("quarters") if isinstance(block.get("quarters"), list) else []
        latest = quarters[0] if quarters and isinstance(quarters[0], dict) else {}
        links = block.get("links") if isinstance(block.get("links"), dict) else {}
        source_url = (
            nxt.get("source_url")
            or block.get("source_url")
            or links.get("screener")
            or f"https://www.screener.in/company/{symbol}/consolidated/"
        )
        date_status = nxt.get("status")
        if not date_status and nxt.get("date"):
            date_status = "estimated" if "finance.yahoo.com" in source_url else "confirmed"
        updated = block.get("updated_at")
        record_stale = bool(block.get("stale"))
        parsed_updated = None
        if updated:
            try:
                parsed_updated = datetime.fromisoformat(str(updated))
            except ValueError:
                parsed_updated = None
        if parsed_updated is not None:
            aware = parsed_updated if parsed_updated.tzinfo else parsed_updated.astimezone()
            if aware < cutoff:
                record_stale = True
            if newest is None or aware > newest:
                newest = aware
        if record_stale:
            section_stale = True
        when = _when_label(nxt.get("date"), date_status)
        if when is None:
            continue
        items.append({
            "symbol": symbol,
            "name": names.get(symbol, symbol),
            "next_date": nxt.get("date"),
            "next_period": nxt.get("period"),
            "date_status": date_status,
            "when": when,
            "latest_period": latest.get("period"),
            "revenue": latest.get("revenue"),
            "net_profit": latest.get("net_profit"),
            "eps": latest.get("eps"),
            "updated_at": updated,
            "stale": record_stale,
            "source_url": source_url,
        })
    return {
        "missing": False,
        "items": items,
        "updated_at": newest.isoformat() if newest else None,
        "stale": section_stale,
    }

@app.route('/results')
def results_page():
    return render_template('results.html')

@app.route('/api/results/board', methods=['GET'])
def results_board_list():
    return jsonify({"items": results_board.list_board()})

@app.route('/api/results/board', methods=['POST'])
def results_board_add():
    payload = request.get_json(silent=True) or request.form
    try:
        item = results_board.add_symbol(payload.get("symbol"), payload.get("name"))
    except ValueError:
        return jsonify({"error": "Enter an NSE symbol such as KPIGREEN."}), 400
    return jsonify(item)

@app.route('/api/results/board/<symbol>', methods=['DELETE'])
def results_board_remove(symbol):
    try:
        return jsonify(results_board.remove_symbol(symbol))
    except ValueError:
        return jsonify({"error": "Unknown symbol."}), 400

@app.route('/api/results', methods=['GET'])
def results_feed():
    return jsonify(_load_results())

@app.route('/api/news', methods=['GET'])
def get_news():
    stock = request.args.get('stock', '')
    if not stock:
        index = request.args.get('index', '')
        configured_ids = {item["id"] for item in APP_CONFIG.indices}
        if index in configured_ids or index in {'NIFTY50', 'DOWJONES'}:
            news = news_fetcher.fetch_index_news(index)
            return jsonify({
                'news': attach_summaries(real_articles(list(news)), index),
                'stale': bool(getattr(news, 'stale', False)),
            })
        return jsonify({'error': 'Stock parameter is required'}), 400

    news = news_fetcher.fetch_news(stock)
    return jsonify({
        'news': attach_summaries(real_articles(list(news)), stock),
        'stale': bool(getattr(news, 'stale', False)),
    })

def debug_from_env():
    """FLASK_DEBUG is off unless the environment explicitly turns it on."""
    return os.environ.get("FLASK_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}

if __name__ == '__main__':
    # For local development. Ignore history writes so a search does not
    # restart the reloader and drop the in-memory news cache.
    app.run(
        debug=debug_from_env(),
        host='0.0.0.0',
        port=int(os.environ.get("PORT", "5000")),
        exclude_patterns=['*search_history.json'],
    ) 
