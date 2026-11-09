"""5.0 human-facing batch 3: explain a score (H6), evidence as code and a print view (U3), deep links (U6)."""
import json
import zipfile

import pytest

from conftest import EXAMPLE, SRC
from states import review_link

CODE = EXAMPLE.parent / "sample-repo"


# --------------------------------------------------------------------------- gradekit

def test_review_links_go_to_the_report_and_its_decisions(gk):
    link = gk.review_link("https://grade.example.com/v5/", "https://github.com/acme/grading", "orders-api", "report/orders-api/x",
                          "2026-11-07-a1b2c3d", "tab=decisions")
    assert link == ("https://grade.example.com/v5/app/review.html?repo=https://github.com/acme/grading&project=orders-api"
                    "&ref=report/orders-api/x&report=2026-11-07-a1b2c3d#tab=decisions")
    assert gk.review_link(None, "x", "p", "r") is None


def test_code_context_reads_the_lines_around_a_quote(gk, tmp_path):
    z = tmp_path / "code.zip"
    with zipfile.ZipFile(z, "w") as zf:   # like GitHub's Download ZIP: one top folder
        for f in CODE.rglob("*.py"):
            zf.write(f, "sample-repo-main/" + f.relative_to(CODE).as_posix())
    src = (CODE / "src" / "orders" / "service.py").read_text().splitlines()
    out = gk.web_api("code_context", {"zip_path": str(z), "context": 2, "locations": [
        {"file": "src/orders/service.py", "lines": "7-8"},
        {"file": "src/orders/service.py", "quote": src[11] + "\n" + src[12]},   # format 5: the quote is the anchor
        {"file": "nope.py", "lines": "1"}]})["locations"]
    assert out[0]["start"] == 5 and out[0]["cited"] == [7, 8] and out[0]["text"] == src[4:10]
    assert out[1]["cited"] == [12, 13]
    assert "not found" in out[2]["error"]


# --------------------------------------------------------------------------- the page

@pytest.mark.browser
def test_a_link_to_a_finding_opens_it_with_its_code(page, site):
    review_link("finding=A1-001")(page, site)
    assert "report=2026-11-07-a1b2c3d" in page.url and "compare=2026-10-24-9f8e7d6" in page.url and page.url.endswith("#finding=A1-001")
    detail = page.locator("tr.finding-detail:not([hidden])")
    assert detail.locator("figure.code .ln.hit").count() == 2
    assert detail.locator("figure.code .ln").first.get_attribute("data-n") == "7"
    page.click("tr.finding-detail button:has-text('Open A1')")
    page.wait_for_selector("#bench-A1 .why")
    assert page.url.endswith("#bench=A1")


@pytest.mark.browser
def test_a_score_is_explained(page, site):
    review_link("bench=A3")(page, site)
    why = page.locator("#bench-A3 .why").inner_text()
    assert why.startswith("Why ")
    page.wait_for_selector("#bench-A3 .anchors li.here")
    score = int(page.locator("#bench-A3 .score").inner_text())
    lo, hi = [int(x) for x in page.locator("#bench-A3 .anchors li.here b").inner_text().replace("–", "-").split("-")]
    assert lo <= score <= hi, "the rubric band that holds the score is marked"
    page.wait_for_selector("#bench-A3 .bench-history")
    assert page.locator("#bench-A3 .bench-history > span").count() == 2, "its score in both reports of the project"


@pytest.mark.browser
def test_code_links_on_each_host(page, site):
    page.goto(site + "app/components.html", wait_until="networkidle")
    links = page.evaluate("""() => [
      UI.codeLink("https://github.com/acme/api", "abc1234", "src/a b.py", "7-9"),
      UI.codeLink("https://gitlab.example.com/acme/api.git", "abc1234", "src/a.py", "7"),
      UI.codeLink("https://bitbucket.org/acme/api", "abc1234", "src/a.py", "7-9"),
      UI.codeLink("https://git.example.com/acme/api", "abc1234", "src/a.py", "7"),
      UI.codeLink("examples/sample-repo", "abc1234", "src/a.py", "7")]""")
    assert links == ["https://github.com/acme/api/blob/abc1234/src/a%20b.py#L7-L9",
                     "https://gitlab.example.com/acme/api/-/blob/abc1234/src/a.py#L7",
                     "https://bitbucket.org/acme/api/src/abc1234/src/a.py#lines-7:9", None, None]


@pytest.mark.browser
def test_print_shows_every_section_without_controls(page, site):
    review_link("finding=A1-001")(page, site)
    page.emulate_media(media="print")
    shown = page.evaluate("""() => [...document.querySelectorAll('#results .panel')].map(p => getComputedStyle(p).display !== 'none')""")
    assert all(shown) and len(shown) == 7
    for sel in (".topbar", "#result-tabs", "#load-card", "#result-tools"):
        assert page.evaluate(f"getComputedStyle(document.querySelector('{sel}')).display") == "none", sel
    assert "orders-api: grading report" in page.inner_text("#print-head")


@pytest.mark.browser
def test_projects_links_into_review(page, site):
    page.goto(site + "app/projects.html?sample=1#tab=project&project=orders-api", wait_until="networkidle")
    page.wait_for_selector("table.heat")
    cell = page.locator("table.heat tbody tr", has_text="A3 Robustness").locator("td a").last
    href = cell.get_attribute("href")
    assert href == "review.html?sample=1&project=orders-api&report=2026-11-07-a1b2c3d#bench=A3"
    cell.click()
    page.wait_for_selector("#bench-A3 .why", timeout=120000)
