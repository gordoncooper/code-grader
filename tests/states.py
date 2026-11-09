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


def setup_saving(page, site):
    """Quick setup filled in, with a GitHub grading repo: the save routes, a prefilled new-file link first."""
    setup_filled(page, site)
    page.fill("#f-code", "https://github.com/acme/orders-api")
    page.dispatch_event("#f-code", "input")
    page.fill("#f-grading", "https://github.com/acme/grading")
    page.wait_for_selector("#save-toml a.btn.primary")


def run_order(page, site):
    """Start a run, recording the run as a work order."""
    run_page(page, site)
    page.fill("#gdir-loc", "https://github.com/acme/grading")
    page.check("#want-order")
    page.wait_for_selector("#order-save .save-routes")


def review_answered(page, site):
    """A decision answered on the sample, with the ways to save it."""
    review_tab("decisions")(page, site)
    page.locator("#panel-decisions .seg label:has-text('Approve')").first.click()
    page.wait_for_selector("#dec-output .save-routes pre")


def tour(page, site):
    """The guided first run, one step done."""
    page.goto(site + "app/review.html?sample=1&tour=1", wait_until="networkidle")
    page.wait_for_selector("#results:not([hidden])", timeout=120000)
    page.wait_for_selector(".tour-bar")


def palette(page, site):
    """The command palette over Review's sample, searching for a benchmark."""
    review_tab("overview")(page, site)
    page.keyboard.press("Control+k")
    page.wait_for_selector("dialog.palette[open]")
    page.keyboard.type("robust")
    page.wait_for_selector(".pal-item[aria-selected=true]")


def projects_costs(page, site):
    """One project with a schedule and recorded time and cost (an index made for the test)."""
    import json
    from conftest import EXAMPLE
    idx = json.loads((EXAMPLE / "projects" / "index.json").read_text())
    p = idx["projects"][0]
    p["schedule"] = {"grade_every_days": 14, "only_if_code_changed": True}
    usage = [{"minutes": 71.0, "tokens_in": 2400000, "tokens_out": 180000, "cost_usd": 6.4}, {"minutes": 52.5, "cost_usd": 3.1}]
    for h, u in zip([x for x in p["history"] if x.get("mode") != "pr"], usage):
        h["model"] = "claude-opus-5-5"
        h["usage"] = u
    page.goto(site + "app/projects.html", wait_until="networkidle")
    page.click("#load-tabs button[data-tab=file]")
    page.set_input_files("#pj-file", files=[{"name": "index.json", "mimeType": "application/json", "buffer": json.dumps(idx).encode()}])
    page.wait_for_selector("#pj-results:not([hidden])")
    page.click("#pj-tabs button[data-tab=project]")
    page.wait_for_selector("table.heat")


TABS = ["overview", "decisions", "priorities", "scorecard", "findings", "compare", "more"]
STATES = ([home, docs, setup_empty, setup_filled, run_page, run_three, review_empty] + [review_tab(t) for t in TABS]
          + [components, dark(components), dark(setup_filled), dark(review_tab("findings"))]
          + [projects_empty, projects_tab("all"), projects_tab("decisions"), projects_tab("project"), dark(projects_tab("project"))]
          + [review_link("finding=A1-001"), review_link("bench=A3"), dark(review_link("finding=A1-001"))]
          + [setup_saving, run_order, review_answered, tour, dark(tour)]
          + [palette, dark(palette), projects_costs])
