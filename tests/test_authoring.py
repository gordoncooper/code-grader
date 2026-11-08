"""Writing reports with `gradekit report` (4.3): graders record judgments, the tool fills in the rest."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
CODE = EXAMPLE.parent / "sample-repo"
ALL = ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5", "B6", "C1", "C2", "C3", "C4",
       "D1", "D2", "D3", "D4", "E1", "E2", "E3", "E4", "F1", "F2", "F3", "F4", "F5", "F6"]


@pytest.fixture
def repo(tmp_path):
    """A copy of the example grading repo (the kit's own example must stay untouched)."""
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


def gk(*args, cwd, ok=True):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def start(repo, *extra):
    out = json.loads(gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--grader", "t", "--json", *extra, cwd=repo).stdout)["result"]
    return out["report"]


def load(repo, rel):
    return json.loads((repo / rel).read_text())


def bench(report, bid):
    return next(b for b in report["benchmarks"] if b["id"] == bid)


# --------------------------------------------------------------------------- new

def test_new_fills_every_benchmark_from_the_config(repo):
    rel = start(repo)
    assert rel.startswith("projects/orders-api/reports/") and rel.endswith("-b2c3d4e/report.json")
    r = load(repo, rel)
    cfg = json.loads(gk("resolve", "--project", "orders-api", "--out", repo / "eff.json", cwd=repo).stdout and (repo / "eff.json").read_text())
    catalog = json.loads((SRC / "rubric" / "catalog.json").read_text())
    assert [b["id"] for b in r["benchmarks"]] == [b["id"] for b in catalog["benchmarks"]]
    for b in r["benchmarks"]:
        assert b["config_weight"] == b["weight"] == cfg["weights"][b["id"]]["weight"]
        assert b["score"] is None
    assert r["config"]["hash"] == cfg["hash"]
    assert bench(r, "A2")["previous_score"] == 5, "previous scores come from the newest report"
    assert r["run"]["commit"] == "b2c3d4e5f6" and r["run"]["date"].endswith("Z")
    errors = [ln for ln in gk("validate", repo / rel, "--project", "orders-api", cwd=repo, ok=False).stdout.splitlines() if ln.startswith("ERROR")]
    assert errors and all("applicable benchmark" in e for e in errors), "a fresh report is valid apart from missing scores"


def test_new_refuses_to_overwrite_and_handles_runs(repo):
    start(repo)
    r = gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", cwd=repo, ok=False)
    assert r.returncode == 1 and "exists" in r.stderr
    assert start(repo, "--run", "2/3").endswith("/runs/run-2.json")
    assert "base-commit" in gk("report", "new", "--project", "orders-api", "--commit", "x", "--mode", "pr", cwd=repo, ok=False).stderr


# --------------------------------------------------------------------------- evidence

def test_cite_copies_the_exact_lines():
    ev = json.loads(gk("report", "cite", "src/payments/api.py:3-4", "--repo", CODE, cwd=CODE).stdout)
    lines = (CODE / "src" / "payments" / "api.py").read_text().splitlines()
    assert ev == {"type": "code", "file": "src/payments/api.py", "lines": "3-4", "quote": "\n".join(lines[2:4])}


@pytest.mark.parametrize("spec, message", [
    ("src/payments/api.py:400", "lines; cited"), ("src/nope.py:1", "file not found"),
    ("../x.py:1", "inside the repo"), ("src/payments/api.py", "FILE:LINE"),
])
def test_cite_rejects_bad_citations(spec, message):
    r = gk("report", "cite", spec, "--repo", CODE, cwd=CODE, ok=False)
    assert r.returncode == 1 and message in r.stderr


def test_findings_get_fresh_ids_and_verified_evidence(repo):
    rel = start(repo)
    out = json.loads(gk("report", "finding", "add", rel, "--benchmark", "a2", "--title", "Amount unchecked", "--severity", "major",
                        "--cite", "src/payments/api.py:5", "--repo", CODE, "--note", "negative amounts", "--sensitive", "--json", cwd=repo).stdout)["result"]
    assert out["id"] == "A2-003", "A2-001 and A2-002 exist in earlier reports"
    gk("report", "finding", "add", rel, "--benchmark", "F2", "--title", "No CI", "--severity", "critical",
       "--absence", "CI config", "--method", "ls -a", cwd=repo)
    r = load(repo, rel)
    f = r["findings"][0]
    assert f["sensitive"] and f["first_seen_commit"] == "b2c3d4e5f6" and f["evidence"][0]["note"] == "negative amounts"
    assert bench(r, "A2")["finding_ids"] == ["A2-003"] and bench(r, "F2")["finding_ids"] == ["F2-002"]
    assert "0 failed" in gk("report", "check", rel, "--repo", CODE, cwd=repo, ok=False).stdout
    missing = gk("report", "finding", "add", rel, "--benchmark", "A1", "--title", "x", "--severity", "minor", cwd=repo, ok=False)
    assert "give evidence" in missing.stderr


def test_reusing_an_id_and_updating_a_finding(repo):
    rel = start(repo)
    gk("report", "finding", "add", rel, "--benchmark", "A4", "--id", "A4-001", "--status", "open", "--title", "Seed not re-runnable",
       "--severity", "major", "--cite", "scripts/seed.sql:1", "--repo", CODE, cwd=repo)
    gk("report", "finding", "update", rel, "A4-001", "--status", "fixed", "--command", "psql -f seed.sql twice",
       "--excerpt", "INSERT 0 0", cwd=repo)
    f = load(repo, rel)["findings"][0]
    assert f["status"] == "fixed" and [e["type"] for e in f["evidence"]] == ["code", "command"]
    gk("report", "finding", "update", rel, "A4-001", "--replace-evidence", "--absence", "seed errors", "--method", "ran it twice", cwd=repo)
    assert [e["type"] for e in load(repo, rel)["findings"][0]["evidence"]] == ["absence"]
    assert "already in this report" in gk("report", "finding", "add", rel, "--benchmark", "A4", "--id", "A4-001", "--title", "x",
                                          "--severity", "minor", "--absence", "a", "--method", "b", cwd=repo, ok=False).stderr


# --------------------------------------------------------------------------- scores and actions

def test_applicability_sets_weight_and_target(repo):
    rel = start(repo)
    gk("report", "score", rel, "X1", "--applicability", "not_applicable", "--reason", "no UI", cwd=repo)
    gk("report", "score", rel, "B5", "--applicability", "limited", "--reason", "small tool", "--score", "9", "--confidence", "high", cwd=repo)
    gk("report", "score", rel, "A2", "--score", "4", "--confidence", "medium", cwd=repo)
    r = load(repo, rel)
    assert bench(r, "X1")["weight"] == 0 and bench(r, "X1")["score"] is None
    assert bench(r, "B5")["weight"] == 1 and bench(r, "B5")["target"] <= 8
    assert bench(r, "A2")["target"] == 10
    assert "--reason" in gk("report", "score", rel, "X2", "--applicability", "not_applicable", cwd=repo, ok=False).stderr
    assert "--confidence" in gk("report", "score", rel, "A1", "--score", "5", cwd=repo, ok=False).stderr


def test_actions_and_gaps(repo):
    rel = start(repo)
    gk("report", "finding", "add", rel, "--benchmark", "F2", "--title", "No CI", "--severity", "critical",
       "--absence", "CI", "--method", "ls", cwd=repo)
    gk("report", "gap", rel, "--gap", "No refunds", "--severity", "major", "--necessity", "must-have", "--benchmarks", "D2", cwd=repo)
    gk("report", "action", rel, "F2", "--action", "Add a CI workflow", "--resolves", "F2-002", "--new-score", "6", "--effort", "S",
       "--decision", "GitHub Actions or GitLab CI?", cwd=repo)
    gk("report", "action", rel, "D2", "--action", "Add a refund endpoint", "--resolves", "GAP-003", "--new-score", "7", "--effort", "M", cwd=repo)
    r = load(repo, rel)
    act = bench(r, "F2")["path_to_target"][0]
    assert act["id"] == "F2-act-1" and act["requires_human_decision"] and act["decision_question"].startswith("GitHub")
    assert r["gap_register"][0]["id"] == "GAP-003" and bench(r, "D2")["path_to_target"][0]["resolves"] == ["GAP-003"]
    assert "no such finding" in gk("report", "action", rel, "A1", "--action", "Fix everything", "--resolves", "A1-999",
                                   "--new-score", "7", "--effort", "S", cwd=repo, ok=False).stderr


def test_set_covers_prose_and_metrics_only(repo):
    rel = start(repo)
    gk("report", "set", rel, "metrics.line_coverage_pct", "41", cwd=repo)
    gk("report", "set", rel, "limitations", "Static review only", "--append", cwd=repo)
    r = load(repo, rel)
    assert r["metrics"]["line_coverage_pct"] == 41 and r["limitations"] == ["Static review only"]
    assert "covers" in gk("report", "set", rel, "findings", "[]", cwd=repo, ok=False).stderr


# --------------------------------------------------------------------------- check

def test_a_whole_report_without_writing_json(repo):
    rel = start(repo)
    first = gk("report", "check", rel, "--json", cwd=repo, ok=False)
    assert first.returncode == 5
    assert json.loads(first.stdout)["result"]["status"] == "incomplete" and len(json.loads(first.stdout)["result"]["todo"]) == 38

    gk("report", "finding", "add", rel, "--benchmark", "C4", "--title", "One test", "--severity", "critical",
       "--command", "pytest -q", "--excerpt", "1 passed", cwd=repo)
    gk("report", "strength", rel, "A1", "--text", "Totals in one place", "--cite", "src/orders/service.py:1-2", "--repo", CODE, cwd=repo)
    for bid in ALL:
        gk("report", "score", rel, bid, "--score", "3" if bid == "C4" else "7", "--confidence", "medium", cwd=repo)
    for bid in ("X1", "X2", "X3", "X4", "X5", "X6"):
        gk("report", "score", rel, bid, "--applicability", "not_applicable", "--reason", "not relevant here", cwd=repo)
    gk("report", "set", rel, "scope_examined", "src/ and scripts/", cwd=repo)
    gk("report", "ran", rel, "--command-text", "pytest -q", "--exit-code", "0", "--summary", "1 passed", cwd=repo)
    gk("report", "set", rel, "limitations", "None", "--append", cwd=repo)

    done = json.loads(gk("report", "check", rel, "--repo", CODE, "--json", "--write", cwd=repo).stdout)["result"]
    assert done["status"] == "ready" and done["errors"] == [] and done["todo"] == []
    assert done["evidence"]["checked"] == 1 and done["evidence"]["failures"] == []
    r = load(repo, rel)
    assert r["rollup"]["overall_score"] == done["overall_score"]
    assert gk("validate", "--project", "orders-api", cwd=repo).returncode == 0
    assert gk("verify-evidence", "--project", "orders-api", "--repo", CODE, cwd=repo).returncode == 0


def test_check_reports_errors_with_exit_1(repo):
    rel = start(repo)
    r = load(repo, rel)
    bench(r, "A1")["score"] = 10
    bench(r, "A1")["confidence"] = "high"
    (repo / rel).write_text(json.dumps(r))
    out = gk("report", "check", rel, cwd=repo, ok=False)
    assert out.returncode == 1 and "requires positive evidence" in out.stdout


# --------------------------------------------------------------------------- found by the 4.3 release gate

def test_ids_mentioned_in_text_are_still_free(repo):
    """A summary saying "confirmed C1-001" (a finding not written yet) must not push the new finding to C1-002."""
    rel = start(repo)
    gk("report", "ran", rel, "--command", "python probe.py", "--exit-code", "0", "--summary", "confirmed C1-001 and GAP-009", cwd=repo)
    gk("report", "set", rel, "metrics_notes", '{"lint_errors": "see C1-001"}', cwd=repo)
    out = json.loads(gk("report", "finding", "add", rel, "--benchmark", "C1", "--title", "x", "--severity", "minor",
                        "--absence", "a", "--method", "b", "--json", cwd=repo).stdout)["result"]
    assert out["id"] == "C1-001"
    r = load(repo, rel)
    assert r["commands_run"][-1]["command"] == "python probe.py", "--command works for `report ran`, like everywhere else"


def test_the_same_feature_again_updates_it(repo):
    rel = start(repo)
    gk("report", "feature", rel, "--feature", "Refunds", "--source", "README", "--status", "partial",
       "--cite", "src/payments/api.py:5", "--repo", CODE, cwd=repo)
    n = len(load(repo, rel)["feature_inventory"])
    r = gk("report", "feature", rel, "--feature", "refunds", "--source", "README", "--status", "complete",
           "--cite", "src/payments/api.py:6", "--repo", CODE, cwd=repo)
    assert "updated feature 'Refunds'" in r.stdout
    feats = load(repo, rel)["feature_inventory"]
    assert len(feats) == n and feats[-1]["status"] == "complete" and feats[-1]["evidence"][0]["lines"] == "6"
