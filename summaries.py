"""Optional headline summaries. Off unless ENABLE_SUMMARY is true.

A missing key, a timeout, or an API error leaves the articles unchanged.
The key is never written to a log.
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests

from logutil import log_event

_TRUE = {"1", "true", "yes", "on"}
_SENTIMENTS = {"positive", "neutral", "negative"}
_TOP = 5
_TIMEOUT_SECONDS = 8


def summaries_enabled():
    return os.environ.get("ENABLE_SUMMARY", "false").strip().lower() in _TRUE


def apply_summaries(articles, query, store):
    """Add llm_summary and sentiment to the top articles. Never raises."""
    if not isinstance(articles, list) or not summaries_enabled():
        return articles
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log_event(logging.WARNING, "summary", outcome="skip", error="missing_key")
        return articles
    attached = 0
    for article in articles:
        if attached >= _TOP:
            break
        if not isinstance(article, dict) or article.get("type") == "info":
            continue
        url = (article.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        if article.get("llm_summary") and article.get("sentiment") in _SENTIMENTS:
            attached += 1
            continue
        cached = _cached(store, url)
        if cached:
            article["llm_summary"] = cached["summary"]
            article["sentiment"] = cached["sentiment"]
            attached += 1
            continue
        try:
            summary, sentiment = _fetch_summary(api_key, query, article)
        except (requests.Timeout, requests.RequestException) as exc:
            log_event(
                logging.WARNING,
                "summary",
                outcome="error",
                error=exc.__class__.__name__,
            )
            break
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            log_event(
                logging.WARNING,
                "summary",
                outcome="error",
                error=exc.__class__.__name__,
            )
            continue
        _store(store, url, summary, sentiment)
        article["llm_summary"] = summary
        article["sentiment"] = sentiment
        attached += 1
    return articles


def parse_summary_text(text):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("summary payload")
    summary = str(data.get("summary") or "").strip()
    sentiment = str(data.get("sentiment") or "").strip().lower()
    if not summary:
        raise ValueError("empty summary")
    if sentiment not in _SENTIMENTS:
        raise ValueError("sentiment")
    return summary, sentiment


def _fetch_summary(api_key, query, article):
    excerpt = article.get("summary") or article.get("description") or ""
    prompt = (
        "Summarize this headline for an equity analyst in two or three sentences. "
        'Reply with JSON only: {"summary": "...", "sentiment": "positive"|"neutral"|"negative"}. '
        f"Query: {query}\n"
        f"Title: {article.get('title') or ''}\n"
        f"Source: {article.get('source') or ''}\n"
        f"Excerpt: {str(excerpt)[:500]}"
    )
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("SUMMARY_MODEL", "claude-3-5-haiku-latest"),
            "max_tokens": 220,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        log_event(
            logging.WARNING,
            "summary",
            outcome="error",
            status=response.status_code,
        )
        raise requests.RequestException(f"HTTP {response.status_code}")
    payload = response.json()
    blocks = payload.get("content") or []
    text = ""
    for block in blocks:
        if isinstance(block, dict) and block.get("type", "text") == "text":
            text += block.get("text") or ""
    return parse_summary_text(text)


def _cached(store, url):
    getter = getattr(store, "get_summary", None)
    if getter is None:
        return None
    try:
        return getter(url)
    except Exception as exc:
        log_event(logging.WARNING, "summary", outcome="cache_read", error=exc.__class__.__name__)
        return None


def _store(store, url, summary, sentiment):
    setter = getattr(store, "put_summary", None)
    if setter is None:
        return
    try:
        setter(url, summary, sentiment)
    except Exception as exc:
        log_event(logging.WARNING, "summary", outcome="cache_write", error=exc.__class__.__name__)
