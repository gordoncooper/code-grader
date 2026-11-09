"""Saving without pasting (5.0, H2), quick setup (H1), work orders from Start a run (C4) and the guided first run (U4)."""
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import SRC
from states import engine_ready, run_order, setup_saving, review_answered, tour

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]


@pytest.mark.parametrize("repo, branch, expect", [
    ("acme/grading", None, ("github", "https://github.com/acme/grading", None)),
    ("https://github.com/acme/grading.git", None, ("github", "https://github.com/acme/grading", None)),
    ("https://github.com/acme/grading/tree/trunk", None, ("github", "https://github.com/acme/grading", "trunk")),
    ("https://gitlab.com/acme/tools/grading/-/tree/dev", None, ("gitlab", "https://gitlab.com/acme/tools/grading", "dev")),
    ("https://git.acme.com/team/grading", None, (None, "https://git.acme.com/team/grading", None)),
])
def test_repo_hosts(page, site, repo, branch, expect):
    page.goto(site + "app/components.html", wait_until="networkidle")
    r = page.evaluate("([r, b]) => UI.repoHost(r, b)", [repo, branch])
    assert (r["host"], r["base"], r["branch"]) == expect


def test_new_file_links(page, site):
    page.goto(site + "app/components.html", wait_until="networkidle")
    gh = page.evaluate("UI.newFileLink('acme/grading', 'projects/x/project.toml', 'a = \"1 & 2\"\\n')")
    u = urlparse(gh["href"])
    assert u.path == "/acme/grading/new/main/projects/x" and parse_qs(u.query) == {"filename": ["project.toml"], "value": ['a = "1 & 2"\n']}
    gl = page.evaluate("UI.newFileLink('https://gitlab.com/a/g', 'projects/x/project.toml', 'x', 'dev')")
    u = urlparse(gl["href"])
    assert u.path == "/a/g/-/new/dev/projects/x" and parse_qs(u.query) == {"file_name": ["project.toml"], "content": ["x"]}
    assert page.evaluate("UI.newFileLink('https://git.acme.com/t/g', 'a', 'x')") is None, "unknown hosts get download, not a guess"
    assert page.evaluate("UI.newFileLink('acme/grading', 'a', 'x'.repeat(9000))") is None, "too long for an address"


def test_quick_setup_asks_three_questions_and_saves_to_the_grading_repo(page, site):
    setup_saving(page, site)
    assert page.locator("#questions .q").count() == 3 and page.locator("#questions-more .q").count() == 5
    href = page.get_attribute("#save-toml a.btn.primary", "href")
    u = urlparse(href)
    assert u.path == "/acme/grading/new/main/projects/orders-api"
    assert parse_qs(u.query)["value"][0].strip() == page.inner_text("#toml-out").strip()
    with page.expect_download() as d:
        page.click("#dl-toml")
    assert Path(d.value.path()).read_text().strip() == page.inner_text("#toml-out").strip()
    page.locator("label:has(input[name=start][value=edit])").click()
    page.fill("#toml-paste", page.inner_text("#toml-out"))
    page.click("#toml-load")
    page.wait_for_timeout(1200)
    assert page.locator("#save-toml a.btn.primary").count() == 0, "no host fills in an edit of an existing file"
    assert "replaces it" in page.inner_text("#save-toml")
    assert not page.errors


def test_review_saves_answers_with_gradekit_decide(page, site, tmp_path):
    review_answered(page, site)
    page.fill("#panel-decisions input[aria-label='Your name or email']", "gordon")
    page.wait_for_timeout(500)
    cmd = page.inner_text("#dec-output .save-routes pre").strip()
    assert cmd == "gradekit decide --project orders-api --approve D1-act-1 --by gordon"
    import shutil
    from conftest import EXAMPLE
    shutil.copytree(EXAMPLE, tmp_path / "g")
    subprocess.run(KIT + cmd.split()[1:], cwd=tmp_path / "g", check=True, capture_output=True)
    assert json.loads((tmp_path / "g/projects/orders-api/decisions.json").read_text())["decisions"][0]["decided_by"] == "gordon"
    assert "paste" not in page.inner_text("#dec-output").lower()
    assert not page.errors


def test_answers_with_details_get_one_command_each(page, site):
    page.goto(site + "app/components.html", wait_until="networkidle")
    cmds = page.evaluate("""UI.decideCommands("p", [
      {action_id: "A1-act-1", approved: true, decided_by: "g"}, {action_id: "A2-act-1", approved: true, decided_by: "g"},
      {action_id: "B1-act-1", approved: false, decided_by: "g", answer: "not now; it's risky"}])""")
    assert cmds == ["gradekit decide --project p --approve A1-act-1 A2-act-1 --by g",
                    "gradekit decide --project p --decline B1-act-1 --by g --answer 'not now; it'\\''s risky'"]


def test_start_a_run_writes_a_valid_work_order(page, site):
    import jsonschema
    run_order(page, site)
    page.fill("#order-by", "gordon")
    page.wait_for_timeout(500)
    m = re.search(r"Work order: (\S+) \(record it with --work-order \1\)", page.inner_text("#prompt-out"))
    assert m, page.inner_text("#prompt-out")
    with page.expect_download() as d:
        page.click("#order-save button:has-text('Download')")
    order = json.loads(Path(d.value.path()).read_text())
    assert d.value.suggested_filename == m.group(1) + ".json"
    jsonschema.validate(order, json.loads((SRC / "schema" / "work-order.schema.json").read_text()))
    assert order["id"] == m.group(1) and order["requested_by"] == "gordon" and order["delivery"] == "pr"
    assert page.get_attribute("#order-save a.btn.primary", "href").startswith("https://github.com/acme/grading/new/main/projects/")
    page.uncheck("#want-order")
    assert "Work order" not in page.inner_text("#prompt-out")
    assert not page.errors


def test_the_guided_first_run(page, site):
    tour(page, site)
    assert "1 of 6" in page.inner_text(".tour-bar")
    page.click(".tour-bar .tour-next a")   # Next: the scorecard, on this page
    page.wait_for_function("(document.querySelector('.tour-bar') || {textContent: ''}).textContent.includes('2 of 6')")
    assert page.get_attribute("#result-tabs button[data-tab=scorecard]", "aria-selected") == "true"
    page.goto(site + "app/run.html")   # the bar follows you around the site
    page.wait_for_selector(".tour-bar")
    page.click("#copy-prompt")
    page.wait_for_function("(document.querySelector('.tour-bar') || {textContent: ''}).textContent.includes('3 of 6')")
    page.click(".tour-bar button:has-text('End the tour')")
    assert page.locator(".tour-bar").count() == 0
    page.goto(site + "app/setup.html")
    assert page.locator(".tour-bar").count() == 0, "ended means ended"
    assert not page.errors
