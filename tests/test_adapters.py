from pathlib import Path

from sources.base import Article
from sources.dedupe import dedupe_articles
from sources.rss import articles_from_feed
from sources.scrapers import YahooFinanceSource

FIXTURES = Path(__file__).parent / "fixtures"


def test_rss_fixture_parses_titles_and_skips_blanks():
    xml = (FIXTURES / "google_news.xml").read_text(encoding="utf-8")
    articles = articles_from_feed(xml, "Reliance")
    titles = [article.title for article in articles]
    assert titles == ["Reliance raises capex", "Bank credit stays firm"]
    assert articles[0].source == "Mint"
    assert articles[0].kind == "rss"
    assert articles[0].published_at.startswith("2025-04-08")
    assert "spending" in articles[0].summary


def test_bing_fixture_parses_a_headline():
    xml = (FIXTURES / "bing_news.xml").read_text(encoding="utf-8")
    articles = articles_from_feed(xml, "AAVAS", default_source="Bing News")
    assert len(articles) == 1
    assert articles[0].title == "AAVAS Financiers share price jumps"
    assert articles[0].source == "Mint"
    assert articles[0].url == "https://example.com/aavas-jumps"


def test_yahoo_fixture_parses_relative_links():
    html = (FIXTURES / "yahoo_news.html").read_text(encoding="utf-8")
    articles = YahooFinanceSource(http=None).parse(html, "RELIANCE")
    assert len(articles) == 1
    assert articles[0].title == "Reliance outlines spending plan"
    assert articles[0].url == "https://finance.yahoo.com/quote/RELIANCE.NS/news/capex"
    assert articles[0].source == "Yahoo Finance"


def test_dedupe_collapses_url_and_fuzzy_title():
    articles = [
        Article(
            title="Reliance raises capex",
            url="https://www.example.com/reliance-capex?utm_source=news",
            source="Mint",
            published_at="2025-04-08T10:24:09Z",
            summary="one",
        ),
        Article(
            title="Reliance raises capex",
            url="https://example.com/reliance-capex",
            source="Copy",
            published_at="2025-04-08T09:00:00Z",
            summary="two",
        ),
        Article(
            title="Reliance raises capital expenditure plan",
            url="https://example.com/other",
            source="Wire",
            published_at="2025-04-08T11:00:00Z",
            summary="three",
        ),
        Article(
            title="Bank credit stays firm",
            url="https://example.com/bank-credit",
            source="Desk",
            published_at="2025-04-07T06:00:00Z",
            summary="four",
        ),
    ]
    kept = dedupe_articles(articles)
    assert [article.title for article in kept] == [
        "Reliance raises capital expenditure plan",
        "Reliance raises capex",
        "Bank credit stays firm",
    ]
