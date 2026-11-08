"""U1 (5.0): one component system. The tool pages are built from the components in common.js and style.css,
which app/components.html shows in every state. These tests keep the pages from growing styles of their own
again, which is where 12 of the 22 bugs fixed in 4.2.2 came from."""
import re

import pytest

from conftest import SRC
from states import components

WEB = SRC / "tools" / "web"
PAGE_JS = [p for p in WEB.glob("*.js") if p.name not in ("common.js", "engine-config.js")]


# --------------------------------------------------------------------------- the source stays on the system

def test_no_inline_styles_in_the_pages():
    for p in WEB.glob("*.html"):
        assert 'style="' not in p.read_text(encoding="utf-8"), f"{p.name}: use a class from style.css"
    for p in [*PAGE_JS, WEB / "common.js"]:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r'\bstyle: "', text), f"{p.name}: h() takes style as an object of custom properties, e.g. {{'--w': '40%'}}"
        assert "setAttribute(\"style\"" not in text and "cssText" not in text, p.name


def test_colors_come_only_from_the_tokens():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    # The token blocks: :root, and :root again inside the dark-mode media query.
    rest = re.sub(r"(@media \(prefers-color-scheme:dark\)\{)?:root\{[^}]*\}\}?", "", css)
    raw = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", rest)
    assert raw == [], f"raw colors outside the tokens (add a token instead): {sorted(set(raw))}"
    assert "prefers-color-scheme:dark" in css and css.count("prefers-color-scheme:dark") == 1, \
        "dark mode is one block of tokens, not per-component overrides"


def test_banners_and_states_are_built_by_the_components():
    for p in PAGE_JS:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r'class: "(banner|empty|state)\b', text), f"{p.name}: use UI.banner() or UI.state()"
    for p in WEB.glob("*.html"):
        assert not re.search(r'class="(banner|empty|state)\b', p.read_text(encoding="utf-8")), p.name


def test_every_component_is_on_the_components_page():
    common = (WEB / "common.js").read_text(encoding="utf-8")
    exported = re.search(r"window\.UI = \{(.*?)\};", common, re.S).group(1)
    builders = ["banner", "state", "chip", "badge", "card", "field", "seg", "table", "tabBar"]
    gallery = (WEB / "components.js").read_text(encoding="utf-8")
    for b in builders:
        assert re.search(rf"\b{b}: {b}\b", exported), f"UI.{b} isn't exported"
        assert f"UI.{b}(" in gallery, f"UI.{b} isn't shown on the components page"
    for kind in ("loading", "empty", "error"):
        assert f'UI.state("{kind}"' in gallery


def test_the_policy_allows_no_inline_styles(built):
    for p in (q for q in (built / "web").rglob("*.html") if "suite" not in q.relative_to(built / "web").parts):   # suite/: the raw kit
        text = p.read_text(encoding="utf-8")
        assert 'style="' not in text, p
        policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', text).group(1)
        assert "style-src 'self';" in policy and "'unsafe-inline'" not in policy, p


# --------------------------------------------------------------------------- the components behave



@pytest.mark.browser
def test_states_tell_screen_readers_what_is_happening(page, site):
    components(page, site)
    loading = page.locator("[data-state=loading]").first
    assert loading.get_attribute("role") == "status" and loading.get_attribute("aria-busy") == "true"
    error = page.locator("[data-state=error]").first
    assert error.get_attribute("role") == "alert" and error.locator("button", has_text="Try again").count() == 1
    empty = page.locator("[data-state=empty]").first
    assert empty.get_attribute("role") is None and empty.locator("button").count() == 1


@pytest.mark.browser
def test_a_fields_help_and_error_are_announced(page, site):
    components(page, site)
    bad = page.locator(".field.has-error input")
    assert bad.get_attribute("aria-invalid") == "true"
    described = bad.get_attribute("aria-describedby").split()
    assert any(page.locator(f"#{d}").inner_text() == "Use owner/name or a github.com URL." for d in described)
    ok = page.locator(".field:not(.has-error) input").first
    assert ok.get_attribute("aria-invalid") is None and page.locator(f"#{ok.get_attribute('aria-describedby')}").inner_text()


@pytest.mark.browser
def test_bars_take_their_size_from_custom_properties(page, site):
    components(page, site)
    w = page.evaluate("() => { const i = document.querySelector('.pbar .track i'); return [i.getBoundingClientRect().width, i.parentElement.getBoundingClientRect().width]; }")
    assert abs(w[0] / w[1] - 0.62) < 0.01


@pytest.mark.browser
def test_an_empty_table_is_an_empty_state(page, site):
    components(page, site)
    demo = page.locator(".demo", has_text="Tables")
    assert demo.locator("table").count() == 1 and demo.locator("[data-state=empty]").count() == 1


@pytest.mark.browser
def test_the_components_page_works_under_the_policy(strict_page, site):
    strict_page.goto(site + "app/components.html")
    strict_page.wait_for_selector("#gallery .demo")
    assert strict_page.csp_violations() == []
