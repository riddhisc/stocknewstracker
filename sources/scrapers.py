"""HTML fallbacks. Used only when RSS returns nothing. Selectors match the previous fetcher."""

from __future__ import annotations

from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from sources.base import Article, NewsSource, utc_now_iso


def _abs(href, origin):
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("./"):
        return origin + href[1:]
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return origin + href
    return origin.rstrip("/") + "/" + href


def _article(title, url, source, summary, symbols=None):
    title = (title or "").strip()
    if not title or not url:
        return None
    return Article(
        title=title,
        url=url,
        source=source,
        published_at=utc_now_iso(),
        summary=summary,
        symbols=list(symbols or []),
        kind="scrape",
    )


class HtmlSource(NewsSource):
    scopes = frozenset({"stock"})
    default_enabled = True

    def fetch(self, query: str) -> list[Article]:
        response = self.http.get(self.build_url(query), timeout=self.timeout)
        return self.parse(response.text, query)

    def build_url(self, query):
        raise NotImplementedError

    def parse(self, html, query):
        raise NotImplementedError


class YahooFinanceSource(HtmlSource):
    name = "yahoo_finance"
    default_priority = 10

    def build_url(self, query):
        return f"https://finance.yahoo.com/quote/{quote_plus(query)}/news"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select("li.js-stream-content")[:15]:
            title_elem = node.select_one("h3")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://finance.yahoo.com"),
                "Yahoo Finance",
                f"News about {query} from Yahoo Finance",
            )
            if item:
                articles.append(item)
        return articles


class EconomicTimesSource(HtmlSource):
    name = "economic_times"
    default_priority = 20

    def build_url(self, query):
        return (
            "https://economictimes.indiatimes.com/searchresult.cms?q="
            + quote_plus(query)
        )

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.find_all("div", class_="eachStory")[:10]:
            title_elem = node.find("h3")
            link_elem = node.find("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://economictimes.indiatimes.com"),
                "Economic Times",
                f"News about {query} from Economic Times",
            )
            if item:
                articles.append(item)
        return articles


class EconomicTimesNiftySource(HtmlSource):
    name = "economic_times_nifty"
    scopes = frozenset({"nifty"})
    default_priority = 21

    def build_url(self, query):
        return "https://economictimes.indiatimes.com/markets/live-coverage"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".story_list .eachStory")[:8]:
            title_elem = node.select_one("h3")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            title = title_elem.get_text(strip=True)
            lowered = title.lower()
            if not any(word in lowered for word in ("nifty", "sensex", "market")):
                continue
            item = _article(
                title,
                _abs(link_elem.get("href", ""), "https://economictimes.indiatimes.com"),
                "Economic Times",
                "Nifty 50 market update from Economic Times",
            )
            if item:
                articles.append(item)
        return articles


class LivemintSource(HtmlSource):
    name = "livemint"
    scopes = frozenset({"stock", "nifty"})
    default_priority = 30

    def build_url(self, query):
        return "https://www.livemint.com/market"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        index_query = query.lower() in {
            "nifty 50", "nifty50", "nse index", "nse nifty", "indian market index", "sensex today",
        }
        for node in soup.select(".headline, .searchHeadline, .listingNews, .combineUpdate li")[:20]:
            title_elem = node.find("h2") or node.find("h3") or node.select_one(".headline a")
            link_elem = node.find("a")
            if not title_elem or not link_elem:
                continue
            title = title_elem.get_text(strip=True)
            lowered = title.lower()
            if index_query:
                if not any(word in lowered for word in ("nifty", "sensex", "market")):
                    continue
                summary = "Nifty 50 market update from LiveMint"
            elif query.lower() not in lowered:
                continue
            else:
                summary = f"News about {query} from Livemint"
            item = _article(
                title,
                _abs(link_elem.get("href", ""), "https://www.livemint.com"),
                "Livemint" if not index_query else "LiveMint",
                summary,
            )
            if item:
                articles.append(item)
        return articles


class GoogleNewsHtmlSource(HtmlSource):
    name = "google_news_html"
    scopes = frozenset({"stock", "nifty", "dow"})
    default_priority = 40

    def build_url(self, query):
        return (
            "https://news.google.com/search?q="
            f"{quote_plus(query)}+stock+market&hl=en-IN&gl=IN&ceid=IN:en"
        )

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select("article")[:15]:
            title_elem = node.select_one("h3, h4")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            source_elem = node.select_one(".wEwyrc, .MfV47, .TVtOme")
            source = source_elem.get_text(strip=True) if source_elem else "Google News"
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://news.google.com"),
                source,
                f"News about {query} from {source}",
            )
            if item:
                articles.append(item)
        return articles


class ReutersSource(HtmlSource):
    name = "reuters"
    default_priority = 50

    def build_url(self, query):
        return (
            "https://www.reuters.com/search/news?blob="
            f"{quote_plus(query)}+india+stock"
        )

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".search-result-content, .story-content")[:10]:
            title_elem = node.select_one("h3")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://www.reuters.com"),
                "Reuters",
                f"News about {query} from Reuters",
            )
            if item:
                articles.append(item)
        return articles


class FinancialExpressSource(HtmlSource):
    name = "financial_express"
    default_priority = 60

    def build_url(self, query):
        return f"https://www.financialexpress.com/search/{quote_plus(query)}+stock/"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".article-list .article")[:10]:
            title_elem = node.select_one("h3")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://www.financialexpress.com"),
                "Financial Express",
                f"News about {query} from Financial Express",
            )
            if item:
                articles.append(item)
        return articles


class NdtvSource(HtmlSource):
    name = "ndtv"
    default_priority = 70

    def build_url(self, query):
        return (
            "https://www.ndtv.com/business/search?query="
            f"{quote_plus(query)}+stock"
        )

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".news_item")[:10]:
            title_elem = node.select_one("h2")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://www.ndtv.com"),
                "NDTV Business",
                f"News about {query} from NDTV Business",
            )
            if item:
                articles.append(item)
        return articles


class MarketWatchSource(HtmlSource):
    name = "marketwatch"
    scopes = frozenset({"dow"})
    default_priority = 80

    def build_url(self, query):
        return "https://www.marketwatch.com/investing/index/djia"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".article__content")[:8]:
            title_elem = node.select_one("h3.article__headline")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://www.marketwatch.com"),
                "MarketWatch",
                "Dow Jones market update from MarketWatch",
            )
            if item:
                articles.append(item)
        return articles


class CnbcSource(HtmlSource):
    name = "cnbc"
    scopes = frozenset({"dow"})
    default_priority = 90

    def build_url(self, query):
        return "https://www.cnbc.com/quotes/.DJI"

    def parse(self, html, query):
        soup = BeautifulSoup(html, "html.parser")
        articles = []
        for node in soup.select(".Card-titleContainer")[:8]:
            title_elem = node.select_one(".Card-title")
            link_elem = node.select_one("a")
            if not title_elem or not link_elem:
                continue
            item = _article(
                title_elem.get_text(strip=True),
                _abs(link_elem.get("href", ""), "https://www.cnbc.com"),
                "CNBC",
                "Dow Jones market update from CNBC",
            )
            if item:
                articles.append(item)
        return articles
