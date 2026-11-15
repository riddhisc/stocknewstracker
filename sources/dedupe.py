"""Drop the same story when the URL or the title matches."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "ocid",
}


def normalize_url(url):
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING
    ]
    query.sort()
    scheme = (parsed.scheme or "https").lower()
    return urlunparse((scheme, host, path, "", urlencode(query), ""))


def _title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def titles_match(left, right):
    a = _title_key(left)
    b = _title_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) > 24 and len(b) > 24 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.88


def dedupe_articles(articles):
    kept = []
    seen_urls = set()
    for article in articles:
        url_key = normalize_url(article.url)
        if url_key and url_key in seen_urls:
            continue
        if any(titles_match(article.title, previous.title) for previous in kept):
            continue
        if url_key:
            seen_urls.add(url_key)
        kept.append(article)
    kept.sort(key=lambda item: item.published_at or "", reverse=True)
    return kept
