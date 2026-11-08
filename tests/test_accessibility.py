"""Accessibility (4.3): axe-core on every page and state at two widths, plus keyboard checks that axe can't do."""
import hashlib
import json
import os
import urllib.request
from pathlib import Path

import pytest

from states import STATES, engine_ready, review_tab, setup_filled, run_page

pytestmark = pytest.mark.browser

AXE_VERSION = "4.14.0"
AXE_SHA256 = "20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
CACHE = Path(__file__).parent / ".cache" / f"axe-core-{AXE_VERSION}.min.js"


@pytest.fixture(scope="session")
def axe_source():
    """axe-core, pinned and checked: downloaded once into tests/.cache (not committed)."""
    if not CACHE.exists():
        try:
            data = urllib.request.urlopen(AXE_URL, timeout=60).read()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"couldn't download axe-core ({exc}); put {AXE_URL} at {CACHE}")
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_bytes(data)
    data = CACHE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == AXE_SHA256, f"{CACHE} isn't axe-core {AXE_VERSION}; delete it"
    return data.decode("utf-8")


def axe(page, source):
    page.wait_for_timeout(150)   # let the page mark scrollable tables (site.js) after it renders
    page.add_script_tag(content=source)
    return page.evaluate("""async (tags) => (await axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']}))
        .violations.map(v => `${v.impact} ${v.id}: ${v.help} → ` + v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(', '))""", AXE_TAGS)


@pytest.mark.parametrize("width", [1320, 390], ids=["desktop", "phone"])
@pytest.mark.parametrize("state", STATES, ids=[s.__name__ for s in STATES])
def test_axe(page, site, axe_source, state, width):
    page.set_viewport_size({"width": width, "height": 900})
    state(page, site)
    assert axe(page, axe_source) == []


def test_axe_on_every_doc_page(page, site, axe_source):
    manifest = json.loads(urllib.request.urlopen(site + "manifest.json").read())
    problems = {}
    for f in manifest["files"]:
        if f["path"].startswith("docs/") and f["path"].endswith(".html"):
            page.goto(site + f["path"], wait_until="networkidle")
            found = axe(page, axe_source)
            if found:
                problems[f["path"]] = found
    assert not problems, json.dumps(problems, indent=1)


# --------------------------------------------------------------------------- keyboard

FOCUSABLE = ("a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), "
             "textarea:not([disabled]), summary, [tabindex]:not([tabindex='-1'])")

TAB_WALK = """(sel) => {
  const visible = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return (r.width > 0 || r.height > 0 || el.type === 'radio' || el.type === 'checkbox') && cs.visibility !== 'hidden' && !el.closest('[hidden]') && !el.closest('details:not([open]) > :not(summary)'); };
  const all = [...document.querySelectorAll(sel)].filter(el => el.tabIndex >= 0 && visible(el));
  // A group of radios is one stop on the Tab key.
  const seen = new Set();
  return all.filter(el => { if (el.type !== 'radio') return true; const k = el.name; if (seen.has(k)) return false; seen.add(k); return true; })
            .map(el => el.type === 'radio' ? 'radio:' + el.name : (el.id ? '#' + el.id : el.tagName + ':' + (el.textContent || el.value || el.name || '').trim().slice(0, 30)));
}"""

FOCUS_SHOWN = """() => {
  const el = document.activeElement;
  const shows = e => { if (!e) return false; const cs = getComputedStyle(e);
    return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none'); };
  const key = el.type === 'radio' ? 'radio:' + el.name : (el.id ? '#' + el.id : el.tagName + ':' + (el.textContent || el.value || el.name || '').trim().slice(0, 30));
  // Visually hidden radios and checkboxes show focus on the label or the span next to them.
  return [key, shows(el) || shows(el.nextElementSibling) || shows(el.closest('label'))];
}"""


def walk(page, limit=400):
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.focus("body") if page.locator("body").count() else None
    reached, unseen = [], []
    first = None
    for _ in range(limit):
        page.keyboard.press("Tab")
        key, shown = page.evaluate(FOCUS_SHOWN)
        if key.startswith("BODY:"):   # out to the browser between the last control and the first
            continue
        if key == first:              # all the way round
            break
        first = first or key
        reached.append(key)
        if not shown and key not in unseen:
            unseen.append(key)
    return reached, unseen


@pytest.mark.parametrize("state", [setup_filled, run_page, review_tab("decisions"), review_tab("scorecard")],
                         ids=["setup", "run", "review-decisions", "review-scorecard"])
def test_every_control_is_reachable_with_a_visible_focus(page, site, state):
    state(page, site)
    expected = page.evaluate(TAB_WALK, FOCUSABLE)
    reached, unseen = walk(page)
    missing = [k for k in expected if k not in reached]
    assert not missing, f"not reachable with Tab: {missing}"
    assert not unseen, f"no visible focus indicator: {unseen}"


def test_skip_link(page, site):
    run_page(page, site)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip" and page.locator(".skip").is_visible()
    page.keyboard.press("Enter")
    assert page.evaluate("location.hash") == "#main"


def test_tabs_work_with_arrow_keys(page, site):
    review_tab("overview")(page, site)
    page.focus("#result-tabs [aria-selected=true]")
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.dataset.tab") == "decisions"
    assert page.locator("#panel-decisions").is_visible() and not page.locator("#panel-overview").is_visible()
    page.keyboard.press("End")
    assert page.evaluate("document.activeElement.dataset.tab") == "more"
    page.keyboard.press("Home")
    assert page.evaluate("document.activeElement.dataset.tab") == "overview"
    tabbable = page.eval_on_selector_all("#result-tabs [role=tab]", "ts => ts.filter(t => t.tabIndex === 0).length")
    assert tabbable == 1, "one tab in the Tab order; arrows move between them"


def test_files_can_be_chosen_with_the_keyboard(page, site):
    engine_ready(page, site, "app/review.html")
    page.click("[data-tab=files]")
    with page.expect_file_chooser() as fc:
        page.focus("#drop [data-choose]")
        page.keyboard.press("Enter")
    assert fc.value is not None
