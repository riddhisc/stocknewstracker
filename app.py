from flask import Flask, render_template, request, jsonify, send_from_directory
from news_fetcher import NewsFetcher
import schedule
import time
import threading
import os
from flask_cors import CORS
import json
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)
news_fetcher = NewsFetcher()

# Store news cache
news_cache = {}

# File to store search history
HISTORY_FILE = os.environ.get('HISTORY_FILE', 'search_history.json')

def update_news_cache():
    global news_cache
    for stock in news_cache.keys():
        news_cache[stock] = news_fetcher.fetch_news(stock)

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
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

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
        
        # Check if we already have this stock in the cache
        if stock in news_cache and not force_refresh:
            print(f"Using cached news for {stock}")
            news = news_cache[stock]
        else:
            # Only clear cache if specifically requested or not in cache
            if force_refresh:
                print(f"{stock} search detected - forcing refresh of cache and fetching fresh news")
                # If we have the stock in cache, remove it to force a fresh fetch
                if stock in news_cache:
                    del news_cache[stock]
            else:
                print(f"{stock} search detected - fetching fresh news")
            
            # Fetch fresh news
            news = news_fetcher.fetch_news(stock)
            
            # Store in cache for future use
            news_cache[stock] = news
        
        # Make sure news is always a list
        if not isinstance(news, list):
            print(f"Warning: News is not a list, converting. Type: {type(news)}")
            try:
                news = list(news) if news else []
            except:
                news = []
        
        # Filter out any non-dictionary items
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
            'cached': stock in news_cache and not force_refresh
        })
    except Exception as e:
        print(f"Error in search endpoint: {str(e)}")
        return jsonify({
            'error': f"Server error: {str(e)}",
            'news': [],
            'history': load_history()
        }), 500

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
    """Check if a stock has cached news data available"""
    has_cache = stock in news_cache
    
    # For cached items, update the timestamp to extend their life
    if has_cache:
        current_time = time.time()
        data, old_timestamp = news_cache[stock]
        
        # Update the timestamp to extend cache life if it's older than 1 minute
        if current_time - old_timestamp > 60:
            print(f"Extending cache life for {stock}")
            news_cache[stock] = (data, current_time)
    
    return jsonify({
        "stock": stock,
        "hasCache": has_cache
    })

@app.route('/api/news', methods=['GET'])
def get_news():
    stock = request.args.get('stock', '')
    if not stock:
        # Handle specific requests for market indices
        index = request.args.get('index', '')
        if index in ['NIFTY50', 'DOWJONES']:
            fetcher = NewsFetcher()
            news = fetcher.fetch_index_news(index)
            return jsonify({'news': news})
        return jsonify({'error': 'Stock parameter is required'}), 400
        
    # Process regular stock requests
    fetcher = NewsFetcher()
    news = fetcher.fetch_news(stock)
    return jsonify({'news': news})

if __name__ == '__main__':
    # For local development
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000))) 