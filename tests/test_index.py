"""projects/index.json (4.3): `gradekit index`, and how CI and the templates treat it."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
PROJ = EXAMPLE / "projects" / "orders-api"


def gk(*args, cwd, ok=True):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


@pytest.fixture
def grading(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    return g


def test_example_index_is_current():
    r = gk("index", "--check", "--json", cwd=EXAMPLE)
    assert json.loads(r.stdout)["result"]["up_to_date"], "run `gradekit index` in examples/grading-repo"


def test_index_matches_its_schema(gk):
    import jsonschema
    schema = json.loads((SRC / "schema" / "index.schema.json").read_text())
    jsonschema.validate(json.loads((EXAMPLE / "projects" / "index.json").read_text()), schema)


def test_index_content(gk):
    idx = gk.build_index(EXAMPLE)
    (p,) = idx["projects"]
    assert p["name"] == "orders-api" and p["preset"] == "service" and p["problems"] == []
    assert [h["folder"] for h in p["history"]] == ["2026-10-24-9f8e7d6", "2026-11-07-a1b2c3d"]
    assert p["latest"]["overall"] == 4.9 and p["latest"]["level"] == "L0" and p["latest"]["next_level"] == "L1"
    assert p["pending_decisions"] == [{"action_id": "D1-act-1", "folder": "2026-11-07-a1b2c3d",
                                      "question": "Implement CSV and XLSX export, or drop the export claim from the README?"}]
    assert sum(p["latest"]["open_findings"].values()) > 0
    assert gk.index_text(EXAMPLE) == gk.index_text(EXAMPLE), "deterministic: no timestamps of its own"


def test_answering_a_decision_updates_the_index(grading):
    d = grading / "projects" / "orders-api" / "decisions.json"
    data = json.loads(d.read_text())
    data["decisions"].append({"action_id": "D1-act-1", "approved": False, "answer": "Drop the claim", "decided_by": "jane@example.com"})
    d.write_text(json.dumps(data))
    assert gk("index", "--check", cwd=grading, ok=False).returncode == 1
    gk("index", cwd=grading)
    p = json.loads((grading / "projects" / "index.json").read_text())["projects"][0]
    assert p["pending_decisions"] == []
    assert gk("index", "--check", cwd=grading).returncode == 0


def test_pr_reports_and_broken_projects(grading, gk):
    pr = grading / "projects" / "orders-api" / "reports" / "2026-11-09-ffff000"
    pr.mkdir()
    r = json.loads((PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json").read_text())
    r.update(mode="pr", run=dict(r["run"], date="2026-11-09T00:00:00Z", commit="ffff000"))
    (pr / "report.json").write_text(json.dumps(r))
    broken = grading / "projects" / "broken"
    broken.mkdir()
    (broken / "project.toml").write_text("[project]\nname = 'broken'\npreset = 'nope'\n")
    idx = gk.build_index(grading)
    by = {p["name"]: p for p in idx["projects"]}
    assert by["orders-api"]["latest"]["folder"] == "2026-11-07-a1b2c3d", "the latest full report, not a PR check"
    assert by["orders-api"]["history"][-1]["mode"] == "pr"
    assert by["broken"]["problems"] and by["broken"]["latest"] is None


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, text=True, check=True).stdout


def ci(cwd):
    r = subprocess.run(KIT + ["ci", "--base", "main", "--json"], cwd=cwd, env=ENV, capture_output=True, text=True)
    return json.loads(r.stdout)["result"]


def test_ci_accepts_only_a_current_index(grading):
    git(grading, "init", "-q", "-b", "main")
    git(grading, "add", "-A")
    git(grading, "commit", "-qm", "base")
    git(grading, "switch", "-q", "-c", "pr")
    d = grading / "projects" / "orders-api" / "decisions.json"
    data = json.loads(d.read_text())
    data["decisions"].append({"action_id": "D1-act-1", "approved": True, "answer": "CSV", "decided_by": "jane@example.com"})
    d.write_text(json.dumps(data))
    gk("index", cwd=grading)
    git(grading, "commit", "-qam", "decide, with the index")
    res = ci(grading)
    assert res["ok"] and res["kind"] == "settings", res
    idx = grading / "projects" / "index.json"
    idx.write_text(idx.read_text().replace('"overall": 4.9', '"overall": 9.9'))
    git(grading, "commit", "-qam", "hand edit")
    res = ci(grading)
    assert not res["ok"] and any("index.json doesn't match" in p for p in res["problems"])


def test_templates_rebuild_the_index():
    gh = (SRC / "ci" / "github-grading.yml").read_text()
    gl = (SRC / "ci" / "gitlab-grading.yml").read_text()
    assert 'gradekit.py" index' in gh and "contents: write" in gh and "default_branch" in gh and "[skip ci]" in gh
    assert 'gradekit.py" index' in gl and "CI_DEFAULT_BRANCH" in gl and "GRADING_BOT_TOKEN" in gl
