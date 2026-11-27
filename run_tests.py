#!/usr/bin/env python
"""
ONE COMMAND TO TEST THE WHOLE APPLICATION
=========================================
    python run_tests.py                 # everything (API + browser UI + unit)
    python run_tests.py --suite api     # only API tests      (fast)
    python run_tests.py --suite ui      # only browser tests
    python run_tests.py --suite unit    # only local unit tests
    python run_tests.py --suite repo    # your project's own existing tests/ folder
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
    "unit": [f"{E2E}/test_03_unit_local.py"],
    "all": [E2E],
    "repo": ["tests"],  # your project's own existing tests (uses its own pytest config)
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
              "pytest_timeout": "pytest-timeout", "requests": "requests",
              "pytest_base_url": "pytest-base-url"}
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


def build_command(args, extra):
    REPORTS.mkdir(exist_ok=True)
    if args.suite == "repo":
        return [sys.executable, "-m", "pytest", *SUITES["repo"],
                f"--junitxml={REPORTS / 'junit.xml'}"] + extra
    cmd = [sys.executable, "-m", "pytest", *SUITES[args.suite],
           "-c", f"{E2E}/pytest.ini", "--rootdir", E2E,
           f"--base-url={args.url}",
           f"--html={REPORTS / 'report.html'}", "--self-contained-html",
           f"--junitxml={REPORTS / 'junit.xml'}",
           "--screenshot=only-on-failure", "--tracing=retain-on-failure",
           f"--output={REPORTS / 'artifacts'}"]
    browsers = ["chromium", "firefox", "webkit"] if args.browser == "all" else [args.browser]
    for b in browsers:
        cmd += ["--browser", b]
    if args.headed:
        cmd.append("--headed")
    if args.slowmo:
        cmd += ["--slowmo", str(args.slowmo)]
    if args.destructive:
        cmd.append("--destructive")
    if args.quick:
        cmd += ["-m", "not slow"]
    return cmd + extra


def summarise(duration):
    xml_file = REPORTS / "junit.xml"
    if not xml_file.exists():
        print(f"{R}No results file was produced - pytest may have crashed before running.{X}")
        return
    root = ET.parse(xml_file).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
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
    p.add_argument("--no-install", action="store_true", help="skip dependency check")
    args, extra = p.parse_known_args()

    os.chdir(ROOT)
    banner("INDIAN STOCK NEWS TRACKER - AUTOMATED TEST SUITE")
    print(f"Target : {args.url}\nSuite  : {args.suite}   Browser: {args.browser}"
          f"   Headed: {args.headed}\nStarted: {time.strftime('%d %b %Y %H:%M:%S')}\n")

    if not args.no_install:
        ensure_dependencies()
    preflight(args.url)

    start = time.time()
    code = subprocess.call(build_command(args, extra))
    print()
    summarise(time.time() - start)
    sys.exit(code)


if __name__ == "__main__":
    main()
