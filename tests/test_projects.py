"""5.0 human-facing batch 2: the Projects page (H3 portfolio, H4 decisions inbox, H5 cycle, U5 trends and heatmap)
and the index fields it reads. gradekit computes everything; the page only draws it."""
import json
import shutil

import pytest

from conftest import EXAMPLE
from states import projects_tab

INDEX = EXAMPLE / "projects" / "index.json"


# --------------------------------------------------------------------------- the index

def test_the_index_has_what_the_pages_draw():
    p = json.loads(INDEX.read_text())["projects"][0]
    for r in p["history"]:
        assert set(r["pillars"]) >= {"A", "B", "C", "D", "E", "F"}
        assert len(r["scores"]) == 35 and r["scores"]["X1"] == "n/a"
    d = p["pending_decisions"][0]
    assert d["benchmark_id"] == "D1" and d["action"].startswith("Either implement")
    assert p["latest"]["below_target"] > 0 and p["latest"]["actions_ready"] == 3
    assert p["cycle"] == {"stage": "decide", "waiting_on": [{"who": "people", "what": "1 decision to make"},
                                                          {"who": "an improver", "what": "3 actions ready"}]}


def project(**kw):
    base = {"name": "x", "problems": [], "latest": {"below_target": 0, "actions_ready": 0}, "pending_decisions": [],
            "open_orders": [], "open_disputes": []}
    base.update(kw)
    return base


@pytest.mark.parametrize("kw, stage, who", [
    ({"latest": None}, "grade", ["a grader"]),
    ({}, "done", []),
    ({"latest": {"below_target": 3, "actions_ready": 2}}, "improve", ["an improver"]),
    ({"latest": {"below_target": 3, "actions_ready": 0}}, "grade", ["a grader"]),
    ({"pending_decisions": [{"action_id": "A1-act-1"}], "latest": {"below_target": 3, "actions_ready": 1}}, "decide", ["people", "an improver"]),
    ({"open_orders": [{"id": "o1", "role": "prcheck"}]}, "check", ["a PR checker"]),
    ({"open_orders": [{"id": "o2", "role": "grade"}], "open_disputes": [{"finding_id": "A1-001"}]}, "grade", ["a grader", "the next grader"]),
])
def test_where_a_project_stands(gk, kw, stage, who):
    c = gk.project_cycle(project(**kw))
    assert c["stage"] == stage and [w["who"] for w in c["waiting_on"]] == who


def test_the_index_stays_current_after_a_decision(gk, tmp_path):
    repo = tmp_path / "g"
    shutil.copytree(EXAMPLE, repo)
    d = repo / "projects" / "orders-api" / "decisions.json"
    data = json.loads(d.read_text())
    data["decisions"].append({"action_id": "D1-act-1", "question": "Implement CSV and XLSX export, or drop the export claim from the README?",
                              "approved": True, "decided_by": "t", "date": "2026-11-08"})
    d.write_text(json.dumps(data))
    p = gk.build_index(repo)["projects"][0]
    assert p["pending_decisions"] == [] and p["cycle"]["stage"] == "improve" and p["latest"]["actions_ready"] == 4


# --------------------------------------------------------------------------- the page



@pytest.mark.browser
def test_every_project_at_a_glance(page, site):
    projects_tab("all")(page, site)
    row = page.locator(".proj-table tbody tr").first
    assert row.locator("button.name").inner_text() == "orders-api"
    assert row.locator("td.num").inner_text() == "4.9" and "decide" in row.inner_text()
    assert "people: 1 decision to make" in row.inner_text()
    assert page.locator(".proj-table .spark svg").count() == 1
    assert page.inner_text("#pj-dec-count") == "1"


@pytest.mark.browser
def test_one_project_trends_and_heatmap(page, site):
    projects_tab("project")(page, site)
    assert page.locator(".cycle-steps li.now").inner_text() == "decide"
    assert page.locator("table.heat tbody th[scope=row]").count() == 35
    cell = page.locator("table.heat tbody tr", has_text="A2 Security").locator("td").last
    assert cell.inner_text() == "5" and "s5" in cell.get_attribute("class")
    assert page.locator(".multiple").count() >= 7
    page.locator(".multiple").first.locator("circle.hit").last.focus()
    assert page.inner_text(".chart-tip") == "2026-11-07: 4.9", "a point's value shows on keyboard focus, not just hover"
    assert "Load the index from a GitHub grading repo" in page.inner_text("#panel-project")


@pytest.mark.browser
def test_decisions_inbox_writes_decisions_json(page, site):
    projects_tab("decisions")(page, site)
    page.fill("#panel-decisions input[type=text]", "gordon")
    page.locator(".seg label", has_text="Approve").click()
    page.fill("#panel-decisions textarea", "Drop the claim for now")
    page.click("text=Save answers for orders-api")
    page.wait_for_selector("#panel-decisions details pre", state="attached", timeout=120000)
    data = json.loads(page.text_content("#panel-decisions details pre"))
    assert "--answer 'Drop the claim for now'" in page.inner_text("#panel-decisions .save-routes pre")
    last = data["decisions"][-1]
    assert (last["action_id"], last["approved"], last["answer"], last["decided_by"]) == ("D1-act-1", True, "Drop the claim for now", "gordon")
    assert "wasn't loaded" in page.inner_text("#panel-decisions"), "from a file, earlier answers can't be merged: say so"


@pytest.mark.browser
def test_a_file_that_isnt_an_index_says_so(page, site, tmp_path):
    page.goto(site + "app/projects.html", wait_until="networkidle")
    page.click("#load-tabs button[data-tab=file]")
    bad = tmp_path / "report.json"
    bad.write_text('{"benchmarks": []}')
    page.set_input_files("#pj-file", str(bad))
    page.wait_for_selector("#pj-status [data-state=error]")
    assert "isn't a grading repo index" in page.inner_text("#pj-status")
    page.set_input_files("#pj-file", str(INDEX))
    page.wait_for_selector("#pj-results:not([hidden])")
    assert "From index.json" in page.inner_text("#panel-all")
