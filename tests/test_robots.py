import requests

from sources.http import USER_AGENT, HttpClient, path_allowed, rules_for_agent

_GOOGLE_LIKE = """
User-agent: *
Disallow: /
Allow: /$
Allow: /?
Allow: /rss
"""

_BING_URL = "https://www.bing.com/news/search?q=AAVAS+stock&format=rss"
_GOOGLE_RSS = "https://news.google.com/rss/search?q=nifty&hl=en-IN&gl=IN&ceid=IN:en"


def test_specific_allow_beats_a_broad_disallow():
    rules = rules_for_agent(_GOOGLE_LIKE, USER_AGENT)
    assert path_allowed(rules, "https://news.google.com/rss/search?q=nifty") is True
    assert path_allowed(rules, _GOOGLE_RSS) is True
    assert path_allowed(rules, "https://news.google.com/search?q=nifty") is False


def test_real_google_disallow_blocks_rss_without_an_allow():
    text = "User-agent: *\nDisallow: /\nAllow: /$\nAllow: /?\n"
    rules = rules_for_agent(text, USER_AGENT)
    assert path_allowed(rules, _GOOGLE_RSS) is False


def test_robots_fetch_error_does_not_block(monkeypatch):
    def timed_out(*_args, **_kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr("sources.http.requests.get", timed_out)
    client = HttpClient()
    assert client.allowed(_BING_URL) is True
