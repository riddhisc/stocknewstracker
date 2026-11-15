from flask import Flask, render_template, request, jsonify, send_from_directory
from news_fetcher import NewsFetcher
import schedule
import time
import threading
import os
from flask_cors import CORS
import json
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, static_folder='static')
CORS(app)
news_fetcher = NewsFetcher()

# One cache shape for every stock: {"data": [articles], "fetched_at": unix time}.
# Readers must use cache_get(); the value is not a tuple.
news_cache = {}
NEWS_CACHE_TTL_SECONDS = 15 * 60

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

def cache_get(stock):
    """Return cached articles, or None when missing or older than the TTL."""
    articles, fresh = _cache_entry(stock)
    if not fresh:
        return None
    return articles

def cache_peek(stock):
    """Return the last articles even when the TTL has passed."""
    articles, _fresh = _cache_entry(stock)
    return articles

# File to store search history
HISTORY_FILE = os.environ.get('HISTORY_FILE', 'search_history.json')

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
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Could not read search history: {exc}")
        return []

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f)

SYMBOLS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'symbols.json')

def load_symbols():
    try:
        with open(SYMBOLS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read symbol list: {exc}")
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

@app.route('/')
def home():
    return render_template('index.html')

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
            print(f"Using cached news for {stock}")
        else:
            if force_refresh:
                print(f"{stock} search detected - forcing refresh of cache and fetching fresh news")
            else:
                print(f"{stock} search detected - fetching fresh news")
            news = news_fetcher.fetch_news(stock, force=force_refresh)
            stale = bool(getattr(news, "stale", False))
            if not isinstance(news, list):
                print(f"Warning: News is not a list, converting. Type: {type(news)}")
                try:
                    news = list(news) if news else []
                except TypeError:
                    news = []
            news = [item for item in news if isinstance(item, dict)]
            if stale:
                previous = cache_peek(stock)
                if previous and not news:
                    news = previous
            else:
                cache_put(stock, news)

        if served_cached:
            news = [item for item in news if isinstance(item, dict)]
        
        # Update search history
        history = load_history()
        history.append({
            'stock': stock,
            'timestamp': datetime.now().isoformat(),
            'count': len(news)
        })
        # Keep only last 50 searches
        history = history[-50:]
        save_history(history)
        
        return jsonify({
            'news': news,
            'history': history,
            'cached': served_cached,
            'stale': stale,
        })
    except Exception as e:
        print(f"Error in search endpoint: {e.__class__.__name__}")
        previous = []
        try:
            previous = cache_peek(stock) or []
        except Exception:
            previous = []
        if previous:
            return jsonify({
                'news': previous,
                'history': load_history(),
                'cached': False,
                'stale': True,
            })
        return jsonify({
            'error': f"Server error: {e.__class__.__name__}",
            'news': [],
            'history': load_history(),
            'stale': False,
        }), 500

@app.route('/api/suggest')
def suggest_symbols():
    return jsonify(match_symbols(request.args.get('q', '')))

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(load_history())

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    save_history([])
    return jsonify({"message": "History cleared"})

@app.route('/api/history/<stock>', methods=['DELETE'])
def delete_history_item(stock):
    history = load_history()
    
    # Filter out entries for the specified stock
    updated_history = [item for item in history if item['stock'].upper() != stock.upper()]
    
    # Save the updated history
    save_history(updated_history)
    
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

@app.route('/api/news', methods=['GET'])
def get_news():
    stock = request.args.get('stock', '')
    if not stock:
        index = request.args.get('index', '')
        if index in ['NIFTY50', 'DOWJONES']:
            news = news_fetcher.fetch_index_news(index)
            return jsonify({
                'news': list(news),
                'stale': bool(getattr(news, 'stale', False)),
            })
        return jsonify({'error': 'Stock parameter is required'}), 400

    news = news_fetcher.fetch_news(stock)
    return jsonify({
        'news': list(news),
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
        port=int(os.environ.get('PORT', 5000)),
        exclude_patterns=['*search_history.json'],
    ) 