"""The three tools, driven like a person would. Engine calls run in CPython (see conftest.site)."""
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from conftest import EXAMPLE

pytestmark = pytest.mark.browser
PROJECT = EXAMPLE / "projects" / "orders-api"
SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def zip_dir(src: Path, dest: Path, top: str) -> Path:
    with zipfile.ZipFile(dest, "w") as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, f"{top}/{p.relative_to(src).as_posix()}")
    return dest


def ready(page, site, path):
    page.goto(site + path)
    page.wait_for_selector("#engine-pill.ready", timeout=60000)


# --------------------------------------------------------------------------- Set up a project

def test_setup_round_trip(page, site, tmp_path):
    ready(page, site, "app/setup.html")
    page.fill("#f-code", "https://github.com/acme/Shop-API.git")
    page.dispatch_event("#f-code", "input")
    page.wait_for_timeout(400)
    assert page.input_value("#f-name") == "shop-api"
    assert "projects/shop-api/" in page.inner_text("#proj-path")
    page.locator("#presets label:has(input[value=service])").click()
    page.wait_for_function("document.querySelector('#pv-status').textContent.includes('Valid')")
    page.eval_on_selector_all("details", "els => els.forEach(e => e.open = true)")
    assert page.locator("#t-level-wrap").is_hidden(), "the Level field shows only for level targets"
    with page.expect_download() as d:
        page.click("#dl-toml")
    toml = Path(d.value.path()).read_text()
    assert 'name            = "shop-api"' in toml and "projects/shop-api/project.toml" in toml
    ready(page, site, "app/setup.html")
    page.locator("label:has(input[name=start][value=edit])").click()
    page.fill("#toml-paste", toml)
    page.click("#toml-load")
    page.wait_for_timeout(1500)
    assert page.inner_text("#toml-out").strip() == toml.strip()
    assert not page.errors


def test_setup_gate_chips_sit_together(page, site):
    ready(page, site, "app/setup.html")
    page.wait_for_function("document.querySelectorAll('#pv-gates .chip').length >= 2")
    xs = page.eval_on_selector_all("#pv-gates .chip", "els => els.map(e => e.getBoundingClientRect().x)")
    assert xs[1] - xs[0] < 80


# --------------------------------------------------------------------------- Start a run

@pytest.mark.parametrize("role, expect", [
    ("Grade the code", "Act as the GRADER"), ("Review a report", "REVIEWER"),
    ("Improve the code", "Act as the IMPROVER"), ("Check a pull request", "PULL-REQUEST REVIEWER"),
])
def test_run_prompts(page, site, role, expect):
    page.goto(site + "app/run.html")
    page.wait_for_selector("#roles .choice")
    page.fill("#code-loc", "https://github.com/acme/orders-api")
    page.fill("#gdir-loc", "https://github.com/acme/grading")
    page.wait_for_timeout(300)
    assert page.input_value("#project-name") == "orders-api"
    page.click(f"text={role}")
    page.wait_for_timeout(300)
    prompt = page.inner_text("#prompt-out")
    assert expect in prompt and "orders-api" in prompt and "AGENT.md" in prompt
    assert not page.errors


# --------------------------------------------------------------------------- Review a report

def test_review_sample(page, site):
    ready(page, site, "app/review.html")
    page.click("#sample")
    page.wait_for_selector("#results:not([hidden])")
    checks = page.inner_text("#panel-overview .checks")
    assert "Report format and rules: Valid" in checks and "warning" not in checks.split("Config")[0]
    for tab in ("decisions", "priorities", "scorecard", "findings", "compare", "more"):
        page.click(f"#result-tabs button[data-tab={tab}]")
        assert page.inner_text(f"#panel-{tab}").strip()
    assert not page.errors


def mock_github(page):
    def handle(route):
        u = route.request.url
        if u.endswith("/repos/acme/grading"):
            return route.fulfill(json={"default_branch": "main"})
        if "/repos/acme/grading/pulls/12" in u:
            return route.fulfill(json={"head": {"ref": "report/orders-api/2026-11-07-a1b2c3d", "repo": {"name": "grading", "owner": {"login": "acme"}}}})
        if "/repos/acme/grading/commits/" in u:
            return route.fulfill(json={"sha": SHA})
        m = re.search(r"/repos/acme/grading/contents/([^?]+)\?ref=(.+)$", u)
        if m:
            assert m.group(2) == SHA, "files are read at the resolved commit"
            path = EXAMPLE / m.group(1)
            if path.is_dir():
                return route.fulfill(json=[{"name": n.name, "type": "dir" if n.is_dir() else "file",
                                            "download_url": f"https://raw.githubusercontent.com/acme/grading/{SHA}/{m.group(1)}/{n.name}"}
                                           for n in sorted(path.iterdir())])
            return route.fulfill(status=404, json={})
        m = re.search(rf"raw\.githubusercontent\.com/acme/grading/{SHA}/(.+)$", u)
        if m and (EXAMPLE / m.group(1)).is_file():
            return route.fulfill(path=str(EXAMPLE / m.group(1)))
        return route.fulfill(status=404, body="not found")
    page.context.route("https://api.github.com/**", handle)
    page.context.route("https://raw.githubusercontent.com/**", handle)


