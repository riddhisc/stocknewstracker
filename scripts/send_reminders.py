"""Email a reminder when a watchlist result date is exactly N days away.

Local default is a dry run (prints the message, sends nothing, records nothing):

    python scripts/send_reminders.py
    python scripts/send_reminders.py --days 10,5

GitHub Actions passes --send. Credentials are SMTP_USER, SMTP_PASS, and
NOTIFY_EMAIL. If any of those are missing, the script prints a skip line and
exits 0 so a data commit can still happen.

--test sends one test email when those three variables are set, and does not
write data/reminders_sent.json. Optional Telegram is used only when both
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set. Secret values are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "data" / "results.json"
SENT_PATH = ROOT / "data" / "reminders_sent.json"
IST = ZoneInfo("Asia/Kolkata")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


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


def parse_days(raw):
    days = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        days.append(int(part))
    return days or [10, 5]


def smtp_config():
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    recipient = os.environ.get("NOTIFY_EMAIL", "").strip()
    if user and password and recipient:
        return user, password, recipient
    return None


def telegram_config():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    if token or chat_id:
        print("Skipping Telegram: both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    return None


def format_number(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def short_date(value):
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.strftime("%d %b %Y").lstrip("0")


def sent_key(symbol, result_date, days):
    return f"{symbol}|{result_date}|{days}"


def already_sent(document):
    found = set()
    for item in document.get("sent") or []:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        result_date = item.get("date")
        days = item.get("days")
        if symbol and result_date and days is not None:
            found.add(sent_key(symbol, result_date, int(days)))
    return found


def message_for(symbol, block, days):
    nxt = block.get("next_result") or {}
    result_date = nxt.get("date")
    period = nxt.get("period")
    when = short_date(result_date)
    period_bit = f"{period} on {when}" if period else f"on {when}"
    subject = f"[Results in {days} days] {symbol} - {period_bit}"
    lines = [
        f"{symbol} reports in {days} days.",
        f"Date: {when}",
    ]
    if period:
        lines.append(f"Period: {period}")
    source = nxt.get("source_url") or block.get("source_url")
    if source:
        lines.append(f"Source: {source}")
    if block.get("stale"):
        lines.append("Stored figures are marked stale because a later refresh did not replace them.")
    quarters = block.get("quarters") or []
    if quarters and isinstance(quarters[0], dict):
        last = quarters[0]
        lines.append("")
        lines.append(
            f"Last reported quarter: {last.get('period') or 'n/a'} "
            f"(period end {last.get('period_end') or 'n/a'})"
        )
        unit = block.get("unit") or "as reported, not converted"
        lines.append(f"Units: {unit}")
        for label, field in (("Revenue", "revenue"), ("Net profit", "net_profit"), ("EPS", "eps")):
            rendered = format_number(last.get(field))
            if rendered is None:
                continue
            extra = []
            yoy = last.get(f"{field}_yoy_pct")
            qoq = last.get(f"{field}_qoq_pct")
            if yoy is not None:
                extra.append(f"YoY {yoy}%")
            if qoq is not None:
                extra.append(f"QoQ {qoq}%")
            suffix = f" ({', '.join(extra)})" if extra else ""
            lines.append(f"{label}: {rendered}{suffix}")
    else:
        lines.append("")
        lines.append("No quarterly figures are on file.")
    return subject, "\n".join(lines) + "\n"


def send_email(user, password, recipient, subject, body):
    message = EmailMessage()
    message["From"] = user
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(message)


def send_telegram(token, chat_id, text):
    import requests

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000]},
        timeout=20,
    )
    response.raise_for_status()


def deliver(subject, body, dry_run):
    print(subject)
    print(body)
    if dry_run:
        print("Dry run: not sent, not recorded.")
        return False
    config = smtp_config()
    if config is None:
        print("Skipping send: SMTP_USER, SMTP_PASS, or NOTIFY_EMAIL is not set")
        return False
    user, password, recipient = config
    send_email(user, password, recipient, subject, body)
    print(f"Email sent for subject: {subject}")
    telegram = telegram_config()
    if telegram is not None:
        token, chat_id = telegram
        try:
            send_telegram(token, chat_id, f"{subject}\n\n{body}")
            print("Telegram message sent")
        except Exception as exc:  # noqa: BLE001 - email already went out
            print(f"Telegram failed: {exc.__class__.__name__}")
    return True


def due_reminders(results, thresholds, today):
    due = []
    if not isinstance(results, dict):
        return due
    for symbol, block in results.items():
        if not isinstance(block, dict):
            continue
        result_date = (block.get("next_result") or {}).get("date")
        if not result_date:
            continue
        try:
            parsed = datetime.strptime(result_date, "%Y-%m-%d").date()
        except ValueError:
            print(f"{symbol}: skipping unreadable result date")
            continue
        days_away = (parsed - today).days
        if days_away in thresholds:
            due.append((str(symbol).upper(), result_date, days_away, block))
    return due


def run_test():
    print("Test reminder mode")
    if smtp_config() is None:
        print("Skipping send: SMTP_USER, SMTP_PASS, or NOTIFY_EMAIL is not set")
        return 0
    results = load_json(RESULTS_PATH, {})
    sample = None
    if isinstance(results, dict):
        for symbol, block in results.items():
            if isinstance(block, dict) and (block.get("next_result") or {}).get("date"):
                sample = (symbol, block)
                break
    if sample is None:
        subject = "[Results reminder test] stock tracker"
        body = (
            "This is a workflow_dispatch test from the stock tracker.\n"
            "No result date is on file, so this message has no figures.\n"
        )
    else:
        symbol, block = sample
        result_date = block["next_result"]["date"]
        days_away = (
            datetime.strptime(result_date, "%Y-%m-%d").date() - datetime.now(IST).date()
        ).days
        _ignored, body = message_for(symbol, block, days_away)
        subject = f"[Results reminder test] {symbol} on {short_date(result_date)}"
        body = "This is a workflow_dispatch test. Figures below are from the saved file only.\n\n" + body
    try:
        deliver(subject, body, dry_run=False)
    except Exception as exc:  # noqa: BLE001 - leave a non-zero exit only for unexpected send errors
        print(f"Test reminder failed: {exc.__class__.__name__}")
        return 1
    print("Test reminder was not added to data/reminders_sent.json")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send result-date reminders")
    parser.add_argument("--send", action="store_true", help="Send mail when SMTP env vars are set")
    parser.add_argument("--dry-run", action="store_true", help="Print only. This is the default.")
    parser.add_argument("--test", action="store_true", help="Send one test message if SMTP is configured")
    parser.add_argument("--days", default=os.environ.get("REMINDER_DAYS", "10,5"), help="Comma-separated day thresholds")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.test:
        return run_test()

    thresholds = parse_days(args.days)
    dry_run = not args.send
    if args.send and smtp_config() is None:
        print("Skipping send: SMTP_USER, SMTP_PASS, or NOTIFY_EMAIL is not set")
        dry_run = True
    elif dry_run:
        print(f"Dry run. Thresholds: {thresholds}. No email will be sent.")
    results = load_json(RESULTS_PATH, None)
    if not isinstance(results, dict):
        print("No data/results.json yet; nothing to remind.")
        return 0
    today = datetime.now(IST).date()
    sent_doc = load_json(SENT_PATH, {"sent": []})
    if not isinstance(sent_doc, dict):
        sent_doc = {"sent": []}
    sent_doc.setdefault("sent", [])
    seen = already_sent(sent_doc)
    due = due_reminders(results, set(thresholds), today)
    if not due:
        print("No reminders due today.")
        return 0

    wrote = False
    for symbol, result_date, days, block in due:
        key = sent_key(symbol, result_date, days)
        if key in seen:
            print(f"Already sent {symbol} for {result_date} at {days} days")
            continue
        subject, body = message_for(symbol, block, days)
        try:
            sent_now = deliver(subject, body, dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol}: send failed ({exc.__class__.__name__}); not recorded")
            continue
        if sent_now:
            sent_doc["sent"].append({
                "symbol": symbol,
                "date": result_date,
                "days": days,
                "sent_at": datetime.now(IST).isoformat(timespec="seconds"),
            })
            seen.add(key)
            wrote = True
    if wrote:
        write_json(SENT_PATH, sent_doc)
        print(f"Updated {SENT_PATH.name}")
    if not dry_run and smtp_config() is None:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
