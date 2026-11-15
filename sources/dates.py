"""Date parsing kept from the original fetcher so headline order stays stable."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


def to_iso(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rss_date(date_str):
    if not date_str:
        return datetime.now()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.now()


def parse_date(date_str):
    if not date_str:
        return datetime.now()
    date_str = date_str.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue

    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }
    patterns = [
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,\s*(\d{4}),\s*(\d{1,2}):(\d{2})(AM|PM)\s*IST",
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
        r"(\d{1,2})/(\d{1,2})/(\d{4})",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s*(\d{4})",
        r"(\d+)\s+(day|days|hour|hours|minute|minutes|week|weeks|month|months|year|years)\s+ago",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, date_str, re.IGNORECASE)
        if not match:
            continue
        groups = match.groups()
        try:
            if index == 0:
                day, month, year, hour, minute, ampm = groups
                hour = int(hour)
                if ampm.upper() == "PM" and hour < 12:
                    hour += 12
                elif ampm.upper() == "AM" and hour == 12:
                    hour = 0
                return datetime(int(year), month_map[month], int(day), hour, int(minute))
            if index == 1:
                day, month, year = groups
                return datetime(int(year), month_map[month], int(day))
            if index == 2:
                day, month, year = groups
                return datetime(int(year), int(month), int(day))
            if index == 3:
                year, month, day = groups
                return datetime(int(year), int(month), int(day))
            if index == 4:
                month, day, year = groups
                return datetime(int(year), month_map[month], int(day))
            amount, unit = groups
            amount = int(amount)
            if unit.startswith("day"):
                return datetime.now() - timedelta(days=amount)
            if unit.startswith("hour"):
                return datetime.now() - timedelta(hours=amount)
            if unit.startswith("minute"):
                return datetime.now() - timedelta(minutes=amount)
            if unit.startswith("week"):
                return datetime.now() - timedelta(weeks=amount)
            if unit.startswith("month"):
                return datetime.now() - timedelta(days=amount * 30)
            if unit.startswith("year"):
                return datetime.now() - timedelta(days=amount * 365)
        except (KeyError, ValueError):
            continue

    lowered = date_str.lower()
    if "hour" in lowered or "hr" in lowered:
        hours = int(date_str[0]) if date_str[:1].isdigit() else 1
        return datetime.now() - timedelta(hours=hours)
    if "min" in lowered:
        minutes = int(date_str[0]) if date_str[:1].isdigit() else 5
        return datetime.now() - timedelta(minutes=minutes)
    if "yesterday" in lowered:
        return datetime.now() - timedelta(days=1)
    if "day" in lowered:
        days = 1
        for word in date_str.split():
            if word.isdigit():
                days = int(word)
                break
        return datetime.now() - timedelta(days=days)
    return datetime.now()
