"""Load config.yaml and reject it with the field name when a value is wrong.

config.yaml is the news desk: tickers, aliases, sources, and cache TTL.
data/watchlist.json is a different file. scripts/refresh_results.py and
scripts/send_reminders.py read that JSON for quarterly results. This loader
does not open it.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from sources.registry import SOURCE_CLASSES

KNOWN_SOURCES = tuple(cls.name for cls in SOURCE_CLASSES)
_TOP_FIELDS = {"cache_ttl_seconds", "indices", "watchlist", "sources"}
_INDEX_FIELDS = {"id", "label"}
_WATCH_FIELDS = {"name", "ticker", "aliases"}
_SOURCE_FIELDS = {"name", "enabled", "priority", "timeout"}


class ConfigError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(f"{field}: {message}")


class AppConfig:
    def __init__(self, cache_ttl_seconds, indices, watchlist, sources, alias_map):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.indices = indices
        self.watchlist = watchlist
        self.sources = sources
        self.source_settings = {item["name"]: item for item in sources}
        self.alias_map = alias_map


def load_config(path=None):
    raw_path = path or os.environ.get("CONFIG_PATH") or "config.yaml"
    config_path = Path(raw_path)
    if not config_path.is_file():
        raise ConfigError("config", f"file not found: {config_path}")
    try:
        text = config_path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
    except OSError as exc:
        raise ConfigError("config", f"could not read file: {exc.__class__.__name__}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError("config", "invalid YAML") from exc
    return validate_config(loaded)


def validate_config(loaded):
    if not isinstance(loaded, dict):
        raise ConfigError("config", "expected a mapping at the top level")
    unknown = sorted(set(loaded) - _TOP_FIELDS)
    if unknown:
        raise ConfigError(unknown[0], "unknown field")
    for name in ("cache_ttl_seconds", "indices", "watchlist", "sources"):
        if name not in loaded:
            raise ConfigError(name, "field is required")

    cache_ttl = _positive_number("cache_ttl_seconds", loaded["cache_ttl_seconds"])
    indices = _indices(loaded["indices"])
    watchlist = _watchlist(loaded["watchlist"])
    sources = _sources(loaded["sources"])
    return AppConfig(
        cache_ttl_seconds=int(cache_ttl),
        indices=indices,
        watchlist=watchlist,
        sources=sources,
        alias_map=_alias_map(watchlist),
    )


def _positive_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(field, "expected a number greater than 0")
    if value <= 0:
        raise ConfigError(field, "expected a number greater than 0")
    return value


def _text(field, value):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(field, "expected a non-empty string")
    return value.strip()


def _indices(value):
    if not isinstance(value, list):
        raise ConfigError("indices", "expected a list")
    indices = []
    seen = set()
    for index, item in enumerate(value):
        field = f"indices[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "expected a mapping with id and label")
        unknown = sorted(set(item) - _INDEX_FIELDS)
        if unknown:
            raise ConfigError(f"{field}.{unknown[0]}", "unknown field")
        if "id" not in item:
            raise ConfigError(f"{field}.id", "field is required")
        if "label" not in item:
            raise ConfigError(f"{field}.label", "field is required")
        item_id = _text(f"{field}.id", item["id"])
        label = _text(f"{field}.label", item["label"])
        if item_id.upper() in seen:
            raise ConfigError(f"{field}.id", f"duplicate index {item_id}")
        seen.add(item_id.upper())
        indices.append({"id": item_id, "label": label})
    return indices


def _watchlist(value):
    if not isinstance(value, list):
        raise ConfigError("watchlist", "expected a list")
    rows = []
    seen = set()
    for index, item in enumerate(value):
        field = f"watchlist[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "expected a mapping with name and ticker")
        unknown = sorted(set(item) - _WATCH_FIELDS)
        if unknown:
            raise ConfigError(f"{field}.{unknown[0]}", "unknown field")
        if "name" not in item:
            raise ConfigError(f"{field}.name", "field is required")
        if "ticker" not in item:
            raise ConfigError(f"{field}.ticker", "field is required")
        name = _text(f"{field}.name", item["name"])
        ticker = _text(f"{field}.ticker", item["ticker"])
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list):
            raise ConfigError(f"{field}.aliases", "expected a list of strings")
        clean_aliases = []
        for alias_index, alias in enumerate(aliases):
            clean_aliases.append(_text(f"{field}.aliases[{alias_index}]", alias))
        marker = ticker.upper()
        if marker in seen:
            raise ConfigError(f"{field}.ticker", f"duplicate ticker {ticker}")
        seen.add(marker)
        rows.append({"name": name, "ticker": ticker, "aliases": clean_aliases})
    return rows


def _sources(value):
    if not isinstance(value, list) or not value:
        raise ConfigError("sources", "expected a non-empty list")
    rows = []
    seen = set()
    for index, item in enumerate(value):
        field = f"sources[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(field, "expected a mapping")
        unknown = sorted(set(item) - _SOURCE_FIELDS)
        if unknown:
            raise ConfigError(f"{field}.{unknown[0]}", "unknown field")
        for key in _SOURCE_FIELDS:
            if key not in item:
                raise ConfigError(f"{field}.{key}", "field is required")
        name = _text(f"{field}.name", item["name"])
        if name not in KNOWN_SOURCES:
            known = ", ".join(KNOWN_SOURCES)
            raise ConfigError(f"{field}.name", f"unknown source {name}. Expected one of: {known}")
        if name in seen:
            raise ConfigError(f"{field}.name", f"duplicate source {name}")
        seen.add(name)
        enabled = item["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigError(f"{field}.enabled", "expected true or false")
        priority = item["priority"]
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ConfigError(f"{field}.priority", "expected an integer")
        timeout = _positive_number(f"{field}.timeout", item["timeout"])
        rows.append({
            "name": name,
            "enabled": enabled,
            "priority": priority,
            "timeout": timeout,
        })
    return rows


def _alias_map(watchlist):
    mapping = {}
    for item in watchlist:
        names = [item["name"], item["ticker"], *item["aliases"]]
        for name in names:
            mapping[name.lower()] = names
    return mapping
