"""News source adapters. One failed source must not blank the whole response."""

from sources.base import Article, NewsSource, SourceError
from sources.registry import build_sources

__all__ = ["Article", "NewsSource", "SourceError", "build_sources"]