def test_review_from_github_and_pr_link(page, site):
    mock_github(page)
    ready(page, site, "app/review.html")
    page.fill("#gh-repo", "acme/grading")
    page.click("#gh-load")
    page.wait_for_selector("#results:not([hidden])")
    status = page.inner_text("#gh-status")
    assert "Loaded orders-api" in status and SHA[:7] in status and "2 report(s)" in status
    page.goto(site + "app/review.html?repo=https://github.com/acme/grading/pull/12")
    page.wait_for_selector("#results:not([hidden])")
    assert page.input_value("#gh-ref") == "report/orders-api/2026-11-07-a1b2c3d"


def test_review_zips_check_citations(page, site, tmp_path):
    grading = zip_dir(EXAMPLE, tmp_path / "grading.zip", "grading-repo")
    code = zip_dir(EXAMPLE.parent / "sample-repo", tmp_path / "code.zip", "sample-repo-main")
    ready(page, site, "app/review.html")
    page.click("[data-tab=files]")
    page.set_input_files("#file-input", [str(grading), str(code)])
    page.wait_for_selector("#results:not([hidden])")
    page.wait_for_function("document.querySelector('#panel-overview .checks').textContent.includes('checked')")
    assert re.search(r"Code citations: \d+ checked, 0 failed", page.inner_text("#panel-overview .checks"))
    assert not page.errors


def test_review_whole_repo_folder_skips_bundled_example(page, site, built, tmp_path):
    repo = tmp_path / "code-grader"
    shutil.copytree(PROJECT, repo / "projects" / "shop-api")
    shutil.copytree(built / "bare", repo / "bundle" / "bare")
    ready(page, site, "app/review.html")
    page.click("[data-tab=files]")
    page.set_input_files("#folder-input", str(repo))
    page.wait_for_selector("#results:not([hidden])")
    assert page.inner_text("#history-bar").startswith("shop-api")


def test_review_zip_with_two_projects_shows_picker(page, site, tmp_path):
    root = tmp_path / "grading"
    shutil.copytree(PROJECT, root / "projects" / "orders-api")
    shutil.copytree(PROJECT, root / "projects" / "shop-api")
    z = zip_dir(root, tmp_path / "two.zip", "grading")
    ready(page, site, "app/review.html")
    page.click("[data-tab=files]")
    page.set_input_files("#file-input", [str(z)])
    page.wait_for_selector("#filelist .banner select")
    page.select_option("#filelist .banner select", "1")
    page.click("#filelist .banner button")
    page.wait_for_selector("#results:not([hidden])")
    assert page.inner_text("#history-bar").startswith("shop-api")


def test_review_orders_same_day_reports_by_time(page, site, tmp_path):
    root = tmp_path / "grading"
    proj = root / "projects" / "orders-api"
    shutil.copytree(PROJECT, proj)
    shutil.rmtree(proj / "reports")
    base = json.loads((PROJECT / "reports" / "2026-11-07-a1b2c3d" / "report.json").read_text())
    for folder, when in (("2026-11-07-0000aaa", "2026-11-07T16:30:00Z"), ("2026-11-07-ffff000", "2026-11-07T09:00:00Z")):
        (proj / "reports" / folder).mkdir(parents=True)
        r = dict(base, run=dict(base["run"], date=when))
        (proj / "reports" / folder / "report.json").write_text(json.dumps(r))
    z = zip_dir(root, tmp_path / "sameday.zip", "grading")
    ready(page, site, "app/review.html")
    page.click("[data-tab=files]")
    page.set_input_files("#file-input", [str(z)])
    page.wait_for_selector("#results:not([hidden])")
    assert "2026-11-07-0000aaa (latest)" in page.inner_text("#history-bar")


def test_review_decisions_produce_appended_json(page, site):
    ready(page, site, "app/review.html")
    page.click("#sample")
    page.wait_for_selector("#results:not([hidden])")
    page.click("#result-tabs button[data-tab=decisions]")
    page.fill("#panel-decisions input[type=text]", "tester@example.com")
    first = page.locator("#panel-decisions .decision").first
    first.locator("label:has(input[value=approve])").click()
    page.wait_for_timeout(500)
    out = page.inner_text("#dec-output")
    data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert data["decisions"][-1]["approved"] is True and data["decisions"][-1]["decided_by"] == "tester@example.com"
