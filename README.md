# Indian Stock News Tracker

A web application that aggregates news for Indian stocks from public RSS feeds, with HTML pages as a fallback. NewsAPI is optional: search works when `NEWS_API_KEY` is empty. Set the key only if you enable the `newsapi` source.

## Features

- Search for news about any Indian stock or market index
- Automatic news aggregation from multiple reliable sources
- Caching system to improve performance and reduce load on news sites
- Search history tracking with easy access to previous searches
- Mobile-friendly responsive design
- Real-time updates for market indices (Nifty 50, Dow Jones)

## Local Development Setup

1. Clone the repository:
   ```
   git clone https://github.com/riddhisc/stocknewstracker.git
   cd stocknewstracker
   ```

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Run the application:
   ```
   python app.py
   ```

4. Access the application at http://127.0.0.1:5000

## Deployment Options

### Option 1: PythonAnywhere (Easiest for Beginners)

1. Sign up for a free account at [PythonAnywhere.com](https://www.pythonanywhere.com)
2. Upload your project files
3. Create a new web app, select Flask framework
4. Set WSGI configuration to point to your app.py file
5. Add the required dependencies in the Virtualenv section

### Option 2: Render

1. Create an account at [Render.com](https://render.com)
2. Create a new Web Service
3. Connect your GitHub repository
4. Render will automatically detect the configuration in render.yaml

### Option 3: Heroku

1. Install the Heroku CLI
2. Deploy with the following commands:
   ```
   heroku login
   git init
   heroku create stocknewstracker
   git add .
   git commit -m "Initial commit"
   git push heroku master
   ```

### Option 4: Docker

1. Build the Docker container:
   ```
   docker build -t stocknewstracker .
   docker run -p 8080:8080 stocknewstracker
   ```

2. Push to any cloud provider that supports Docker containers

## Two watchlists

`config.yaml` chooses the headlines on the desk and on `GET /api/watchlist/news` (names, tickers, and aliases such as Reliance / RELIANCE.NS / RIL). `data/watchlist.json` is separate: `scripts/refresh_results.py` uses it for quarterly results. Changing one file does not change the other.

## Environment Variables

- `PORT`: Port number for the application (default: 5000)
- `HISTORY_FILE`: JSON search history path (default: search_history.json). This file is local and gitignored.
- `NEWS_API_KEY`: Optional. Search does not require it.
- See `.env.example` for `HISTORY_DB`, `LOG_LEVEL`, `CONFIG_PATH`, `ENABLE_SUMMARY`, and `ANTHROPIC_API_KEY`.

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 