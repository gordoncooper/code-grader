"""The command palette (5.0, U2), and time, cost and schedules on the pages (N3, N2)."""
import pytest

from states import engine_ready, palette, projects_costs, review_tab

pytestmark = pytest.mark.browser


def results(page):
    return page.eval_on_selector_all(".pal-item .pal-label", "els => els.map(e => e.textContent)")


def test_palette_opens_from_the_keyboard_and_the_top_bar(page, site):
    page.goto(site + "app/run.html", wait_until="networkidle")
    page.click(".topbar .pal-btn")
    assert page.is_visible("dialog.palette[open]")
    assert page.evaluate("document.activeElement.classList.contains('pal-input')")
    page.keyboard.press("Escape")
    assert not page.is_visible("dialog.palette[open]")
    assert page.evaluate("document.activeElement.classList.contains('pal-btn')"), "focus goes back where it was"
    page.keyboard.press("Control+k")
    assert page.is_visible("dialog.palette[open]")
    page.keyboard.press("Control+k")
    assert not page.is_visible("dialog.palette[open]"), "the shortcut toggles"
    assert not page.errors


def test_palette_finds_rubric_terms_and_docs(page, site):
    page.goto(site + "app/setup.html")
    page.keyboard.press("Control+k")
    page.keyboard.type("a3")
    assert results(page)[0] == "A3 Robustness & Error Handling"
    page.fill(".pal-input", "gate")
    labels = results(page)
    assert "gate" in labels and labels.index("gate") < 3
    page.fill(".pal-input", "zzzz nothing")
    assert "Nothing matches" in page.inner_text(".pal-list")
    page.fill(".pal-input", "tuning guide")
    page.keyboard.press("Enter")
    page.wait_for_url("**/docs/TUNING.html")


def test_palette_jumps_within_a_report(page, site):
    palette(page, site)   # "robust" typed over the sample report
    assert results(page)[0] == "A3 Robustness & Error Handling"
    group = page.eval_on_selector(".pal-group", "e => e.textContent")
    assert group == "Benchmarks in this report", "this page's items come first"
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#bench=A3'")
    assert page.get_attribute("#result-tabs button[data-tab=scorecard]", "aria-selected") == "true"
    page.keyboard.press("Control+k")
    page.keyboard.type("A1-001")
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#finding=A1-001'")
    page.keyboard.press("Control+k")
    page.keyboard.type("go to decisions")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    assert page.get_attribute("#result-tabs button[data-tab=decisions]", "aria-selected") == "true"
    assert not page.errors


def test_palette_is_a_combobox_with_a_listbox(page, site):
    page.goto(site + "app/run.html", wait_until="networkidle")
    page.keyboard.press("Control+k")
    page.keyboard.type("project")
    inp = page.locator(".pal-input")
    assert inp.get_attribute("role") == "combobox" and inp.get_attribute("aria-expanded") == "true"
    active = inp.get_attribute("aria-activedescendant")
    assert page.get_attribute(f"#{active}", "aria-selected") == "true" and page.get_attribute(f"#{active}", "role") == "option"
    page.keyboard.press("ArrowDown")
    assert inp.get_attribute("aria-activedescendant") != active


def test_review_says_who_graded_and_what_it_took(page, site):
    review_tab("overview")(page, site)
    line = page.inner_text("#panel-overview .run-line")
    assert line.startswith("Graded by example") and "time and cost not recorded" in line


def test_projects_shows_time_cost_and_schedule(page, site):
    projects_costs(page, site)
    card = page.inner_text("#panel-project")
    assert "A full grade takes about 62 min" in card and "costs about $4.75" in card   # (71 + 52.5) / 2 min, (6.40 + 3.10) / 2
    assert "2.4M in, 180k out tokens" in card and "claude-opus-5-5" in card
    assert "Graded every 14 days when the code has changed" in card
    page.click("#pj-tabs button[data-tab=all]")
    row = page.inner_text("#panel-all .proj-table tbody tr")
    assert "53 min" in row and "$3.10" in row
    assert "due if the code changed" in row or "next 2026-11-21" in row
    assert not page.errors


def test_fmt_helpers(page, site):
    page.goto(site + "app/components.html", wait_until="networkidle")
    assert page.evaluate("[UI.fmtMinutes(12.4), UI.fmtMinutes(95), UI.fmtMinutes(720), UI.fmtCost(0.5), UI.fmtCost(1234.5)]") == \
        ["12 min", "1.6 h", "12 h", "$0.50", "$1235"]
    assert page.evaluate("UI.scheduleOf({schedule: {grade_every_days: 30}, latest: {date: '2026-11-07'}}, '2026-12-06')") == \
        {"every": 30, "onlyIfChanged": True, "next": "2026-12-07", "due": False}
    assert page.evaluate("UI.scheduleOf({schedule: {grade_every_days: 30}, latest: null}, '2026-12-06').due") is True
    assert page.evaluate("UI.scheduleOf({latest: {date: '2026-11-07'}})") is None


def test_setup_writes_a_schedule(page, site):
    engine_ready(page, site, "app/setup.html")
    page.wait_for_selector("#pv-status:has-text('Valid')")
    page.eval_on_selector_all("details", "els => els.forEach(e => e.open = true)")
    page.fill("#s-every", "30")
    page.wait_for_function("/^\\[schedule\\]\\ngrade_every_days\\s*=\\s*30$/m.test(document.querySelector('#toml-out').textContent)")
    assert "only_if_code_changed" not in page.inner_text("#toml-out").split("[schedule]")[1].split("\n\n")[0], "the default isn't written"
    page.uncheck("#s-changed")
    page.wait_for_function("/^only_if_code_changed\\s*=\\s*false$/m.test(document.querySelector('#toml-out').textContent)")
    toml = page.inner_text("#toml-out")
    page.locator("label:has(input[name=start][value=edit])").click()
    page.fill("#toml-paste", toml)
    page.click("#toml-load")
    page.wait_for_timeout(1200)
    assert page.input_value("#s-every") == "30" and not page.is_checked("#s-changed")
    page.fill("#s-every", "")
    page.wait_for_function("!/^\\[schedule\\]/m.test(document.querySelector('#toml-out').textContent)")
    assert not page.errors
