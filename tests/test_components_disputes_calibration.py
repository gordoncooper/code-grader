"""Monorepo components in every tool (N6), finding disputes (N9) and the calibration program (C6)."""
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
PROJ = "projects/orders-api"
CODE = EXAMPLE.parent / "sample-repo"


def cli(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def j(r):
    return json.loads(r.stdout)["result"]


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, check=True)


@pytest.fixture
def grading(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    return g


# --------------------------------------------------------------------------- components (N6)

def monorepo(grading):
    toml = grading / PROJ / "project.toml"
    toml.write_text(toml.read_text() + '\n[[components]]\nname = "api"\npath = "src"\nweight = 2\n\n'
                    '[[components]]\nname = "web"\npath = "web"\nweight = 1\n')
    return grading


def finish(grading, rel, score):
    r = json.loads((grading / rel).read_text())
    for b in r["benchmarks"]:
        if b["applicability"] != "not_applicable":
            cli("report", "score", rel, b["id"], "--score", str(score), "--confidence", "medium", cwd=grading)
    cli("report", "set", rel, "scope_examined", "all", cwd=grading)
    cli("report", "ran", rel, "--command", "pytest", "--exit-code", "0", "--summary", "ok", cwd=grading)
    cli("report", "set", rel, "limitations", '["None"]', cwd=grading)
    cli("report", "set", rel, "summary", "Even across the board.", cwd=grading)
    for b in json.loads((grading / rel).read_text())["benchmarks"]:   # a path for each benchmark below target
        if isinstance(b["score"], int) and isinstance(b["target"], int) and b["score"] < b["target"]:
            cli("report", "action", rel, b["id"], "--action", "Raise it to the target", "--new-score", str(b["target"]),
                "--effort", "M", cwd=grading)
    cli("report", "check", rel, "--write", cwd=grading)


def test_a_monorepo_report_with_components(grading):
    build_monorepo_report(grading)


def build_monorepo_report(grading):
    monorepo(grading)
    args = ["--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--json"]
    repo_rel = j(cli("report", "new", "--component", "repo", *args, cwd=grading))["report"]
    api_rel = j(cli("report", "new", "--component", "api", *args, cwd=grading))["report"]
    web_rel = j(cli("report", "new", "--component", "web", *args, cwd=grading))["report"]
    assert repo_rel.endswith("/report.json") and api_rel.endswith("/components/api.json") and web_rel.endswith("/components/web.json")
    repo_r, api_r = json.loads((grading / repo_rel).read_text()), json.loads((grading / api_rel).read_text())
    assert repo_r["component"]["name"] == "repo" and api_r["component"]["name"] == "api"
    na = lambda r: {b["id"] for b in r["benchmarks"] if b["applicability"] == "not_applicable"}
    shared = {"B3", "E3", "E4", "F2", "F6", "X6"}
    assert shared.isdisjoint(na(repo_r)) and shared <= na(api_r)
    assert "A1" in na(repo_r) and next(b for b in repo_r["benchmarks"] if b["id"] == "A1")["applicability_reason"] == "graded per component"
    finish(grading, repo_rel, 7)
    finish(grading, api_rel, 8)
    finish(grading, web_rel, 6)
    folder = (grading / repo_rel).parent
    res = j(cli("rollup-repo", folder, "--write", "--json", cwd=grading))
    api_overall = json.loads((grading / api_rel).read_text())["rollup"]["overall_score"]
    web_overall = json.loads((grading / web_rel).read_text())["rollup"]["overall_score"]
    assert res["overall_score"] == round((2 * api_overall + web_overall) / 3, 1)
    stored = json.loads((grading / repo_rel).read_text())["repo_rollup"]
    assert stored["overall_score"] == res["overall_score"] and [c["component"] for c in stored["components"]] == ["api", "web"]
    cli("index", cwd=grading)
    latest = json.loads((grading / "projects" / "index.json").read_text())["projects"][0]["latest"]
    assert latest["overall"] == res["overall_score"] and [c["name"] for c in latest["components"]] == ["api", "web"]
    return grading, folder


def test_ci_checks_every_component_report(grading):
    grading, folder = build_monorepo_report(grading)
    shutil.move(str(folder), str(grading.parent / "newfolder"))
    git(grading, "init", "-q", "-b", "main")
    git(grading, "add", "-A")
    git(grading, "commit", "-qm", "base")
    git(grading, "switch", "-q", "-c", "pr")
    shutil.move(str(grading.parent / "newfolder"), str(folder))
    for name in ("report", "components/api", "components/web"):
        cli("redact", folder / f"{name}.json", "--in-place", cwd=grading)
        cli("render", "report", folder / f"{name}.json", cwd=grading)
    git(grading, "add", "-A")
    git(grading, "commit", "-qm", "report")
    res = j(cli("ci", "--base", "main", "--json", cwd=grading, code=None))
    assert res["ok"] and res["kind"] == "report", res["problems"]
    r = json.loads((folder / "report.json").read_text())
    r["repo_rollup"]["overall_score"] = 9.9
    (folder / "report.json").write_text(json.dumps(r, indent=2))
    git(grading, "commit", "-qam", "tamper")
    res = j(cli("ci", "--base", "main", "--json", cwd=grading, code=None))
    assert any("repo_rollup (9.9" in p for p in res["problems"])


# --------------------------------------------------------------------------- disputes (N9)

def test_a_dispute_must_be_answered_and_withdrawn_findings_count_nowhere(gk, grading):
    cli("dispute", "add", "A2-001", "--project", "orders-api", "--reason", "amounts are validated by the gateway", "--by", "gordon",
        cwd=grading)
    d = json.loads((grading / PROJ / "disputes.json").read_text())["disputes"][0]
    assert d["finding_id"] == "A2-001" and d["report"] == "2026-11-07-a1b2c3d" and d["date"].endswith("Z")
    assert "A2-001" in cli("dispute", "list", cwd=grading).stdout
    out = cli("carry", PROJ + "/reports/2026-11-07-a1b2c3d/report.json", "--mode", "full", "--repo", CODE, "--commit", "b2c3d4e5f6",
              "--allow-withheld", "--project", "orders-api", "--model", "m", "--json", cwd=grading)
    rel = str((grading / j(out)["report"]).relative_to(grading)) if j(out).get("report") else j(out)["written"]
    todo = j(cli("report", "check", rel, "--json", cwd=grading, code=None))["todo"]
    assert any("answer the dispute on A2-001 (gordon: amounts are validated by the gateway)" in t for t in todo)
    cli("report", "finding", "answer", rel, "A2-001", "--withdraw", "--note", "confirmed: the gateway validates amounts", cwd=grading)
    r = json.loads((grading / rel).read_text())
    f = next(x for x in r["findings"] if x["id"] == "A2-001")
    assert f["status"] == "withdrawn" and f["dispute"]["answer"] == "withdrawn" and f["dispute"]["disputed_on"] == d["date"]
    assert "withdrawn" not in gk.OPEN_STATUSES
    todo = j(cli("report", "check", rel, "--json", cwd=grading, code=None))["todo"]
    assert not any("dispute" in t for t in todo)
    assert "no open disputes" in cli("dispute", "list", cwd=grading).stdout
    rows = j(cli("dispute", "list", "--all", "--json", cwd=grading))["disputes"]
    assert rows[0]["status"] == "answered"


def test_upholding_keeps_the_finding(grading):
    cli("dispute", "add", "A2-001", "--project", "orders-api", "--reason", "x", "--by", "gordon", cwd=grading)
    out = j(cli("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--json", cwd=grading))
    rel = out["report"]
    cli("report", "finding", "add", rel, "--benchmark", "A2", "--id", "A2-001", "--status", "open", "--title", "Amount unchecked",
        "--severity", "minor", "--cite", "src/payments/api.py:5", "--repo", CODE, cwd=grading)
    cli("report", "finding", "answer", rel, "A2-001", "--uphold", "--note", "the gateway accepts negative amounts", cwd=grading)
    f = json.loads((grading / rel).read_text())["findings"][0]
    assert f["status"] == "open" and f["dispute"]["answer"] == "upheld"


def test_unknown_findings_cant_be_disputed(grading):
    r = cli("dispute", "add", "A9-999", "--project", "orders-api", "--reason", "x", "--by", "g", cwd=grading, code=1)
    assert "no finding A9-999" in r.stderr


def test_disputes_are_append_only_in_ci(grading):
    git(grading, "init", "-q", "-b", "main")
    git(grading, "add", "-A")
    git(grading, "commit", "-qm", "base")
    git(grading, "switch", "-q", "-c", "pr")
    cli("dispute", "add", "A2-001", "--project", "orders-api", "--reason", "x", "--by", "g", cwd=grading)
    git(grading, "add", "-A")
    git(grading, "commit", "-qm", "dispute")
    res = j(cli("ci", "--base", "main", "--json", cwd=grading, code=None))
    assert res["ok"] and res["kind"] == "settings", res
    git(grading, "switch", "-q", "main")
    git(grading, "merge", "-q", "pr")
    git(grading, "switch", "-q", "-c", "edit")
    p = grading / PROJ / "disputes.json"
    data = json.loads(p.read_text())
    data["disputes"][0]["reason"] = "changed"
    p.write_text(json.dumps(data))
    git(grading, "commit", "-qam", "edit")
    res = j(cli("ci", "--base", "main", "--json", cwd=grading, code=None))
    assert not res["ok"]


# --------------------------------------------------------------------------- calibration (C6)

def test_the_published_calibration_results_are_current():
    """The gate: change the scoring rules or a golden run, and these must be regenerated (`gradekit calibration run`)."""
    r = cli("calibration", "run", "--check", "--json", cwd=SRC)
    assert j(r)["up_to_date"], j(r)["stale"]


def test_a_rubric_change_changes_the_fingerprint(gk, monkeypatch):
    before = gk.scoring_fingerprint()
    real = gk.parse_rubric

    def edited(catalog=None):
        data = real(catalog)
        data["benchmarks"][0]["anchors"]["9–10"] += " Also, more."
        return data
    monkeypatch.setattr(gk, "parse_rubric", edited)
    assert gk.scoring_fingerprint() != before


def test_runs_spread_and_verdicts(gk, tmp_path):
    golden = tmp_path / "golden" / "demo"
    (golden / "runs").mkdir(parents=True)
    (golden / "expected.json").write_text(json.dumps({"reference": "demo @ 1", "commit": "abc",
                                                      "criteria": {"within_tolerance_pct": 50, "mae_max": 1.5, "max_spread": 1},
                                                      "expected": {"A1": {"score": 7}, "A2": {"score": 5}}}))
    fp = gk.scoring_fingerprint()
    for i, (a1, a2) in enumerate([(7, 5), (8, 5), (7, 6)], 1):
        (golden / "runs" / f"run-{i}.json").write_text(json.dumps({"rules_fingerprint": fp, "scores": {"A1": {"score": a1}, "A2": {"score": a2}}}))
    res = gk.calibration_results(tmp_path / "golden", 3)
    g = res["goldens"][0]
    assert g["status"] == "pass" and res["pass"] and g["spread"]["largest"] == 1
    (golden / "runs" / "run-4.json").write_text(json.dumps({"rules_fingerprint": fp, "scores": {"A1": {"score": 4}, "A2": {"score": 5}}}))
    g = gk.calibration_results(tmp_path / "golden", 3)["goldens"][0]
    assert g["status"] == "fail" and g["spread"]["unstable"] == ["A1"]
    assert gk.calibration_results(tmp_path / "golden", 5)["goldens"][0]["status"] == "needs more runs"
    assert "## demo: needs more runs" in gk.calibration_markdown(gk.calibration_results(tmp_path / "golden", 5))


def test_only_runs_under_the_current_rules_count(gk, tmp_path):
    """A rubric or limits change makes earlier runs history: listed, not counted, until graders run again."""
    golden = tmp_path / "golden" / "demo"
    (golden / "runs").mkdir(parents=True)
    (golden / "expected.json").write_text(json.dumps({"reference": "demo @ 1", "commit": "abc", "expected": {"A1": {"score": 7}}}))
    for i, fp in enumerate(["0123456789abcdef", None, gk.scoring_fingerprint()], 1):
        (golden / "runs" / f"run-{i}.json").write_text(json.dumps({"rules_fingerprint": fp, "scores": {"A1": {"score": 3 if fp != gk.scoring_fingerprint() else 7}}}))
    g = gk.calibration_results(tmp_path / "golden", 1)["goldens"][0]
    assert [r["run"] for r in g["runs"]] == ["run-3"] and [r["run"] for r in g["earlier_runs"]] == ["run-1", "run-2"]
    assert g["status"] == "pass" and g["spread"]["largest"] is None, "the old runs' 3s don't count toward the spread"
    assert "Not counted, because they were graded under earlier scoring rules: run-1, run-2." in \
        gk.calibration_markdown(gk.calibration_results(tmp_path / "golden", 1))


def test_add_run_records_the_rules(gk, tmp_path):
    golden = tmp_path / "g"
    golden.mkdir()
    (golden / "expected.json").write_text(json.dumps({"commit": "a1b2c3d", "expected": {"A1": {"score": 7}}}))
    report = EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"
    cli("calibration", "add-run", golden, report, cwd=tmp_path)
    assert json.loads((golden / "runs" / "run-1.json").read_text())["rules_fingerprint"] == gk.scoring_fingerprint()


def test_add_run_needs_the_golden_commit(tmp_path):
    golden = tmp_path / "g"
    golden.mkdir()
    (golden / "expected.json").write_text(json.dumps({"commit": "ffffff0", "expected": {"A1": {"score": 7}}}))
    report = EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"
    r = cli("calibration", "add-run", golden, report, cwd=tmp_path, code=1)
    assert "frozen at ffffff0" in r.stderr
    (golden / "expected.json").write_text(json.dumps({"commit": "a1b2c3d", "expected": {"A1": {"score": 7}}}))
    cli("calibration", "add-run", golden, report, "--note", "test", cwd=tmp_path)
    run = json.loads((golden / "runs" / "run-1.json").read_text())
    assert run["commit"].startswith("a1b2c3d") and run["scores"]["A1"]["score"] is not None and run["note"] == "test"
