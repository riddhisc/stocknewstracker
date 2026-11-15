"""Refresh quarterly results and the next result date for the watchlist.

Run from the repo root:

    python scripts/refresh_results.py
    python scripts/refresh_results.py --symbol RELIANCE --timeout 25

Primary source is Yahoo Finance via yfinance (SYMBOL.NS). If that call does not
return an upcoming date, the script tries the public NSE event calendar and
BSE scrip search / board-meeting endpoints. No API key is required.

Figures are stored only when the source returns them. A failed fetch keeps the
previous block for that symbol and sets stale to true. Nothing here is estimated.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WATCHLIST_PATH = DATA / "watchlist.json"
SYMBOLS_PATH = DATA / "symbols.json"
RESULTS_PATH = DATA / "results.json"
IST = ZoneInfo("Asia/Kolkata")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}

REVENUE_ROWS = ("Total Revenue", "Operating Revenue", "Total Revenues")
PROFIT_ROWS = (
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income Including Noncontrolling Interests",
)
EPS_ROWS = ("Diluted EPS", "Basic EPS")
RESULT_WORDS = ("result", "financial")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {path.name}: {exc}")
        return default


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def as_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(IST).date()
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nat", "none", "nan"}:
        return None
    for parser in (
        lambda raw: datetime.fromisoformat(raw.replace("Z", "+00:00")),
        lambda raw: datetime.strptime(raw[:10], "%Y-%m-%d"),
        lambda raw: datetime.strptime(raw, "%d %b %Y"),
        lambda raw: datetime.strptime(raw, "%d-%b-%Y"),
        lambda raw: datetime.strptime(raw, "%d/%m/%Y"),
    ):
        try:
            parsed = parser(text)
        except ValueError:
            continue
        if isinstance(parsed, datetime) and parsed.tzinfo is not None:
            return parsed.astimezone(IST).date()
        return parsed.date() if isinstance(parsed, datetime) else parsed
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def pct_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def add_quarter(period_end):
    month_index = period_end.month - 1 + 3
    year = period_end.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    return first_of_next - timedelta(days=1)


def fy_period(period_end):
    """Indian fiscal label from a quarter-end date. FY27 ends March 2027."""
    if period_end.month <= 3:
        quarter, fy_year = "Q4", period_end.year
    elif period_end.month <= 6:
        quarter, fy_year = "Q1", period_end.year + 1
    elif period_end.month <= 9:
        quarter, fy_year = "Q2", period_end.year + 1
    else:
        quarter, fy_year = "Q3", period_end.year + 1
    return f"{quarter} FY{fy_year % 100:02d}"


def call_with_timeout(func, timeout):
    box = {}

    def run():
        try:
            box["value"] = func()
        except Exception as exc:  # noqa: BLE001 - returned to the caller
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"timed out after {timeout:.0f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def request_json(url, timeout, headers):
    delay = 1.0
    last_error = "request failed"
    for _attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200 and response.content:
                try:
                    return response.json()
                except ValueError:
                    return {"_text": response.text[:4000]}
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = exc.__class__.__name__
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(last_error)


def company_links(symbol, bse_code=None):
    links = {
        "yahoo": f"https://finance.yahoo.com/quote/{symbol}.NS/",
        "nse": f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}",
        "screener": f"https://www.screener.in/company/{symbol}/consolidated/",
    }
    if bse_code:
        links["bse"] = (
            "https://www.bseindia.com/corporates/ann.html?scrip="
            + str(bse_code)
        )
    return links


def row_series(frame, names):
    wanted = {name.lower() for name in names}
    for label in frame.index:
        if str(label).strip().lower() in wanted:
            row = frame.loc[label]
            if hasattr(row, "columns"):
                row = row.iloc[0]
            return row
    return None


def quarters_from_frame(frame):
    columns = []
    for column in frame.columns:
        parsed = to_date(column)
        if parsed is not None:
            columns.append((parsed, column))
    columns.sort(key=lambda item: item[0], reverse=True)
    columns = columns[:8]
    if not columns:
        return []

    revenue = row_series(frame, REVENUE_ROWS)
    profit = row_series(frame, PROFIT_ROWS)
    eps = row_series(frame, EPS_ROWS)

    raw = []
    for period_end, column in columns:
        raw.append({
            "period_end": period_end.isoformat(),
            "period": fy_period(period_end),
            "revenue": as_float(revenue[column]) if revenue is not None else None,
            "net_profit": as_float(profit[column]) if profit is not None else None,
            "eps": as_float(eps[column]) if eps is not None else None,
        })

    def prior(index, low_days, high_days):
        current = date.fromisoformat(raw[index]["period_end"])
        match = None
        for older in raw[index + 1:]:
            gap = (current - date.fromisoformat(older["period_end"])).days
            if low_days <= gap <= high_days:
                match = older
                break
        return match

    quarters = []
    for index, quarter in enumerate(raw):
        # Compare only when the source actually has the adjacent quarter.
        # A missing column (Yahoo sometimes skips one) stays null.
        previous = prior(index, 80, 110)
        year_ago = prior(index, 350, 380)
        quarter = dict(quarter)
        for field in ("revenue", "net_profit", "eps"):
            quarter[f"{field}_qoq_pct"] = pct_change(
                quarter[field], previous[field] if previous else None
            )
            quarter[f"{field}_yoy_pct"] = pct_change(
                quarter[field], year_ago[field] if year_ago else None
            )
        quarters.append(quarter)
    return quarters


def upcoming_from_yfinance(ticker, today):
    candidates = []
    frame = None
    try:
        frame = ticker.earnings_dates
    except Exception as exc:
        print(f"  earnings dates unavailable: {exc.__class__.__name__}")
    if frame is not None and not getattr(frame, "empty", True):
        for label in list(frame.index):
            parsed = to_date(label)
            if parsed is not None and parsed >= today:
                candidates.append(parsed)
    if candidates:
        return min(candidates)
    try:
        calendar = ticker.calendar
    except Exception:
        calendar = None
    raw_dates = []
    if isinstance(calendar, dict):
        raw_dates = calendar.get("Earnings Date") or calendar.get("earnings_date") or []
    if not isinstance(raw_dates, (list, tuple)):
        raw_dates = [raw_dates]
    for item in raw_dates:
        parsed = to_date(item)
        if parsed is not None and parsed >= today:
            candidates.append(parsed)
    return min(candidates) if candidates else None


def fetch_yfinance(symbol, timeout, today):
    import yfinance as yf

    def load():
        ticker = yf.Ticker(f"{symbol}.NS")
        frame = ticker.quarterly_income_stmt
        if frame is None or getattr(frame, "empty", True):
            getter = getattr(ticker, "get_income_stmt", None)
            frame = getter(freq="quarterly") if getter else frame
        earnings_date = upcoming_from_yfinance(ticker, today)
        return frame, earnings_date

    frame, earnings_date = call_with_timeout(load, timeout)
    quarters = quarters_from_frame(frame) if frame is not None and not getattr(frame, "empty", True) else []
    return quarters, earnings_date


def walk_records(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from walk_records(item)
    elif isinstance(payload, dict):
        yield payload
        for value in payload.values():
            if isinstance(value, (list, dict)):
                yield from walk_records(value)


def bse_code_for(symbol, timeout):
    url = f"https://api.bseindia.com/BseIndiaAPI/api/SuggestScrip/w?flag=Equity&val={symbol}"
    try:
        payload = request_json(url, timeout, BROWSER_HEADERS)
    except RuntimeError as exc:
        print(f"  BSE scrip search failed: {exc}")
        return None
    for record in walk_records(payload):
        code = record.get("scrip_cd") or record.get("scripcode") or record.get("Scripcode")
        name = str(record.get("scrip_name") or record.get("Scrip_Name") or "").upper()
        if code and name == symbol:
            return str(code)
    text = payload.get("_text", "") if isinstance(payload, dict) else ""
    for match in re.finditer(r"(\d{6})", text):
        if symbol in text.upper():
            return match.group(1)
    return None


def date_from_announcement_records(payload, today):
    found = []
    for record in walk_records(payload):
        purpose = " ".join(
            str(record.get(key) or "")
            for key in ("Purpose", "purpose", "Agenda", "Headline", "NEWSSUB", "News_Sub")
        ).lower()
        if not any(word in purpose for word in RESULT_WORDS):
            continue
        for key in ("MEETING_DATE", "MeetingDate", "NEWS_DT", "News_Dt", "DissemDT", "date", "Date"):
            parsed = to_date(record.get(key))
            if parsed is not None and parsed >= today:
                found.append(parsed)
                break
    return min(found) if found else None


def fetch_bse_date(symbol, timeout, today):
    code = bse_code_for(symbol, timeout)
    if not code:
        return None, None
    start = (today - timedelta(days=7)).strftime("%Y%m%d")
    end = (today + timedelta(days=120)).strftime("%Y%m%d")
    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/CorpboardMeeting/w"
        f"?pageno=1&strCat=-1&strPrevDate={start}&strScrip={code}"
        f"&strSearch=P&strToDate={end}&strType=C"
    )
    try:
        payload = request_json(url, timeout, BROWSER_HEADERS)
    except RuntimeError as exc:
        print(f"  BSE board meetings failed: {exc}")
        return code, None
    return code, date_from_announcement_records(payload, today)


def fetch_nse_date(symbol, timeout, today):
    session = requests.Session()
    session.headers.update({
        **BROWSER_HEADERS,
        "Referer": "https://www.nseindia.com/",
        "Accept": "application/json,text/plain,*/*",
    })
    delay = 1.0
    for _attempt in range(3):
        try:
            session.get("https://www.nseindia.com/", timeout=timeout)
            response = session.get(
                "https://www.nseindia.com/api/event-calendar",
                params={"index": "equities", "symbol": symbol},
                timeout=timeout,
            )
            if response.status_code == 200:
                found = []
                for record in walk_records(response.json()):
                    purpose = str(record.get("purpose") or record.get("event") or "").lower()
                    if not any(word in purpose for word in RESULT_WORDS):
                        continue
                    parsed = to_date(record.get("date") or record.get("bm_timestamp"))
                    if parsed is not None and parsed >= today:
                        found.append(parsed)
                return min(found) if found else None
            print(f"  NSE calendar HTTP {response.status_code}")
        except (requests.RequestException, ValueError) as exc:
            print(f"  NSE calendar failed: {exc.__class__.__name__}")
        time.sleep(delay)
        delay *= 2
    return None


def next_result_block(symbol, earnings_date, latest_period_end, source_url):
    period = None
    if earnings_date is not None and latest_period_end is not None:
        inferred_end = add_quarter(latest_period_end)
        earliest = inferred_end - timedelta(days=10)
        latest = inferred_end + timedelta(days=150)
        if earliest <= earnings_date <= latest:
            period = fy_period(inferred_end)
    return {
        "date": earnings_date.isoformat() if earnings_date else None,
        "period": period,
        "source_url": source_url,
    }


def empty_block(symbol, now, stale):
    links = company_links(symbol)
    return {
        "next_result": {"date": None, "period": None, "source_url": links["screener"]},
        "quarters": [],
        "updated_at": now,
        "stale": stale,
        "source_url": links["screener"],
        "links": links,
    }


def refresh_symbol(symbol, previous, timeout, today, now):
    links = company_links(symbol)
    quarters = []
    earnings_date = None
    yahoo_error = None
    try:
        quarters, earnings_date = fetch_yfinance(symbol, timeout, today)
    except Exception as exc:
        yahoo_error = f"{exc.__class__.__name__}: {exc}"
        print(f"  Yahoo Finance failed: {yahoo_error}")

    date_source = "yahoo" if earnings_date is not None else None
    if earnings_date is None:
        nse_date = fetch_nse_date(symbol, min(timeout, 12), today)
        if nse_date is not None:
            earnings_date = nse_date
            date_source = "nse"
            links["nse_calendar"] = (
                "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"
            )
    if earnings_date is None:
        bse_code, bse_date = fetch_bse_date(symbol, min(timeout, 12), today)
        if bse_code:
            links["bse"] = company_links(symbol, bse_code)["bse"]
        if bse_date is not None:
            earnings_date = bse_date
            date_source = "bse"

    if date_source == "bse" and links.get("bse"):
        source_url = links["bse"]
    elif date_source == "nse":
        source_url = links["nse"]
    elif date_source == "yahoo":
        source_url = links["yahoo"]
    else:
        source_url = links["screener"]

    latest_end = to_date(quarters[0]["period_end"]) if quarters else None
    if not quarters:
        if isinstance(previous, dict) and previous.get("quarters"):
            kept = json.loads(json.dumps(previous))
            kept["stale"] = True
            if earnings_date is not None:
                previous_end = None
                old_quarters = kept.get("quarters") or []
                if old_quarters:
                    previous_end = to_date(old_quarters[0].get("period_end"))
                kept["next_result"] = next_result_block(
                    symbol, earnings_date, previous_end, source_url
                )
            kept["links"] = links
            print("  kept previous quarters and marked stale")
            return kept
        block = empty_block(symbol, now, True)
        block["links"] = links
        block["next_result"] = next_result_block(symbol, earnings_date, None, source_url)
        if yahoo_error:
            block["error"] = yahoo_error[:300]
        return block

    return {
        "next_result": next_result_block(symbol, earnings_date, latest_end, links["yahoo"]),
        "quarters": quarters,
        "updated_at": now,
        "stale": False,
        "source_url": links["yahoo"],
        "links": links,
        "unit": "as reported by Yahoo Finance for the .NS ticker; not converted",
    }


def known_symbols():
    payload = load_json(SYMBOLS_PATH, [])
    found = set()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("symbol"):
                found.add(str(item["symbol"]).upper())
    return found


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Refresh watchlist results into data/results.json")
    parser.add_argument("--symbol", action="append", help="NSE symbol to refresh. Repeat to add more.")
    parser.add_argument("--timeout", type=float, default=40, help="Seconds allowed for each source call")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    watchlist = load_json(WATCHLIST_PATH, [])
    if not isinstance(watchlist, list) or not watchlist:
        print(f"No watchlist at {WATCHLIST_PATH}")
        return 1
    selected = {item.upper() for item in args.symbol} if args.symbol else None
    listed = known_symbols()
    previous = load_json(RESULTS_PATH, {})
    if not isinstance(previous, dict):
        previous = {}
    today = datetime.now(IST).date()
    now = datetime.now(IST).isoformat(timespec="seconds")
    results = dict(previous)

    for item in watchlist:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or (selected is not None and symbol not in selected):
            continue
        if listed and symbol not in listed:
            print(f"{symbol}: not in data/symbols.json, skipping")
            continue
        print(f"{symbol}: fetching")
        results[symbol] = refresh_symbol(
            symbol,
            previous.get(symbol),
            args.timeout,
            today,
            now,
        )
        block = results[symbol]
        next_date = (block.get("next_result") or {}).get("date")
        print(
            f"{symbol}: quarters={len(block.get('quarters') or [])} "
            f"next={next_date} stale={block.get('stale')}"
        )

    write_json(RESULTS_PATH, results)
    print(f"Wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
