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


def components(page, site):
    page.goto(site + "app/components.html", wait_until="networkidle")
    page.wait_for_selector("#gallery .demo")


def review_link(hash_part):
    """Review opened by a deep link to the sample: a finding or a benchmark, explained."""
    def go(page, site):
        page.goto(site + "app/review.html?sample=1&project=orders-api#" + hash_part, wait_until="networkidle")
        page.wait_for_selector("tr.finding-detail:not([hidden]) figure.code" if hash_part.startswith("finding") else ".bench .why",
                               timeout=120000)
    go.__name__ = "review_" + hash_part.replace("=", "_").replace("-", "_")
    return go


def projects_tab(tab):
    def go(page, site):
        page.goto(site + "app/projects.html", wait_until="networkidle")
        page.click("#pj-sample")
        page.wait_for_selector("#pj-results:not([hidden])")
        page.click(f"#pj-tabs button[data-tab={tab}]")
        if tab == "project":
            page.wait_for_selector("table.heat")
    go.__name__ = f"projects_{tab}"
    return go


def projects_empty(page, site):
    page.goto(site + "app/projects.html", wait_until="networkidle")


def dark(state):
    """The same state with the system set to dark mode (every color comes from the tokens in style.css)."""
    def go(page, site):
        page.emulate_media(color_scheme="dark")
        state(page, site)
    go.__name__ = f"{state.__name__}_dark"
    return go


TABS = ["overview", "decisions", "priorities", "scorecard", "findings", "compare", "more"]
STATES = ([home, docs, setup_empty, setup_filled, run_page, run_three, review_empty] + [review_tab(t) for t in TABS]
          + [components, dark(components), dark(setup_filled), dark(review_tab("findings"))]
          + [projects_empty, projects_tab("all"), projects_tab("decisions"), projects_tab("project"), dark(projects_tab("project"))]
          + [review_link("finding=A1-001"), review_link("bench=A3"), dark(review_link("finding=A1-001"))])
