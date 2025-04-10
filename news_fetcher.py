import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
import re
import time
import json
import feedparser
from urllib.parse import quote_plus
import random

class NewsFetcher:
    def __init__(self):
        # List of trusted Indian financial news sources
        self.sources = [
            'moneycontrol.com',
            'economictimes.indiatimes.com',
            'livemint.com',
            'business-standard.com',
            'zeebiz.com',
            'bqprime.com',
            'etnownews.com',
            'capitalmarket.com',
            'sharekhan.com',
            'icicidirect.com',
            'axisdirect.in',
            'hdfcsec.com',
            'ndtv.com/business',
            'financialexpress.com',
            'finance.yahoo.com',
            'reuters.com',
            'bloomberg.com',
            'cnbc.com',
            'thehindubusinessline.com',
            'mint.com'
        ]
        
        # Stock symbol mappings for better search
        self.stock_symbols = {
            'vedanta': ['VEDL', 'VEDANTA'],
            'reliance': ['RELIANCE', 'RIL'],
            'tcs': ['TCS', 'TATA CONSULTANCY'],
            'infosys': ['INFY', 'INFOSYS'],
            'hdfc bank': ['HDFCBANK', 'HDFC BANK'],
            'icici bank': ['ICICIBANK', 'ICICI BANK'],
            'sbi': ['SBIN', 'STATE BANK OF INDIA'],
            'tata motors': ['TATAMOTORS', 'TATA MOTORS'],
            'wipro': ['WIPRO'],
            'asian paints': ['ASIANPAINT', 'ASIAN PAINTS'],
            'hdfc life': ['HDFCLIFE', 'HDFC LIFE'],
            'bajaj finance': ['BAJFINANCE', 'BAJAJ FINANCE'],
            'bajaj finserv': ['BAJAJFINSV', 'BAJAJ FINSERV'],
            'sun pharma': ['SUNPHARMA', 'SUN PHARMA'],
            'maruti': ['MARUTI', 'MARUTI SUZUKI'],
            'axis bank': ['AXISBANK', 'AXIS BANK'],
            'kotak bank': ['KOTAKBANK', 'KOTAK BANK'],
            'lt': ['LT', 'LARSEN & TOUBRO'],
            'hcl tech': ['HCLTECH', 'HCL TECHNOLOGIES'],
            'bharti airtel': ['BHARTIARTL', 'BHARTI AIRTEL']
        }
        
        # Cache for storing news results
        self.news_cache = {}
        self.cache_expiry = 300  # 5 minutes
        
        # Rate limiting
        self.last_request_time = {}
        self.min_request_interval = 2  # seconds between requests to the same domain
        
        # User agents to rotate
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
        ]

    def get_random_user_agent(self):
        """Get a random user agent to avoid detection"""
        return random.choice(self.user_agents)

    def get_domain(self, url):
        """Extract domain from URL for rate limiting"""
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        return parsed_url.netloc

    def make_request(self, url, max_retries=3, timeout=10):
        """Make HTTP requests with retry logic and proper error handling"""
        domain = self.get_domain(url)
        
        # Check rate limiting
        current_time = time.time()
        if domain in self.last_request_time:
            time_since_last_request = current_time - self.last_request_time[domain]
            if time_since_last_request < self.min_request_interval:
                sleep_time = self.min_request_interval - time_since_last_request
                print(f"Rate limiting: waiting {sleep_time:.2f} seconds before requesting {domain}")
                time.sleep(sleep_time)
        
        # Update last request time
        self.last_request_time[domain] = time.time()
        
        # Rotate user agents
        user_agent = self.get_random_user_agent()
        
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Pragma': 'no-cache'
        }
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Exponential backoff with jitter
                    wait_time = min(2 ** attempt + (0.1 * attempt), 10)
                    time.sleep(wait_time)
                
                # Add a small random delay to avoid detection
                time.sleep(random.uniform(0.5, 1.5))
                
                response = requests.get(url, headers=headers, timeout=timeout)
                
                if response.status_code == 200:
                    if len(response.text) > 100:
                        return response
                    else:
                        print(f"Response too short for URL: {url}")
                elif response.status_code == 429:
                    wait_time = min(2 ** attempt, 30)
                    print(f"Rate limited. Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                elif response.status_code == 404:
                    print(f"Page not found (404) for URL: {url}")
                    return None
                elif response.status_code == 410:
                    print(f"Resource gone (410) for URL: {url}")
                    return None
                elif response.status_code == 503:
                    print(f"Service unavailable (503) for URL: {url}")
                    # For 503 errors, wait longer before retrying
                    time.sleep(min(5 * (attempt + 1), 20))
                elif response.status_code == 403:
                    print(f"Access forbidden (403) for URL: {url}")
                    # For 403 errors, try with a different user agent
                    headers['User-Agent'] = self.get_random_user_agent()
                    time.sleep(min(3 * (attempt + 1), 15))
                else:
                    print(f"Request failed with status code {response.status_code} for URL: {url}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
            except requests.exceptions.Timeout:
                print(f"Request timed out for URL: {url}")
                # For timeouts, increase the timeout for the next attempt
                timeout = min(timeout * 1.5, 30)
                if attempt < max_retries - 1:
                    time.sleep(1)
            except requests.exceptions.ConnectionError:
                print(f"Connection error for URL: {url}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            except requests.exceptions.RequestException as e:
                print(f"Request error for URL {url}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                print(f"Unexpected error for URL {url}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        print(f"Failed to fetch URL after {max_retries} attempts: {url}")
        return None

    def parse_date(self, date_str):
        """Parse various date formats to datetime object"""
        if not date_str:
            return datetime.now()
            
        # Clean up the date string
        date_str = date_str.strip()
        
        # Try standard ISO format first
        try:
            return datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            pass
            
        # Try standard datetime format
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
            
        # Try RSS feed format (e.g., "Wed, 10 Apr 2024 15:30:00 GMT")
        try:
            return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
        except ValueError:
            pass
            
        # Try another common RSS format
        try:
            return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
        except ValueError:
            pass
            
        # Try to extract date from various formats using regex
        try:
            # Common Indian date formats
            patterns = [
                # "07 Apr, 2025, 11:13AM IST"
                r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,\s*(\d{4}),\s*(\d{1,2}):(\d{2})(AM|PM)\s*IST',
                # "07 Apr 2025"
                r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
                # "07/04/2025"
                r'(\d{1,2})/(\d{1,2})/(\d{4})',
                # "2025-04-07"
                r'(\d{4})-(\d{1,2})-(\d{1,2})',
                # "April 7, 2025"
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s*(\d{4})',
                # "7 days ago", "2 hours ago", etc.
                r'(\d+)\s+(day|days|hour|hours|minute|minutes|week|weeks|month|months|year|years)\s+ago'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, date_str, re.IGNORECASE)
                if match:
                    if pattern == patterns[0]:  # "07 Apr, 2025, 11:13AM IST"
                        day, month, year, hour, minute, ampm = match.groups()
                        month_map = {
                            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                        }
                        hour = int(hour)
                        if ampm.upper() == 'PM' and hour < 12:
                            hour += 12
                        elif ampm.upper() == 'AM' and hour == 12:
                            hour = 0
                        return datetime(int(year), month_map[month], int(day), hour, int(minute))
                    elif pattern == patterns[1]:  # "07 Apr 2025"
                        day, month, year = match.groups()
                        month_map = {
                            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                        }
                        return datetime(int(year), month_map[month], int(day))
                    elif pattern == patterns[2]:  # "07/04/2025"
                        day, month, year = match.groups()
                        return datetime(int(year), int(month), int(day))
                    elif pattern == patterns[3]:  # "2025-04-07"
                        year, month, day = match.groups()
                        return datetime(int(year), int(month), int(day))
                    elif pattern == patterns[4]:  # "April 7, 2025"
                        month, day, year = match.groups()
                        month_map = {
                            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                        }
                        return datetime(int(year), month_map[month], int(day))
                    elif pattern == patterns[5]:  # "7 days ago", etc.
                        amount, unit = match.groups()
                        amount = int(amount)
                        if unit.startswith('day'):
                            return datetime.now() - timedelta(days=amount)
                        elif unit.startswith('hour'):
                            return datetime.now() - timedelta(hours=amount)
                        elif unit.startswith('minute'):
                            return datetime.now() - timedelta(minutes=amount)
                        elif unit.startswith('week'):
                            return datetime.now() - timedelta(weeks=amount)
                        elif unit.startswith('month'):
                            return datetime.now() - timedelta(days=amount*30)
                        elif unit.startswith('year'):
                            return datetime.now() - timedelta(days=amount*365)
        except Exception as e:
            print(f"Error parsing date with regex: {str(e)}")
        
        # Special cases for relative time expressions
        if 'hour' in date_str.lower() or 'hr' in date_str.lower():
            hours = 1
            if date_str[0].isdigit():
                hours = int(date_str[0])
            return datetime.now() - timedelta(hours=hours)
        
        if 'min' in date_str.lower():
            minutes = 5
            if date_str[0].isdigit():
                minutes = int(date_str[0])
            return datetime.now() - timedelta(minutes=minutes)
            
        if 'yesterday' in date_str.lower():
            return datetime.now() - timedelta(days=1)
            
        if 'day' in date_str.lower():
            # Extract number of days
            days = 1
            for word in date_str.split():
                if word.isdigit():
                    days = int(word)
                    break
            return datetime.now() - timedelta(days=days)
        
        # If all parsing attempts fail, return current time
        print(f"Could not parse date: {date_str}, using current time instead")
        return datetime.now()

    def parse_rss_date(self, date_str):
        """Parse RSS date format with GMT timezone"""
        if not date_str:
            return datetime.now()
            
        try:
            # Try to parse the date string directly
            # This handles the format 'Tue, 08 Apr 2025 10:24:09 GMT'
            return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
        except ValueError:
            try:
                # Try with timezone format
                return datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
            except ValueError:
                # If all parsing attempts fail, return current time
                print(f"Could not parse RSS date: {date_str}, using current time instead")
                return datetime.now()

    def fetch_news(self, stock, days_back=7):
        """Fetch news for a given stock from multiple sources"""
        # Special case for market indices
        if stock.upper() in ['NIFTY50', 'NIFTY', 'NIFTY 50']:
            return self.fetch_index_news('NIFTY50')
        elif stock.upper() in ['DOWJONES', 'DOW JONES', 'DOW']:
            return self.fetch_index_news('DOWJONES')
        
        # Regular stock handling (existing code)
        # Check cache first
        current_time = time.time()
        if stock in self.news_cache:
            cached_data, timestamp = self.news_cache[stock]
            if current_time - timestamp < self.cache_expiry:
                print(f"Returning cached news for {stock}")
                return cached_data
            else:
                print(f"Cache expired for {stock}, fetching fresh news")
        
        all_news = []
        has_results = False
        
        # Handle common variations of stock names
        search_terms = [stock]
        
        # Add stock symbols if available
        if stock.lower() in self.stock_symbols:
            search_terms.extend(self.stock_symbols[stock.lower()])
        
        # Add "Limited" if not already in the search term
        if "limited" not in stock.lower() and "ltd" not in stock.lower():
            search_terms.append(f"{stock} Limited")
        
        # Add stock symbol if it's a common format
        if stock.isupper() and len(stock) <= 5:
            search_terms.append(f"{stock} stock")
            search_terms.append(f"{stock} share")
        
        # Special cases for common stocks
        if stock.lower() == 'vedanta' or stock.upper() == 'VEDL':
            if 'VEDL' not in search_terms:
                search_terms.append('VEDL')
            if 'Vedanta' not in search_terms:
                search_terms.append('Vedanta')
        elif stock.lower() == 'infosys' or stock.upper() == 'INFY':
            if 'INFY' not in search_terms:
                search_terms.append('INFY')
            if 'Infosys' not in search_terms:
                search_terms.append('Infosys')
                
        print(f"Search terms for {stock}: {search_terms}")
        
        # Try each search term
        for i, search_term in enumerate(search_terms):
            # Only try the first two search terms to save time
            if i >= 2:
                break
                
            print(f"Trying search term: {search_term}")
            
            # 1. Try Yahoo Finance first (most reliable)
            try:
                print("Fetching from Yahoo Finance...")
                yahoo_url = f"https://finance.yahoo.com/quote/{quote_plus(search_term)}/news"
                response = self.make_request(yahoo_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('li.js-stream-content')
                    
                    for article in articles[:15]:
                        try:
                            title_elem = article.select_one('h3')
                            if not title_elem:
                                continue
                                
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://finance.yahoo.com' + url
                                
                            title = title_elem.text.strip()
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from Yahoo Finance",
                                'url': url,
                                'source': 'Yahoo Finance',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Yahoo Finance article: {title}")
                        except Exception as e:
                            print(f"Error processing Yahoo Finance article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Yahoo Finance: {str(e)}")
            
            # 2. Try Google News RSS feed
            try:
                print("Fetching from Google News RSS...")
                encoded_term = quote_plus(search_term)
                rss_url = f"https://news.google.com/rss/search?q={encoded_term}+stock+market&hl=en-IN&gl=IN&ceid=IN:en"
                
                response = self.make_request(rss_url)
                if response and response.status_code == 200:
                    feed = feedparser.parse(response.text)
                    
                    for entry in feed.entries[:20]:
                        try:
                            # Fix for date parsing issue
                            published_at_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
                            if hasattr(entry, 'published'):
                                try:
                                    # Use our custom parser for RSS dates
                                    published_at = self.parse_rss_date(entry.published)
                                    published_at_str = published_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                                except Exception as e:
                                    print(f"Error parsing date '{entry.published}': {str(e)}")
                                    
                            # Only add if title isn't empty
                            if hasattr(entry, 'title') and entry.title.strip():
                                all_news.append({
                                    'title': entry.title,
                                    'description': entry.summary if hasattr(entry, 'summary') else f"News about {search_term}",
                                    'url': entry.link,
                                    'source': entry.source.title if hasattr(entry, 'source') and hasattr(entry.source, 'title') else 'Google News',
                                    'published_at': published_at_str,
                                    'type': 'rss'
                                })
                                has_results = True
                                print(f"Found Google News article: {entry.title}")
                        except Exception as e:
                            print(f"Error processing Google News entry: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Google News RSS: {str(e)}")
            
            # 3. Try Economic Times
            try:
                print("Fetching from Economic Times...")
                et_url = f"https://economictimes.indiatimes.com/searchresult.cms?q={quote_plus(search_term)}"
                response = self.make_request(et_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.find_all('div', class_='eachStory')
                    
                    for article in articles[:10]:
                        try:
                            title_elem = article.find('h3')
                            if not title_elem:
                                continue
                                
                            link_elem = article.find('a')
                            if not link_elem:
                                continue
                                
                            url = 'https://economictimes.indiatimes.com' + link_elem.get('href', '')
                            title = title_elem.text.strip()
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from Economic Times",
                                'url': url,
                                'source': 'Economic Times',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Economic Times article: {title}")
                        except Exception as e:
                            print(f"Error processing Economic Times article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Economic Times: {str(e)}")
            
            # 4. Try Livemint
            try:
                print("Fetching from Livemint...")
                # Use the market page instead of search
                lm_url = "https://www.livemint.com/market"
                response = self.make_request(lm_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.headline, .searchHeadline, .listingNews')
                    
                    for article in articles[:20]:
                        try:
                            title_elem = article.find('h2') or article.find('h3')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            # Only include if it contains our search term
                            if search_term.lower() not in title.lower():
                                continue
                                
                            link_elem = article.find('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.livemint.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from Livemint",
                                'url': url,
                                'source': 'Livemint',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Livemint article: {title}")
                        except Exception as e:
                            print(f"Error processing Livemint article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Livemint: {str(e)}")
                
            # 5. Try Google News (direct scraping)
            try:
                print("Fetching from Google News...")
                google_url = f"https://news.google.com/search?q={quote_plus(search_term)}+stock+market&hl=en-IN&gl=IN&ceid=IN:en"
                response = self.make_request(google_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('article')
                    
                    for article in articles[:15]:
                        try:
                            title_elem = article.select_one('h3, h4')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if url.startswith('./'):
                                url = 'https://news.google.com' + url[1:]
                            elif not url.startswith('http'):
                                url = 'https://news.google.com' + url
                            
                            source_elem = article.select_one('.wEwyrc, .MfV47')
                            source = source_elem.text.strip() if source_elem else 'Google News'
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from {source}",
                                'url': url,
                                'source': source,
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Google News article: {title}")
                        except Exception as e:
                            print(f"Error processing Google News article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Google News: {str(e)}")
            
            # 6. Try Reuters
            try:
                print("Fetching from Reuters...")
                reuters_url = f"https://www.reuters.com/search/news?blob={quote_plus(search_term)}+india+stock"
                response = self.make_request(reuters_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.search-result-content, .story-content')
                    
                    for article in articles[:10]:
                        try:
                            title_elem = article.select_one('h3')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.reuters.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from Reuters",
                                'url': url,
                                'source': 'Reuters',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Reuters article: {title}")
                        except Exception as e:
                            print(f"Error processing Reuters article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Reuters: {str(e)}")
            
            # 7. Try Financial Express
            try:
                print("Fetching from Financial Express...")
                fe_url = f"https://www.financialexpress.com/search/{quote_plus(search_term)}+stock/"
                response = self.make_request(fe_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.article-list .article')
                    
                    for article in articles[:10]:
                        try:
                            title_elem = article.select_one('h3')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.financialexpress.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from Financial Express",
                                'url': url,
                                'source': 'Financial Express',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found Financial Express article: {title}")
                        except Exception as e:
                            print(f"Error processing Financial Express article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Financial Express: {str(e)}")
            
            # 8. Try NDTV Business
            try:
                print("Fetching from NDTV Business...")
                ndtv_url = f"https://www.ndtv.com/business/search?query={quote_plus(search_term)}+stock"
                response = self.make_request(ndtv_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.news_item')
                    
                    for article in articles[:10]:
                        try:
                            title_elem = article.select_one('h2')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.ndtv.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {search_term} from NDTV Business",
                                'url': url,
                                'source': 'NDTV Business',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            has_results = True
                            print(f"Found NDTV Business article: {title}")
                        except Exception as e:
                            print(f"Error processing NDTV Business article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from NDTV Business: {str(e)}")
        
        # If no news found, add a dummy news item
        if not has_results:
            all_news.append({
                'title': f"No recent news found for {stock}",
                'description': "Try another search term or check back later for updates.",
                'url': "https://www.google.com/search?q=" + quote_plus(f"{stock} stock news"),
                'source': 'Info',
                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'type': 'info'
            })
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_news = []
        for news in all_news:
            if news['url'] not in seen_urls:
                seen_urls.add(news['url'])
                unique_news.append(news)
        
        # Sort by published date
        unique_news.sort(key=lambda x: x['published_at'], reverse=True)
        
        # Cache the results
        self.news_cache[stock] = (unique_news, current_time)
        
        print(f"Returning {len(unique_news)} news items for {stock}")
        return unique_news

    def fetch_index_news(self, index_name):
        """Fetch news specifically for market indices like NIFTY50 or DOWJONES"""
        print(f"Fetching news for market index: {index_name}")
        all_news = []
        
        # Check cache first
        current_time = time.time()
        if index_name in self.news_cache:
            cached_data, timestamp = self.news_cache[index_name]
            if current_time - timestamp < self.cache_expiry:
                print(f"Returning cached news for {index_name}")
                return cached_data
        
        if index_name == 'NIFTY50':
            # Search terms for Nifty 50
            search_terms = [
                'Nifty 50', 
                'Nifty50', 
                'NSE index', 
                'NSE Nifty', 
                'Indian market index',
                'Sensex today' # Add Sensex as it's closely related
            ]
        elif index_name == 'DOWJONES':
            # Search terms for Dow Jones
            search_terms = [
                'Dow Jones', 
                'DJIA', 
                'Dow Jones Industrial Average', 
                'US market index',
                'Wall Street index',
                'S&P 500 today' # Add S&P 500 as it's closely related
            ]
        else:
            # Default to the index name as the only search term
            search_terms = [index_name]
        
        # Try different news sources with each search term
        for search_term in search_terms:
            try:
                # Google News RSS feed (most reliable source for indices)
                print(f"Searching Google News for {search_term}")
                encoded_term = quote_plus(f"{search_term} market")
                rss_url = f"https://news.google.com/rss/search?q={encoded_term}&hl=en-IN&gl=IN&ceid=IN:en"
                
                response = self.make_request(rss_url)
                if response and response.status_code == 200:
                    feed = feedparser.parse(response.text)
                    
                    for entry in feed.entries[:15]:  # Get more entries for indices
                        try:
                            # Fix for date parsing issue
                            published_at_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
                            if hasattr(entry, 'published'):
                                try:
                                    published_at = self.parse_rss_date(entry.published)
                                    published_at_str = published_at.strftime('%Y-%m-%dT%H:%M:%SZ')
                                except Exception as e:
                                    print(f"Error parsing date '{entry.published}': {str(e)}")
                                    
                            # Only add if title isn't empty
                            if hasattr(entry, 'title') and entry.title.strip():
                                all_news.append({
                                    'title': entry.title,
                                    'description': entry.summary if hasattr(entry, 'summary') else f"News about {search_term}",
                                    'url': entry.link,
                                    'source': entry.source.title if hasattr(entry, 'source') and hasattr(entry.source, 'title') else 'Google News',
                                    'published_at': published_at_str,
                                    'type': 'rss'
                                })
                                print(f"Found Google News article for {index_name}: {entry.title}")
                        except Exception as e:
                            print(f"Error processing Google News entry: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Google News RSS: {str(e)}")
        
        # For NIFTY50, try Economic Times and LiveMint directly
        if index_name == 'NIFTY50':
            # Economic Times markets page
            try:
                print("Fetching from Economic Times for Nifty 50")
                et_url = "https://economictimes.indiatimes.com/markets/live-coverage"
                response = self.make_request(et_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.story_list .eachStory')
                    
                    for article in articles[:8]:
                        try:
                            title_elem = article.select_one('h3')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            # Only include relevant articles
                            if not ('nifty' in title.lower() or 'sensex' in title.lower() or 'market' in title.lower()):
                                continue
                                
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://economictimes.indiatimes.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': "Nifty 50 market update from Economic Times",
                                'url': url,
                                'source': 'Economic Times',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            print(f"Found Economic Times article for Nifty: {title}")
                        except Exception as e:
                            print(f"Error processing Economic Times article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from Economic Times: {str(e)}")
                
            # LiveMint markets page
            try:
                print("Fetching from LiveMint for Nifty 50")
                lm_url = "https://www.livemint.com/market"
                response = self.make_request(lm_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.headline, .combineUpdate li')
                    
                    for article in articles[:8]:
                        try:
                            title_elem = article.select_one('h2, h3, .headline a')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            # Only include relevant articles
                            if not ('nifty' in title.lower() or 'sensex' in title.lower() or 'market' in title.lower()):
                                continue
                                
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.livemint.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': "Nifty 50 market update from LiveMint",
                                'url': url,
                                'source': 'LiveMint',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            print(f"Found LiveMint article for Nifty: {title}")
                        except Exception as e:
                            print(f"Error processing LiveMint article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from LiveMint: {str(e)}")
        
        # For DOWJONES, try financial news sources directly
        elif index_name == 'DOWJONES':
            # MarketWatch
            try:
                print("Fetching from MarketWatch for Dow Jones")
                mw_url = "https://www.marketwatch.com/investing/index/djia"
                response = self.make_request(mw_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.article__content')
            
                    for article in articles[:8]:
                        try:
                            title_elem = article.select_one('h3.article__headline')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.marketwatch.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': "Dow Jones market update from MarketWatch",
                                'url': url,
                                'source': 'MarketWatch',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            print(f"Found MarketWatch article for Dow Jones: {title}")
                        except Exception as e:
                            print(f"Error processing MarketWatch article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from MarketWatch: {str(e)}")
                
            # CNBC
            try:
                print("Fetching from CNBC for Dow Jones")
                cnbc_url = "https://www.cnbc.com/quotes/.DJI"
                response = self.make_request(cnbc_url)
                
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('.Card-titleContainer')
                    
                    for article in articles[:8]:
                        try:
                            title_elem = article.select_one('.Card-title')
                            if not title_elem:
                                continue
            
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if not url.startswith('http'):
                                url = 'https://www.cnbc.com' + url
                            
                            all_news.append({
                                'title': title,
                                'description': "Dow Jones market update from CNBC",
                                'url': url,
                                'source': 'CNBC',
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            print(f"Found CNBC article for Dow Jones: {title}")
                        except Exception as e:
                            print(f"Error processing CNBC article: {str(e)}")
            except Exception as e:
                print(f"Error fetching from CNBC: {str(e)}")

        # If no news found, try direct Google News scraping
        if len(all_news) < 5:
            try:
                google_url = f"https://news.google.com/search?q={quote_plus(index_name)}+market&hl=en-US&gl=US&ceid=US:en"
                response = self.make_request(google_url)
            
                if response and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    articles = soup.select('article')
            
                    for article in articles[:10]:
                        try:
                            title_elem = article.select_one('h3, h4')
                            if not title_elem:
                                continue
                                
                            title = title_elem.text.strip()
                            
                            link_elem = article.select_one('a')
                            if not link_elem:
                                continue
                                
                            url = link_elem.get('href', '')
                            if url.startswith('./'):
                                url = 'https://news.google.com' + url[1:]
                            elif not url.startswith('http'):
                                url = 'https://news.google.com' + url
                            
                            source_elem = article.select_one('.TVtOme')
                            source = source_elem.text.strip() if source_elem else 'Google News'
                            
                            all_news.append({
                                'title': title,
                                'description': f"News about {index_name} from {source}",
                                'url': url,
                                'source': source,
                                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'type': 'scrape'
                            })
                            print(f"Found direct Google News article for {index_name}: {title}")
                        except Exception as e:
                            print(f"Error processing direct Google News article: {str(e)}")
            except Exception as e:
                print(f"Error fetching directly from Google News: {str(e)}")
        
        # If still no news found, add a dummy news item
        if len(all_news) == 0:
            all_news.append({
                'title': f"No recent news found for {index_name}",
                'description': "Try again later for market updates.",
                'url': f"https://www.google.com/search?q={quote_plus(f'{index_name} market news')}",
                'source': 'Info',
                'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'type': 'info'
            })
            
            # Also add a generic market update
            if index_name == 'NIFTY50':
                all_news.append({
                    'title': "Indian Market Daily Update",
                    'description': "View the latest updates on Indian stock market performance.",
                    'url': "https://www.nseindia.com/",
                    'source': 'NSE India',
                    'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'type': 'info'
                })
            elif index_name == 'DOWJONES':
                all_news.append({
                    'title': "US Market Daily Update",
                    'description': "View the latest updates on US stock market performance.",
                    'url': "https://www.wsj.com/market-data/quotes/index/DJIA",
                    'source': 'Wall Street Journal',
                    'published_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'type': 'info'
                })
        
        # Remove duplicates based on URL
        seen_urls = set()
        unique_news = []
        for news in all_news:
            if news['url'] not in seen_urls:
                seen_urls.add(news['url'])
                unique_news.append(news)
        
        # Sort by published date
        unique_news.sort(key=lambda x: x['published_at'], reverse=True)
        
        # Cache the results
        self.news_cache[index_name] = (unique_news, current_time)
        
        print(f"Returning {len(unique_news)} news items for {index_name}")
        return unique_news 