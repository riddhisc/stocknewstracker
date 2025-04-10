# Indian Stock News Tracker

A web application that aggregates news for Indian stocks from multiple reliable sources without requiring any API keys.

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
   git clone https://github.com/yourusername/stocknewstracker.git
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

## Environment Variables

- `PORT`: Port number for the application (default: 5000)
- `HISTORY_FILE`: Path to store search history (default: search_history.json)

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 