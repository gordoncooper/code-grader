"""Every page of the built site: no errors, no broken links, no sideways scrolling on a phone."""
import json
import urllib.request

import pytest

pytestmark = pytest.mark.browser

# Raw kit files the site serves for agents (e.g. suite/tools/web/*.html templates) are not pages.
def site_pages(site):
    manifest = json.loads(urllib.request.urlopen(site + "manifest.json").read())
    return [f["path"] for f in manifest["files"] if f["path"].endswith(".html") and not f["path"].startswith("suite/")]


@pytest.mark.parametrize("width", [1320, 390], ids=["desktop", "phone"])
def test_pages_load_cleanly(browser, site, width):
    problems, links = [], set()
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    for path in site_pages(site):
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e, errors=errors: errors.append(f"pageerror {e}"))
        pg.on("console", lambda m, errors=errors: m.type == "error" and errors.append(f"console {m.text}"))
        pg.on("response", lambda r, errors=errors: r.status >= 400 and errors.append(f"HTTP {r.status} {r.url}"))
        pg.goto(site + path, wait_until="networkidle")
        overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if overflow > 2:
            errors.append(f"scrolls sideways by {overflow}px")
        if width > 1000:
            links |= {h.split("#")[0] for h in pg.eval_on_selector_all("a[href]", "els => els.map(e => e.href)") if h.startswith(site)}
        if errors:
            problems.append((path, errors))
        pg.close()
    ctx.close()
    for link in sorted(links):
        try:
            urllib.request.urlopen(link)
        except Exception as e:  # noqa: BLE001
            problems.append((link, [str(e)]))
    assert not problems, "\n".join(f"{p}: {e}" for p, e in problems)


def test_phone_navigation_is_reachable(browser, site):
    ctx = browser.new_context(viewport={"width": 390, "height": 800})
    pg = ctx.new_page()
    for path in ("", "app/run.html", "docs/README.html"):
        pg.goto(site + path, wait_until="networkidle")
        assert pg.locator(".topbar nav.main a", has_text="Review").is_visible(), path
    ctx.close()
