"""
LAYER 2 - END-TO-END UI TESTS (real browser via Playwright)

Opens the live site in a real Chromium/Firefox/WebKit browser and behaves like
a user: types in the search box, clicks Search / History / Status / Results /
filter buttons, checks headlines load, checks responsiveness, accessibility
basics and that no JavaScript errors or server errors happen.

Elements are found by VISIBLE TEXT / ROLE (not fragile CSS ids), so the tests
keep working when the HTML is tweaked.

Run only this layer:   python run_tests.py --suite ui
Watch it happen:       python run_tests.py --suite ui --headed --slowmo 400
"""
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

TERM = "RELIANCE"
FILTERS = ["All", "Expected this week", "Recently announced", "Date not announced"]
SEARCH_URL_PARTS = ("/search", "/api/news")


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def _timeouts(page):
    page.set_default_timeout(30_000)
    page.set_default_navigation_timeout(60_000)


@pytest.fixture
def watch(page, base_url):
    """Collects uncaught JS exceptions and same-site 5xx responses."""
    problems = {"js_errors": [], "server_errors": [], "dialogs": []}
    root = base_url.rstrip("/")

    page.on("pageerror", lambda e: problems["js_errors"].append(str(e)))
    page.on(
        "response",
        lambda r: problems["server_errors"].append(f"{r.status} {r.url}")
        if r.url.startswith(root) and r.status >= 500
        else None,
    )

    def _dialog(d):
        problems["dialogs"].append(d.message)
        d.dismiss()

    page.on("dialog", _dialog)
    return problems


@pytest.fixture
def home(page, watch):
    page.goto("/")
    page.wait_for_load_state("domcontentloaded")
    return page


def assert_healthy(problems):
    assert not problems["js_errors"], f"JavaScript errors: {problems['js_errors']}"
    assert not problems["server_errors"], f"Server errors: {problems['server_errors']}"


# --------------------------------------------------------------------------- helpers
def search_box(page):
    page.wait_for_selector("input", state="visible")
    candidates = (
        page.get_by_role("searchbox"),
        page.get_by_placeholder(re.compile("stock|index|symbol|search|nifty|reliance", re.I)),
        page.get_by_role("textbox"),
    )
    for loc in candidates:
        if loc.count():
            return loc.first
    pytest.fail("Could not find the search input on the page")


def search_button(page):
    return page.get_by_role("button", name=re.compile(r"^\s*search\s*$", re.I)).first


def is_news_response(r):
    u = r.url
    return (
        any(p in u for p in SEARCH_URL_PARTS)
        and "history" not in u
        and "cache-status" not in u
    )


def run_search(page, term=TERM, via_enter=False):
    box = search_box(page)
    box.fill(term)
    with page.expect_response(is_news_response, timeout=90_000) as info:
        if via_enter:
            box.press("Enter")
        else:
            search_button(page).click()
    return info.value


def clickable(page, name):
    """Find a control by its text whether it is a button, tab, link or plain text."""
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)
    for loc in (
        page.get_by_role("button", name=pattern),
        page.get_by_role("tab", name=pattern),
        page.get_by_role("link", name=pattern),
        page.get_by_text(pattern),
    ):
        if loc.count():
            return loc.first
    pytest.fail(f"Control '{name}' not found on the page")


# --------------------------------------------------------------------------- 1. page load
class TestPageLoad:
    def test_title_and_heading(self, home):
        expect(home).to_have_title(re.compile("Stock News Tracker", re.I))
        expect(home.get_by_role("heading", name=re.compile("Indian Stock News Tracker", re.I))).to_be_visible()

    def test_core_controls_are_visible(self, home):
        expect(search_box(home)).to_be_visible()
        expect(search_button(home)).to_be_visible()
        for name in ("History", "Status"):
            expect(clickable(home, name)).to_be_visible()
        expect(home.get_by_role("link", name=re.compile("results", re.I)).first).to_be_visible()

    def test_no_errors_on_load(self, home, watch):
        home.wait_for_load_state("networkidle")
        assert_healthy(watch)

    def test_page_loads_within_budget(self, home):
        ms = home.evaluate(
            "() => { const t = performance.timing; return t.domContentLoadedEventEnd - t.navigationStart; }"
        )
        assert ms < 10_000, f"DOMContentLoaded took {ms} ms"

    def test_reload_keeps_working(self, home):
        home.reload()
        expect(search_box(home)).to_be_visible()


# --------------------------------------------------------------------------- 2. market headlines
class TestMarketHeadlines:
    def test_headlines_finish_loading(self, home):
        """'Markets now' section: the spinner text must go away and no error shown."""
        loading = home.get_by_text(re.compile("Fetching headlines", re.I))
        if loading.count():
            expect(loading.first).to_be_hidden(timeout=60_000)
        expect(home.get_by_text(re.compile("Headlines didn.t load", re.I))).to_have_count(0)

    def test_headlines_are_real_links(self, home):
        home.wait_for_load_state("networkidle")
        links = home.locator("a[href^='http']:visible")
        assert links.count() >= 1, "no external headline links rendered"
        for i in range(min(links.count(), 10)):
            assert links.nth(i).get_attribute("href").startswith(("http://", "https://"))


