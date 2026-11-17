"""Add and remove results-watchlist names without touching config.yaml.

The quarterly figures come from scripts/refresh_results.py. Yahoo Finance is
loaded in a separate interpreter when this process cannot import pandas.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_INTERPRETER = None
_SYMBOL = re.compile(r"^[A-Z0-9]{1,15}$")

_FETCH = r"""
import importlib.util, json, sys
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
symbol = sys.argv[2]
timeout = float(sys.argv[3])
spec = importlib.util.spec_from_file_location(
    "refresh_results", root / "scripts" / "refresh_results.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
previous = {}
if module.RESULTS_PATH.exists():
    try:
        saved = json.loads(module.RESULTS_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            previous = saved.get(symbol) or {}
    except (OSError, json.JSONDecodeError):
        previous = {}
stdout = sys.stdout
sys.stdout = sys.stderr
now = datetime.now(module.IST).isoformat(timespec="seconds")
today = datetime.now(module.IST).date()
block = module.refresh_symbol(symbol, previous or None, timeout, today, now)
stdout.write(json.dumps(block))
stdout.flush()
"""


def _script():
    path = Path(__file__).resolve().parent / "scripts" / "refresh_results.py"
    spec = importlib.util.spec_from_file_location("refresh_results", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _interpreter():
    global _INTERPRETER
    if _INTERPRETER:
        return _INTERPRETER
    chosen = os.environ.get("RESULTS_PYTHON") or ""
    candidates = [item for item in (chosen, str(Path(sys.base_prefix) / "python.exe"), sys.executable) if item]
    for command in candidates:
        try:
            probe = subprocess.run(
                [command, "-c", "import yfinance"],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            _INTERPRETER = command
            return command
    _INTERPRETER = sys.executable
    return _INTERPRETER


def _years(quarters, annual=None):
    found = []

    def add(label):
        if label and str(label).startswith("FY") and label not in found:
            found.append(label)

    for quarter in quarters or []:
        if not isinstance(quarter, dict):
            continue
        parts = str(quarter.get("period") or "").split()
        add(parts[-1] if parts else None)
    for row in annual or []:
        if isinstance(row, dict):
            add(row.get("period"))
    def sort_key(label):
        digits = "".join(ch for ch in label if ch.isdigit())
        return int(digits) if digits else 0
    return sorted(found, key=sort_key, reverse=True)


def _public_block(symbol, name, block):
    block = block if isinstance(block, dict) else {}
    nxt = block.get("next_result") if isinstance(block.get("next_result"), dict) else {}
    quarters = block.get("quarters") if isinstance(block.get("quarters"), list) else []
    annual = block.get("annual") if isinstance(block.get("annual"), list) else []
    return {
        "symbol": symbol,
        "name": name or symbol,
        "next_date": nxt.get("date"),
        "next_period": nxt.get("period"),
        "date_status": nxt.get("status") or ("estimated" if "finance.yahoo.com" in str(nxt.get("source_url") or block.get("source_url") or "") else "confirmed" if nxt.get("date") else None),
        "source_url": nxt.get("source_url") or block.get("source_url"),
        "updated_at": block.get("updated_at"),
        "stale": bool(block.get("stale")),
        "error": block.get("error"),
        "years": _years(quarters, annual),
        "quarters": quarters,
        "annual": annual,
        "annual_count": block.get("annual_count") if block.get("annual_count") is not None else len(annual),
        "annual_source": block.get("annual_source"),
    }


def list_board():
    module = _script()
    watch = module.load_json(module.WATCHLIST_PATH, [])
    saved = module.load_json(module.RESULTS_PATH, {})
    if not isinstance(watch, list):
        watch = []
    if not isinstance(saved, dict):
        saved = {}
    items = []
    for row in watch:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        items.append(_public_block(symbol, row.get("name") or symbol, saved.get(symbol)))
    return items


def add_symbol(symbol, name=None, timeout=30):
    symbol = str(symbol or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol")
    module = _script()
    if not name:
        catalog = module.load_json(module.SYMBOLS_PATH, [])
        if isinstance(catalog, list):
            for item in catalog:
                if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol:
                    name = item.get("name")
                    break
    name = (name or symbol).strip()
    with _LOCK:
        block = _fetch(module, symbol, timeout)
        watch = module.load_json(module.WATCHLIST_PATH, [])
        if not isinstance(watch, list):
            watch = []
        if not any(str(row.get("symbol") or "").upper() == symbol for row in watch if isinstance(row, dict)):
            watch.append({"symbol": symbol, "name": name})
            module.write_json(module.WATCHLIST_PATH, watch)
        saved = module.load_json(module.RESULTS_PATH, {})
        if not isinstance(saved, dict):
            saved = {}
        saved[symbol] = block
        module.write_json(module.RESULTS_PATH, saved)
    return _public_block(symbol, name, block)


def remove_symbol(symbol):
    symbol = str(symbol or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol")
    module = _script()
    with _LOCK:
        watch = module.load_json(module.WATCHLIST_PATH, [])
        if isinstance(watch, list):
            watch = [
                row for row in watch
                if not (isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol)
            ]
            module.write_json(module.WATCHLIST_PATH, watch)
        saved = module.load_json(module.RESULTS_PATH, {})
        if isinstance(saved, dict) and symbol in saved:
            saved.pop(symbol, None)
            module.write_json(module.RESULTS_PATH, saved)
    return {"symbol": symbol, "removed": True}


def _fetch(module, symbol, timeout):
    command = _interpreter()
    try:
        proc = subprocess.run(
            [command, "-c", _FETCH, str(module.ROOT), symbol, str(timeout)],
            capture_output=True,
            text=True,
            timeout=max(timeout + 45, 70),
            cwd=str(module.ROOT),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _failed(module, symbol, exc.__class__.__name__)
    except OSError as exc:
        return _failed(module, symbol, exc.__class__.__name__)
    if proc.returncode != 0 or not proc.stdout.strip():
        return _failed(module, symbol, "RuntimeError")
    try:
        block = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _failed(module, symbol, "JSONDecodeError")
    if not isinstance(block, dict):
        return _failed(module, symbol, "ValueError")
    return block


def _failed(module, symbol, error_name):
    saved = module.load_json(module.RESULTS_PATH, {})
    previous = saved.get(symbol) if isinstance(saved, dict) else None
    now = datetime.now(module.IST).isoformat(timespec="seconds")
    if isinstance(previous, dict) and previous.get("quarters"):
        kept = json.loads(json.dumps(previous))
        kept["stale"] = True
        kept["error"] = error_name
        kept["updated_at"] = previous.get("updated_at") or now
        return kept
    block = module.empty_block(symbol, now, True)
    block["error"] = error_name
    return block
