"""Report format 5 (A9, with A13 provenance, C4 work orders and N3 usage): schema_version, `noticed`, the quote as
the anchor, UTC timestamps, fingerprints, who graded. 4.x reports are still read with the format-4 schema."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
CODE = EXAMPLE.parent / "sample-repo"
PROJ = "projects/orders-api"
NEW = EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def gk(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


def start(repo, *extra):
    out = json.loads(gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--grader", "Claude Code",
                        "--json", *extra, cwd=repo).stdout)["result"]
    return out["report"]


def load(repo, rel):
    return json.loads((repo / rel).read_text())


def config(gk_mod):
    return gk_mod.resolve_config([str(EXAMPLE / PROJ / "project.toml")])


def finish(repo, rel):
    """Score every benchmark and fill the required prose, through the commands (as a grader would)."""
    r = load(repo, rel)
    for b in r["benchmarks"]:
        if b["applicability"] != "not_applicable":
            gk("report", "score", rel, b["id"], "--score", "7", "--confidence", "medium", cwd=repo)
    gk("report", "set", rel, "scope_examined", "all of src/", cwd=repo)
    gk("report", "ran", rel, "--command", "pytest -q", "--exit-code", "0", "--summary", "12 passed", cwd=repo)
    gk("report", "set", rel, "limitations", '["None"]', cwd=repo)


# --------------------------------------------------------------------------- what report new writes

def test_new_reports_are_format_5_with_provenance(repo):
    rel = start(repo, "--model", "claude-opus-5-5", "--session", "https://example.com/s/1", "--work-order", "WO-7")
    r = load(repo, rel)
    assert r["schema_version"] == 5
    run = r["run"]
    assert UTC.match(run["started"]) and UTC.match(run["date"])
    assert (run["grader"], run["model"], run["session"], run["work_order"]) == ("Claude Code", "claude-opus-5-5", "https://example.com/s/1", "WO-7")


def test_a_finished_report_records_the_model(repo):
    rel = start(repo)
    finish(repo, rel)
    r = gk("report", "check", rel, "--json", cwd=repo, code=5)
    assert any("run.model" in t for t in json.loads(r.stdout)["result"]["todo"])
    gk("report", "set", rel, "run.model", "claude-opus-5-5", cwd=repo)
    gk("report", "check", rel, "--write", cwd=repo)
    run = load(repo, rel)["run"]
    assert run["model"] == "claude-opus-5-5" and run["usage"]["minutes"] is not None and run["usage"]["minutes"] >= 0


def test_validate_refuses_a_finished_report_without_a_model(gk, repo):
    rel = start(repo, "--model", "m")
    finish(repo, rel)
    gk_cli = gk
    subprocess.run(KIT + ["report", "check", rel, "--write"], cwd=repo, env=ENV, check=True, capture_output=True)
    r = load(repo, rel)
    r["run"]["model"] = None
    errors, _ = gk_cli.validate_report(r, config(gk_cli), gk_cli.load_catalog())
    assert any("run.model is empty" in e for e in errors)


def test_format_5_needs_utc_timestamps(gk, repo):
    rel = start(repo, "--model", "m")
    r = load(repo, rel)
    r["run"]["date"] = "2026-11-08"
    errors, _ = gk.validate_report(r, config(gk), gk.load_catalog())
    assert any("schema: run/date" in e for e in errors)


def test_4x_reports_are_read_with_the_format_4_schema(gk):
    r = json.loads(NEW.read_text())
    assert "schema_version" not in r
    errors, _ = gk.validate_report(r, config(gk), gk.load_catalog())
    assert errors == []
    r["schema_version"] = 5     # claiming format 5 without its fields fails
    errors, _ = gk.validate_report(r, config(gk), gk.load_catalog())
    assert any("schema:" in e for e in errors)


# --------------------------------------------------------------------------- fingerprints

def test_fingerprints_are_written_and_checked(gk, repo):
    rel = start(repo, "--model", "m")
    gk_cli = ["report", "finding", "add", rel, "--benchmark", "A2", "--title", "Amount unchecked", "--severity", "major",
              "--cite", "src/payments/api.py:5", "--repo", CODE]
    subprocess.run(KIT + gk_cli, cwd=repo, env=ENV, check=True, capture_output=True)
    f = load(repo, rel)["findings"][0]
    assert re.fullmatch(r"[0-9a-f]{12}", f["fingerprint"]) and f["fingerprint"] == gk.fingerprint_of(f)
    r = load(repo, rel)
    r["findings"][0]["fingerprint"] = "0" * 12
    errors, _ = gk.validate_report(r, config(gk), gk.load_catalog())
    assert any("fingerprint 000000000000 doesn't match" in e for e in errors)


def test_the_same_problem_keeps_its_fingerprint_when_the_code_moves(gk):
    f = {"benchmark_id": "A3", "title": "a", "evidence": [{"type": "code", "file": "src/x.py", "lines": "10", "quote": "  retry(job)  "}]}
    moved = {"benchmark_id": "A3", "title": "reworded title", "evidence": [{"type": "code", "file": "src/x.py", "lines": "42",
                                                                          "quote": "retry(job)", "note": "new note"}]}
    other = {"benchmark_id": "A3", "title": "a", "evidence": [{"type": "code", "file": "src/x.py", "lines": "10", "quote": "run(job)"}]}
    assert gk.fingerprint_of(f) == gk.fingerprint_of(moved) != gk.fingerprint_of(other)


# --------------------------------------------------------------------------- the quote is the anchor

def test_code_evidence_without_lines(gk):
    lines = ["def pay(amount):", "    charge(amount)", ""]
    assert gk.check_code_evidence({"type": "code", "file": "a.py", "quote": "charge(amount)"}, lambda rel: lines, 2) is None
    assert "quote not found in a.py" in gk.check_code_evidence({"type": "code", "file": "a.py", "quote": "refund()"}, lambda rel: lines, 2)


# --------------------------------------------------------------------------- noticed

def test_noticed_findings_are_open_but_never_fail_a_pr_check(gk, repo):
    base = json.loads(NEW.read_text())
    rel = start(repo, "--model", "m", "--mode", "pr", "--base-commit", "a1b2c3d")
    subprocess.run(KIT + ["report", "finding", "add", rel, "--benchmark", "A2", "--title", "Login has no rate limit (already there)",
                          "--severity", "major", "--status", "noticed", "--cite", "src/payments/api.py:5", "--repo", CODE],
                   cwd=repo, env=ENV, check=True, capture_output=True)
    pr = load(repo, rel)
    f = pr["findings"][-1]
    assert f["status"] == "noticed" and f["first_seen_commit"] == "a1b2c3d", "noticed findings were first seen at the base"
    pr["benchmarks"] = base["benchmarks"]
    pr["findings"] = base["findings"] + [f]
    c = config(gk)
    d = gk.compute_diff(base, pr, c, c)
    assert d["regressions"] == [] and any("pre-existing" in n and f["id"] in n for n in d["notes"])
    assert f["id"] in gk.analyze_findings(pr, c) and "noticed" in gk.OPEN_STATUSES


def test_noticed_needs_format_5(repo):
    rel = str((repo / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json").relative_to(repo))
    r = gk("report", "finding", "add", rel, "--benchmark", "A2", "--title", "x", "--severity", "minor", "--status", "noticed",
           "--absence", "a", "--method", "b", cwd=repo, code=1)
    assert "needs a format-5 report" in r.stderr


# --------------------------------------------------------------------------- carry and rendering

def test_carry_upgrades_a_4x_baseline_to_format_5(gk, repo):
    out = repo.parent / "pr.json"
    gk_args = ["carry", str(NEW), "--repo", CODE, "--commit", "b2c3d4e5f6", "--base-commit", "a1b2c3d", "--out", out,
               "--allow-withheld", "--model", "claude-opus-5-5", "--session", "S-1"]
    subprocess.run(KIT + [str(a) for a in gk_args], cwd=repo, env=ENV, check=True, capture_output=True)
    r = json.loads(out.read_text())
    assert r["schema_version"] == 5 and UTC.match(r["run"]["started"])
    assert (r["run"]["model"], r["run"]["session"]) == ("claude-opus-5-5", "S-1")
    assert list(r)[0] == "schema_version"


def test_report_md_says_who_graded(gk, repo):
    rel = start(repo, "--model", "claude-opus-5-5", "--work-order", "WO-7")
    finish(repo, rel)
    subprocess.run(KIT + ["report", "check", rel, "--write"], cwd=repo, env=ENV, check=True, capture_output=True)
    md = gk.render_report_md(load(repo, rel), config(gk))
    assert re.search(r"\*Graded by Claude Code \(claude-opus-5-5\) · [\d.]+ min · work order `WO-7`\*", md)


def test_a_public_copy_keeps_its_fingerprints_valid(gk, repo):
    """redact withholds a sensitive finding's evidence; its fingerprint, computed from the full report, stays."""
    rel = start(repo, "--model", "m")
    subprocess.run(KIT + ["report", "finding", "add", rel, "--benchmark", "A2", "--title", "Amount unchecked", "--severity", "major",
                          "--sensitive", "--cite", "src/payments/api.py:5", "--repo", CODE], cwd=repo, env=ENV, check=True, capture_output=True)
    finish(repo, rel)
    subprocess.run(KIT + ["report", "check", rel, "--write"], cwd=repo, env=ENV, check=True, capture_output=True)
    fp = load(repo, rel)["findings"][0]["fingerprint"]
    subprocess.run(KIT + ["redact", rel, "--in-place"], cwd=repo, env=ENV, check=True, capture_output=True)
    public = load(repo, rel)
    f = public["findings"][0]
    assert f["evidence"][0]["type"] == "withheld" and f["fingerprint"] == fp
    errors, _ = gk.validate_report(public, config(gk), gk.load_catalog())
    assert not [e for e in errors if "fingerprint" in e]
    gk_args = ["report", "check", rel]
    r = subprocess.run(KIT + gk_args, cwd=repo, env=ENV, capture_output=True, text=True)
    assert load(repo, rel)["findings"][0]["fingerprint"] == fp, "editing the public copy never overwrites it"
