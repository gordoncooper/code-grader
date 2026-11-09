"""Answering decision questions without editing JSON (5.0, C5): `gradekit decide`, `gradekit decisions`, and the
report PR's checklist that the decide CI job reads."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PROJ = "projects/orders-api"
Q = "Implement CSV and XLSX export, or drop the export claim from the README?"


def cli(*args, cwd, code=0, stdin=None):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True, input=stdin)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def js(*args, cwd, code=0, stdin=None):
    return json.loads(cli(*args, "--json", cwd=cwd, code=code, stdin=stdin).stdout)["result"]


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


def entries(repo):
    return json.loads((repo / PROJ / "decisions.json").read_text())["decisions"]


def checklist(approve=(), decline=(), marker=True):
    lines = ["Grading report for **orders-api**.", "", "**Decisions needed**", "",
             f"- [{'x' if 'D1-act-1' in approve else ' '}] **D1-act-1:** {Q}",
             f"  - [{'x' if 'D1-act-1' in decline else ' '}] Decline D1-act-1 instead"]
    return "\n".join(lines + ([f"", "<!-- gradekit:project=orders-api -->"] if marker else [])) + "\n"


def test_decisions_lists_the_newest_reports_questions(repo):
    res = js("decisions", "--project", "orders-api", cwd=repo)
    assert [(d["action_id"], d["status"], d["question"]) for d in res["decisions"]] == [("D1-act-1", "pending", Q)]
    assert js("decisions", "--project", "orders-api", "--approved", cwd=repo)["approved"] == []


def test_approve_by_id_records_the_question_and_who(repo):
    res = js("decide", "--project", "orders-api", "--approve", "D1-act-1", "--by", "gordon", "--date", "2026-11-09", cwd=repo)
    assert res["added"] == [{"action_id": "D1-act-1", "question": Q, "approved": True, "decided_by": "gordon", "date": "2026-11-09"}]
    assert entries(repo) == res["added"]
    assert [d["action_id"] for d in js("decisions", "--project", "orders-api", "--approved", cwd=repo)["approved"]] == ["D1-act-1"]
    assert "_about" in json.loads((repo / PROJ / "decisions.json").read_text()), "the file's note is kept"


def test_the_same_answer_twice_is_recorded_once_but_a_change_of_mind_is_appended(repo):
    for _ in range(2):
        cli("decide", "--project", "orders-api", "--approve", "D1-act-1", "--by", "gordon", cwd=repo)
    assert len(entries(repo)) == 1
    res = js("decide", "--project", "orders-api", "--decline", "D1-act-1", "--by", "gordon", "--answer", "not this quarter", cwd=repo)
    assert len(entries(repo)) == 2 and entries(repo)[-1]["approved"] is False and res["added"][0]["answer"] == "not this quarter"
    assert js("decisions", "--project", "orders-api", cwd=repo)["decisions"][0]["status"] == "declined"


def test_unknown_ids_are_refused_and_nothing_is_written(repo):
    before = (repo / PROJ / "decisions.json").read_text()
    r = cli("decide", "--project", "orders-api", "--approve", "D1-act-1", "X9-act-1", "--by", "g", cwd=repo, code=1)
    assert "X9-act-1" in r.stderr and "gradekit decisions" in r.stderr
    assert (repo / PROJ / "decisions.json").read_text() == before


def test_a_ticked_checklist_approves_and_finds_the_project_from_its_marker(repo):
    (repo / "body.md").write_text(checklist(approve=["D1-act-1"]))
    res = js("decide", "--from-checklist", "body.md", "--by", "octocat", cwd=repo)
    assert [(e["action_id"], e["approved"], e["decided_by"]) for e in res["added"]] == [("D1-act-1", True, "octocat")]
    again = js("decide", "--from-checklist", "-", "--by", "octocat", cwd=repo, stdin=checklist(approve=["D1-act-1"]))
    assert again["added"] == [] and again["skipped"] == ["D1-act-1"], "an edit that changes nothing else records nothing"


def test_the_decline_box_declines_and_both_boxes_is_no_answer(repo):
    res = js("decide", "--from-checklist", "-", "--by", "o", cwd=repo, stdin=checklist(decline=["D1-act-1"]))
    assert res["added"][0]["approved"] is False
    both = cli("decide", "--from-checklist", "-", "--by", "o", cwd=repo, stdin=checklist(approve=["D1-act-1"], decline=["D1-act-1"]))
    assert "both approve and decline" in both.stdout and len(entries(repo)) == 1


def test_unticked_boxes_change_nothing(repo):
    res = js("decide", "--from-checklist", "-", "--by", "o", cwd=repo, stdin=checklist())
    assert res["added"] == [] and entries(repo) == []


def test_a_checklist_without_a_marker_needs_the_project(repo):
    r = cli("decide", "--from-checklist", "-", "--by", "o", cwd=repo, stdin=checklist(approve=["D1-act-1"], marker=False), code=1)
    assert "--project-dir" in r.stderr
    js("decide", "--project-dir", PROJ, "--from-checklist", "-", "--by", "o", cwd=repo, stdin=checklist(approve=["D1-act-1"], marker=False))
    assert len(entries(repo)) == 1


def test_agents_are_told_their_answers_need_permission(repo):
    r = cli("decide", "--project", "orders-api", "--approve", "D1-act-1", "--by", "agent-claude", cwd=repo)
    assert "allow_agent_decisions" in r.stdout
    assert js("decisions", "--project", "orders-api", cwd=repo)["decisions"][0]["status"] == "pending"


def test_the_report_pr_body_is_a_checklist_decide_can_read(tmp_path):
    """The PR body deliver writes, ticked by a person, is what the decide job hands to `gradekit decide`."""
    sys.path.insert(0, str(SRC / "tools"))
    import gradekit as gk
    import argparse
    pdir = tmp_path / "grading" / PROJ
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    rpath = gk.report_folders(pdir)[-1] / "report.json"
    report = json.loads(rpath.read_text())
    cfg = gk.load_config(argparse.Namespace(project_dir=str(pdir), project=None, config=None, component=None), report, quiet=True)
    body = gk.render_report_pr(report, cfg)["body"]
    assert "<!-- gradekit:project=orders-api -->" in body and "- [ ] **D1-act-1:**" in body and "- [ ] Decline D1-act-1 instead" in body
    assert "Tick a question's first box" in body
    ticked = body.replace("- [ ] **D1-act-1:**", "- [x] **D1-act-1:**")
    res = js("decide", "--from-checklist", "-", "--by", "octocat", cwd=tmp_path / "grading", stdin=ticked)
    assert res["added"][0]["action_id"] == "D1-act-1" and res["added"][0]["approved"] is True


@pytest.mark.parametrize("name", ["github-grading.yml", "gitlab-grading.yml"])
def test_ci_templates_record_ticked_answers_safely(name):
    import re
    text = (SRC / "ci" / name).read_text()
    call = re.search(r'gradekit\.py" decide ([^\n]+)', text).group(1)
    helptext = cli("decide", "--help", cwd=SRC).stdout
    for flag in set(re.findall(r"--[a-z-]+", call)):
        assert flag in helptext, f"{name} uses {flag}, which `gradekit decide` doesn't have"
    body_refs = [l.strip() for l in text.splitlines() if "pull_request.body" in l]
    assert body_refs in ([], ["BODY: ${{ github.event.pull_request.body }}"]), "the description reaches the shell only through an env var"
    if name.startswith("github"):
        job = text[text.index("\n  decide:"):text.index("\n  index:")]
        assert "types: [opened, synchronize, reopened, edited]" in text
        assert re.search(r"permissions:\n\s+contents: write\n", job) and "pull-requests" not in job
        assert "head.repo.full_name == github.repository" in job and "changes.body" in job and "sender.type != 'Bot'" in job
        assert "github.event.action != 'edited'" in text[text.index("\n  check:"):], "editing a description doesn't re-run the check"
    else:
        job = text[text.index("\ngrading-decide:"):text.index("\ngrading-index:")]
        assert "when: manual" in job and "$GRADING_BOT_TOKEN" in job and "$CI_MERGE_REQUEST_SOURCE_PROJECT_ID == $CI_PROJECT_ID" in job
