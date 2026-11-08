"""Visual checks (4.3).

Layout rules that hold on any machine, at four widths: no sideways scrolling, tap targets of at least
24×24 px (WCAG 2.2 target size), no controls on top of each other, nothing cut off at the right edge.

Screenshot comparison against baselines in tests/visual/. Fonts render differently from one machine to
the next, so baselines are only compared on the platform and browser they were made with (CI's
Linux Chromium). CI makes them on its first run and commits them to the pull request; after an
intended change, label the pull request "update-visual" (or run the Tests workflow by hand with
"update_visual") to remake them (UPDATE_VISUAL=1 does it locally). A failed comparison leaves the actual and diff images in tests/visual/out/, which CI
uploads as the "visual-diff" artifact.
"""
import json
import os
import platform
from pathlib import Path

import pytest

from states import STATES, home, docs, setup_filled, run_page, review_tab

pytestmark = pytest.mark.browser

WIDTHS = [320, 390, 768, 1280]
VISUAL = Path(__file__).parent / "visual"
OUT = VISUAL / "out"

LAYOUT = """() => {
  const vw = document.documentElement.clientWidth, problems = [];
  if (document.documentElement.scrollWidth > vw + 1) problems.push(`scrolls sideways by ${document.documentElement.scrollWidth - vw}px`);
  const shown = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.checkVisibility({visibilityProperty: true, opacityProperty: true, contentVisibilityAuto: true})
      && !el.closest('details:not([open]) > :not(summary)'); };
  const name = el => el.id ? '#' + el.id : el.tagName.toLowerCase() + '"' + (el.textContent || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 24) + '"';
  const controls = [...document.querySelectorAll('button, select, input:not([type=hidden]), textarea, summary, [role=tab], .seg label, .choice')]
    .filter(shown).filter(el => !(el.matches('input[type=radio], input[type=checkbox]') && el.closest('label')));
  for (const el of controls) {
    const r = el.getBoundingClientRect();
    // Inline text buttons are exempt (WCAG 2.5.8 "inline"); everything else is at least 24×24.
    if (!el.matches('button.link') && (r.width < 24 || r.height < 24)) problems.push(`${name(el)} is ${Math.round(r.width)}×${Math.round(r.height)}px`);
    if (r.right > vw + 1 && !el.closest('.tabs, table, pre')) problems.push(`${name(el)} is cut off at the right edge`);
  }
  for (let i = 0; i < controls.length; i++) for (let j = i + 1; j < controls.length; j++) {
    const a = controls[i], b = controls[j];
    if (a.contains(b) || b.contains(a)) continue;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (w > 2 && h > 2) problems.push(`${name(a)} overlaps ${name(b)}`);
  }
  return [...new Set(problems)];
}"""


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("state", STATES, ids=[s.__name__ for s in STATES])
def test_layout(page, site, state, width):
    page.set_viewport_size({"width": width, "height": 900})
    state(page, site)
    page.wait_for_timeout(100)
    assert page.evaluate(LAYOUT) == []


# --------------------------------------------------------------------------- screenshots

SHOTS = [("home", home, 1280), ("docs", docs, 1280), ("setup", setup_filled, 1280), ("run", run_page, 1280),
         ("review-overview", review_tab("overview"), 1280), ("review-scorecard", review_tab("scorecard"), 1280),
         ("review-decisions", review_tab("decisions"), 1280), ("review-overview-phone", review_tab("overview"), 390),
         ("setup-phone", setup_filled, 390)]
# Things that change on their own: the kit version, build date, download size, engine status, timings.
MASK = [".ver", ".engine-pill", "[data-built]", ".dl-meta", "#pv-hash", ".built", "time"]
FREEZE = """() => { const s = document.createElement('style');
  s.textContent = '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}'
    + '.topbar{position:static!important}.toast{display:none!important}';
  document.head.appendChild(s); document.activeElement && document.activeElement.blur(); }"""


def environment(browser):
    return {"platform": f"{platform.system()}-{platform.machine()}", "browser": f"chromium {browser.version}"}


def compare(actual: Path, baseline: Path, diff: Path) -> float:
    from PIL import Image, ImageChops
    a, b = Image.open(actual).convert("RGB"), Image.open(baseline).convert("RGB")
    if a.size != b.size:
        return 1.0
    d = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = d.histogram()[255]   # the mask is 0 or 255
    if changed:
        d.save(diff)
    return changed / (a.size[0] * a.size[1])


def test_screenshots(browser, site, tmp_path):
    pytest.importorskip("PIL")
    env = environment(browser)
    meta_path = VISUAL / "baselines.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    update = os.environ.get("UPDATE_VISUAL") == "1" or (meta is None and os.environ.get("CI") == "true")
    if meta is None and not update:
        pytest.skip("no screenshot baselines yet: CI makes them on its first run (or UPDATE_VISUAL=1 makes local ones)")
    if not update and {k: meta.get(k) for k in env} != env:
        pytest.skip(f"baselines are for {meta['platform']} / {meta['browser']}; this is {env['platform']} / {env['browser']} "
                    "(compared in CI; UPDATE_VISUAL=1 makes local ones)")
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, state, width in SHOTS:
        ctx = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1, reduced_motion="reduce")
        pg = ctx.new_page()
        state(pg, site)
        pg.evaluate(FREEZE)
        pg.wait_for_timeout(200)
        shot = (VISUAL if update else OUT) / f"{name}.png"
        masks = [pg.locator(sel) for sel in MASK]
        pg.screenshot(path=str(shot), full_page=True, mask=masks, mask_color="#888888", animations="disabled")
        ctx.close()
        if not update:
            ratio = compare(shot, VISUAL / f"{name}.png", OUT / f"{name}.diff.png")
            if ratio > 0.002:
                failures.append(f"{name}: {ratio:.2%} of pixels changed (see tests/visual/out/{name}*.png)")
    if update:
        meta_path.write_text(json.dumps({**env, "shots": [n for n, _, _ in SHOTS],
                                         "about": "Made by UPDATE_VISUAL=1 (or the first run on this platform); "
                                                  "compared only on this platform and browser."}, indent=2) + "\n")
        (OUT / "NEW_BASELINES").write_text("\n".join(n for n, _, _ in SHOTS) + "\n")
        return
    assert not failures, "\n".join(failures) + "\nIf the change is intended, refresh the baselines with UPDATE_VISUAL=1 in CI."
