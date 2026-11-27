#!/usr/bin/env python
"""
ONE COMMAND TO TEST THE WHOLE APPLICATION
=========================================
    python run_tests.py                 # everything (API + browser UI + your own unit tests)
    python run_tests.py --suite api     # only API tests      (fast)
    python run_tests.py --suite ui      # only browser tests
    python run_tests.py --suite e2e     # API + browser tests (the live-site checks)
    python run_tests.py --suite unit    # your project's own existing tests/ folder (offline)
    python run_tests.py --channel chrome  # force the installed Google Chrome for browser tests
    python run_tests.py --headed        # watch the browser click through the site
    python run_tests.py --headed --slowmo 400
    python run_tests.py --browser all   # Chromium + Firefox + WebKit
    python run_tests.py --quick         # skip slow load tests
    python run_tests.py --url http://127.0.0.1:5000   # test a local copy
    python run_tests.py --destructive   # also test 'Clear History' (wipes history!)

It installs missing test dependencies, checks the site is reachable, runs the
tests, and prints a detailed report (also saved to reports/report.html).
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DEFAULT_URL = "https://ridz111.pythonanywhere.com"
E2E = "e2e_tests"
SUITES = {
    "api": [f"{E2E}/test_01_api.py"],
    "ui": [f"{E2E}/test_02_ui.py"],
    "e2e": [E2E],
    "unit": ["tests"],   # your project's own existing tests (use their own pytest config)
    "repo": ["tests"],   # alias of unit
    "all": [E2E, "tests"],
}

os.system("")  # enables ANSI colours in Windows CMD
G, R, Y, C, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"


def line(char="=", n=78):
    print(char * n)


def banner(text, colour=C):
    line()
    print(f"{colour}{B}{text}{X}")
    line()


def ensure_dependencies():
    needed = {"pytest": "pytest", "playwright": "playwright", "pytest_html": "pytest-html",
              "pytest_timeout": "pytest-timeout", "requests": "requests"}
    missing = [m for m in needed if importlib.util.find_spec(m) is None]
    if missing:
        print(f"{Y}Installing missing test dependencies: {', '.join(missing)}{X}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r",
                               str(ROOT / "requirements-test.txt")])
    print("Making sure the Playwright browsers are installed (first run downloads ~150 MB)...")
    subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


def preflight(url):
    print(f"Pre-flight check: {url}")
    start = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TestSuite"}),
                                    timeout=60) as resp:
            print(f"  {G}reachable{X}  HTTP {resp.status} in {time.time() - start:.1f}s\n")
            return True
    except Exception as exc:
        print(f"  {R}NOT reachable: {exc}{X}")
        print("  (Tests will run anyway and report exactly what fails.)\n")
        return False


def pick_browser_channel(args):
    """Chromium that Playwright downloads is sometimes blocked on Windows
    (antivirus / admin shell -> 'spawn UNKNOWN'). Test-launch it; if that fails,
    try the Chrome / Edge that is already installed."""
    if args.channel:
        return args.channel
    if args.browser not in ("chromium",) or args.suite in ("unit", "repo"):
        return None
    probe = ("from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch({}); b.close()\n")
    print("Checking that a browser can start...")
    for channel in (None, "chrome", "msedge"):
        arg = f"channel='{channel}'" if channel else ""
        try:
            res = subprocess.run([sys.executable, "-c", probe.format(arg)],
                                 capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            continue
        if res.returncode == 0:
            label = channel or "Playwright Chromium"
            print(f"  {G}browser OK:{X} {label}\n")
            return channel
    print(f"  {R}No browser could be started{X} - browser tests will error.")
    print("  Try: open a NORMAL (non-admin) CMD, or run  python -m playwright install chromium --force\n")
    return None


def build_runs(args, extra, channel):
    REPORTS.mkdir(exist_ok=True)
    runs = []
    for target in ("e2e", "repo"):
        if target == "e2e" and not any(p.startswith(E2E) for p in SUITES[args.suite]):
            continue
        if target == "repo" and "tests" not in SUITES[args.suite]:
            continue
        if target == "repo":
            runs.append(dict(name="your project's own tests", junit=REPORTS / "junit_repo.xml",
                             cmd=[sys.executable, "-m", "pytest", "tests",
                                  f"--junitxml={REPORTS / 'junit_repo.xml'}"]))
            continue
        cmd = [sys.executable, "-m", "pytest", *[p for p in SUITES[args.suite] if p.startswith(E2E)],
               "-c", f"{E2E}/pytest.ini", "--rootdir", E2E,
               f"--base-url={args.url}",
               f"--html={REPORTS / 'report.html'}", "--self-contained-html",
               f"--junitxml={REPORTS / 'junit_e2e.xml'}",
               "--screenshot=only-on-failure", "--tracing=retain-on-failure",
               f"--output={REPORTS / 'artifacts'}"]
        browsers = ["chromium", "firefox", "webkit"] if args.browser == "all" else [args.browser]
        for b in browsers:
            cmd += ["--browser", b]
        if channel:
            cmd += ["--browser-channel", channel]
        if args.headed:
            cmd.append("--headed")
        if args.slowmo:
            cmd += ["--slowmo", str(args.slowmo)]
        if args.destructive:
            cmd.append("--destructive")
        if args.quick:
            cmd += ["-m", "not slow"]
        runs.append(dict(name="live site: API + browser", junit=REPORTS / "junit_e2e.xml", cmd=cmd + extra))
    return runs


def summarise(duration, junit_files):
    junit_files = [f for f in junit_files if f.exists()]
    if not junit_files:
        print(f"{R}No results file was produced - pytest may have crashed before running.{X}")
        return
    suites = []
    for xml_file in junit_files:
        root = ET.parse(xml_file).getroot()
        suites += [root] if root.tag == "testsuite" else list(root)
    per_file = OrderedDict()
    slowest, failures, skipped = [], [], []
    totals = dict(passed=0, failed=0, skipped=0)

    for suite in suites:
        for case in suite.iter("testcase"):
            parts = case.get("classname", "").split(".")
            module = next((x for x in parts if x.startswith("test_")), parts[0] or "?")
            stats = per_file.setdefault(module, dict(passed=0, failed=0, skipped=0, time=0.0))
            t = float(case.get("time", 0))
            stats["time"] += t
            slowest.append((t, f"{case.get('classname', '').split('.')[-1]}::{case.get('name')}"))
            fail = case.find("failure") if case.find("failure") is not None else case.find("error")
            skip = case.find("skipped")
            if fail is not None:
                stats["failed"] += 1
                totals["failed"] += 1
                msg = (fail.get("message") or fail.text or "").strip().splitlines()
                failures.append((f"{case.get('classname', '').split('.')[-1]}::{case.get('name')}",
                                 msg[0][:160] if msg else ""))
            elif skip is not None:
                stats["skipped"] += 1
                totals["skipped"] += 1
                skipped.append((case.get("name"), (skip.get("message") or "")[:100]))
            else:
                stats["passed"] += 1
                totals["passed"] += 1

    total = sum(totals.values())
    banner("DETAILED TEST SUMMARY")
    print(f"{B}{'Test file':<28}{'Passed':>8}{'Failed':>8}{'Skipped':>9}{'Time':>10}{X}")
    line("-")
    for name, s in per_file.items():
        colour = R if s["failed"] else G
        print(f"{colour}{name:<28}{s['passed']:>8}{s['failed']:>8}{s['skipped']:>9}{s['time']:>9.1f}s{X}")
    line("-")
    print(f"{B}{'TOTAL':<28}{totals['passed']:>8}{totals['failed']:>8}{totals['skipped']:>9}"
          f"{duration:>9.1f}s{X}\n")

    print(f"{B}Slowest 5 tests{X}")
    for t, name in sorted(slowest, reverse=True)[:5]:
        print(f"  {t:6.1f}s  {name}")

    if skipped:
        print(f"\n{Y}{B}Skipped ({len(skipped)}){X}")
        for name, why in skipped:
            print(f"  - {name}: {why}")

    if failures:
        print(f"\n{R}{B}FAILED TESTS ({len(failures)}){X}")
        for name, why in failures:
            print(f"  {R}x{X} {name}\n      {why}")

    print()
    if totals["failed"] == 0 and total > 0:
        banner(f"RESULT: ALL {totals['passed']} TESTS PASSED - APPLICATION IS WORKING", G)
    else:
        banner(f"RESULT: {totals['failed']} OF {total} TESTS FAILED - SEE DETAILS ABOVE", R)
    print(f"HTML report : {REPORTS / 'report.html'}")
    print(f"Screenshots/traces of failures : {REPORTS / 'artifacts'}")


def main():
    p = argparse.ArgumentParser(description="Full test-suite for Indian Stock News Tracker")
    p.add_argument("--url", default=os.environ.get("BASE_URL", DEFAULT_URL))
    p.add_argument("--suite", choices=SUITES, default="all")
    p.add_argument("--browser", choices=["chromium", "firefox", "webkit", "all"], default="chromium")
    p.add_argument("--headed", action="store_true", help="show the browser window")
    p.add_argument("--slowmo", type=int, default=0, help="ms delay between browser actions")
    p.add_argument("--quick", action="store_true", help="skip slow load tests")
    p.add_argument("--destructive", action="store_true", help="also test clearing ALL history")
    p.add_argument("--channel", choices=["chrome", "msedge"], help="use the installed Chrome/Edge for browser tests")
    p.add_argument("--no-install", action="store_true", help="skip dependency check")
    args, extra = p.parse_known_args()

    os.chdir(ROOT)
    banner("INDIAN STOCK NEWS TRACKER - AUTOMATED TEST SUITE")
    print(f"Target : {args.url}\nSuite  : {args.suite}   Browser: {args.browser}"
          f"   Headed: {args.headed}\nStarted: {time.strftime('%d %b %Y %H:%M:%S')}\n")

    if not args.no_install:
        ensure_dependencies()
    preflight(args.url)
    channel = pick_browser_channel(args) if args.suite in ("ui", "e2e", "all") else None

    start = time.time()
    code = 0
    runs = build_runs(args, extra, channel)
    for i, run in enumerate(runs, 1):
        banner(f"RUN {i}/{len(runs)}: {run['name']}", C)
        code = subprocess.call(run["cmd"]) or code
    print()
    summarise(time.time() - start, [r["junit"] for r in runs])
    sys.exit(code)


if __name__ == "__main__":
    main()