# --------------------------------------------------------------------------- 3. searching
class TestSearch:
    def test_search_button_returns_news(self, home, watch):
        before = home.locator("body").inner_text()
        resp = run_search(home)
        assert resp.ok, f"search request failed: {resp.status}"
        body = resp.json()
        assert isinstance(body.get("news"), list) and body["news"], "no news returned"
        home.wait_for_timeout(1500)
        assert home.locator("body").inner_text() != before, "page did not change after search"
        assert home.locator("a[href^='http']:visible").count() >= 1
        assert_healthy(watch)

    def test_enter_key_triggers_search(self, home):
        resp = run_search(home, "TCS", via_enter=True)
        assert resp.ok

    @pytest.mark.parametrize("term", ["INFY", "HDFCBANK", "NIFTY 50"])
    def test_multiple_stocks(self, home, term):
        resp = run_search(home, term)
        assert resp.ok
        assert resp.json()["news"], f"no news for {term}"

    def test_empty_search_does_not_break_page(self, home, watch):
        search_box(home).fill("")
        search_button(home).click()
        home.wait_for_timeout(1500)
        expect(search_box(home)).to_be_visible()
        assert_healthy(watch)

    def test_script_injection_is_not_executed(self, home, watch):
        search_box(home).fill("<img src=x onerror=alert('xss')><script>alert('xss')</script>")
        search_button(home).click()
        home.wait_for_timeout(4000)
        assert watch["dialogs"] == [], f"XSS dialog executed: {watch['dialogs']}"
        assert_healthy(watch)

    def test_back_to_back_searches(self, home):
        for term in ("TCS", "INFY"):
            assert run_search(home, term).ok


# --------------------------------------------------------------------------- 4. history panel
class TestHistoryPanel:
    def test_history_panel_opens_and_closes(self, home):
        clickable(home, "History").click()
        expect(home.get_by_text(re.compile("Search History", re.I)).first).to_be_visible()
        clickable(home, "Close").click()
        expect(home.get_by_text(re.compile("Search History", re.I)).first).to_be_hidden()

    def test_search_appears_in_history(self, home):
        run_search(home, TERM)
        clickable(home, "History").click()
        expect(home.get_by_text(re.compile(TERM, re.I)).first).to_be_visible()

    def test_clear_history_button(self, home, destructive):
        if not destructive:
            pytest.skip("wipes shared history - run with --destructive to enable")
        clickable(home, "History").click()
        clickable(home, "Clear History").click()
        expect(home.get_by_text(re.compile("No search history", re.I))).to_be_visible()


# --------------------------------------------------------------------------- 5. status button
class TestStatus:
    def test_status_button_works(self, home, watch):
        clickable(home, "Status").click()
        home.wait_for_timeout(2000)
        expect(home.locator("body")).to_be_visible()
        assert_healthy(watch)


# --------------------------------------------------------------------------- 6. results page
class TestResultsPage:
    def test_navigate_to_results(self, home):
        home.get_by_role("link", name=re.compile("results", re.I)).first.click()
        expect(home).to_have_url(re.compile(r"/results/?$"))
        expect(home.get_by_text(re.compile("Upcoming results", re.I)).first).to_be_visible()

    @pytest.mark.parametrize("name", FILTERS)
    def test_filter_buttons(self, page, watch, name):
        page.goto("/results")
        control = clickable(page, name)
        expect(control).to_be_visible()
        control.click()
        page.wait_for_timeout(800)
        expect(page.locator("body")).to_be_visible()
        assert_healthy(watch)

    def test_browser_back_returns_home(self, home):
        home.get_by_role("link", name=re.compile("results", re.I)).first.click()
        expect(home).to_have_url(re.compile(r"/results"))
        home.go_back()
        expect(search_box(home)).to_be_visible()


# --------------------------------------------------------------------------- 7. responsive + accessibility
class TestResponsiveAndAccessibility:
    @pytest.mark.parametrize(
        "size", [(375, 667), (768, 1024), (1366, 768), (1920, 1080)],
        ids=["phone", "tablet", "laptop", "desktop"],
    )
    def test_no_horizontal_scroll(self, page, size):
        page.set_viewport_size({"width": size[0], "height": size[1]})
        page.goto("/")
        page.wait_for_load_state("networkidle")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"page overflows horizontally by {overflow}px at {size}"
        expect(search_box(page)).to_be_visible()

    def test_search_works_on_mobile_device(self, browser, browser_name, playwright, base_url):
        if browser_name == "firefox":
            pytest.skip("Firefox does not support mobile emulation")
        device = dict(playwright.devices["iPhone 12"])
        device.pop("default_browser_type", None)
        ctx = browser.new_context(**device, base_url=base_url)
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        try:
            page.goto("/", timeout=60_000)
            assert run_search(page, "TCS").ok
        finally:
            ctx.close()

    def test_page_basics_for_accessibility(self, home):
        assert home.locator("html[lang]").count() == 1, "<html> needs a lang attribute"
        assert home.locator("meta[name=viewport]").count() == 1
        assert home.title().strip()

    def test_all_buttons_have_accessible_names(self, home):
        buttons = home.get_by_role("button")
        unnamed = []
        for i in range(buttons.count()):
            b = buttons.nth(i)
            if b.is_visible():
                name = (b.inner_text() or b.get_attribute("aria-label") or b.get_attribute("title") or "").strip()
                if not name:
                    unnamed.append(b.evaluate("e => e.outerHTML.slice(0, 80)"))
        assert not unnamed, f"Buttons without an accessible name: {unnamed}"

    def test_keyboard_can_reach_search(self, home):
        home.keyboard.press("Tab")
        focused = home.evaluate("() => document.activeElement && document.activeElement.tagName")
        assert focused and focused != "BODY"
