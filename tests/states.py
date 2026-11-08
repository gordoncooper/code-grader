"""Pages of the site in the states people see them in, for the accessibility and visual tests."""


def engine_ready(page, site, path):
    page.goto(site + path)
    page.wait_for_selector("#engine-pill.ready", timeout=60000)


def home(page, site):
    page.goto(site, wait_until="networkidle")


def docs(page, site):
    page.goto(site + "docs/GETTING-STARTED.html", wait_until="networkidle")


def setup_empty(page, site):
    engine_ready(page, site, "app/setup.html")


def setup_filled(page, site):
    engine_ready(page, site, "app/setup.html")
    page.locator("#presets label:has(input[value=service])").click()
    page.wait_for_selector("#pv-status:has-text('Valid')")
    page.eval_on_selector_all("details", "els => els.forEach(e => e.open = true)")


def run_page(page, site):
    page.goto(site + "app/run.html", wait_until="networkidle")


def run_three(page, site):
    run_page(page, site)
    page.locator("label:has-text('How many graders') select").select_option("3")
    page.wait_for_selector("#prompt-tabs:not([hidden]) [role=tab]")


def review_empty(page, site):
    engine_ready(page, site, "app/review.html")


def review_tab(tab):
    def go(page, site):
        engine_ready(page, site, "app/review.html")
        page.click("#sample")
        page.wait_for_selector("#results:not([hidden])")
        page.click(f"#result-tabs button[data-tab={tab}]")
    go.__name__ = f"review_{tab}"
    return go


TABS = ["overview", "decisions", "priorities", "scorecard", "findings", "compare", "more"]
STATES = [home, docs, setup_empty, setup_filled, run_page, run_three, review_empty] + [review_tab(t) for t in TABS]
