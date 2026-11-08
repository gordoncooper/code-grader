"""Enforced score limits (A8): the rubric's caps are data, each benchmark gets a computed limit, and a format-5
report can't score above it. 4.x reports keep the warnings they had."""
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


def cli(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


@pytest.fixture
def rel(repo):
    out = json.loads(cli("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--json", cwd=repo).stdout)
    return out["result"]["report"]


def load(repo, rel):
    return json.loads((repo / rel).read_text())


def config(gk_mod):
    return gk_mod.resolve_config([str(EXAMPLE / PROJ / "project.toml")])


# --------------------------------------------------------------------------- the caps are data

def test_the_catalogs_caps_are_the_rubrics():
    """catalog.json carries each benchmark's caps; they must say exactly what the rubric files say."""
    catalog = json.loads((SRC / "rubric" / "catalog.json").read_text())
    in_catalog = {b["id"]: b.get("caps", []) for b in catalog["benchmarks"]}
    in_rubric = {}
    for p in sorted((SRC / "rubric").glob("[A-FX]-*.md")):
        bid = None
        for line in p.read_text().splitlines():
            m = re.match(r"## ([A-FX]\d)\. ", line)
            if m:
                bid = m.group(1)
            m = re.match(r"- \*\*Caps:\*\*\s*(.+)$", line)
            if m and bid:
                in_rubric[bid] = [{"id": i, "when": w.strip(), "max": int(n)}
                                  for w, n, i in re.findall(r"(.+?)\s*→\s*max\s+(\d+)\s*\(`([A-FX]\d-cap-\d+)`\)\.?(?:\s+|$)", m.group(1))]
    assert {k: v for k, v in in_catalog.items() if v} == in_rubric
    assert sum(len(v) for v in in_rubric.values()) >= 20


# --------------------------------------------------------------------------- limits

def add_quickstart_finding(repo, rel):
    out = cli("report", "finding", "add", rel, "--benchmark", "E1", "--title", "Quickstart crashes", "--severity", "major",
              "--cap", "E1-cap-1", "--absence", "a working quickstart", "--method", "ran the README", "--json", cwd=repo)
    return json.loads(out.stdout)["result"]["id"]


def test_a_cap_on_a_finding_holds_while_it_is_open(repo, rel):
    fid = add_quickstart_finding(repo, rel)
    r = cli("report", "score", rel, "E1", "--score", "6", "--confidence", "high", cwd=repo, code=1)
    assert f"E1: 6 is above its limit of 4: E1-cap-1: Quickstart fails ({fid}) → max 4" in r.stderr
    cli("report", "score", rel, "E1", "--score", "4", "--confidence", "high", cwd=repo)
    cli("report", "finding", "update", rel, fid, "--status", "fixed", cwd=repo)
    cli("report", "score", rel, "E1", "--score", "6", "--confidence", "high", cwd=repo)   # fixed: the cap lifts by itself


def test_an_open_critical_finding_holds_a_score_at_5(gk, repo, rel):
    gk_cli = ["report", "finding", "add", rel, "--benchmark", "A2", "--title", "Amount unchecked", "--severity", "critical",
              "--cite", "src/payments/api.py:5", "--repo", CODE]
    subprocess.run(KIT + [str(a) for a in gk_cli], cwd=repo, env=ENV, check=True, capture_output=True)
    r = subprocess.run(KIT + ["report", "score", rel, "A2", "--score", "6", "--confidence", "high"], cwd=repo, env=ENV, capture_output=True, text=True)
    assert r.returncode == 1 and re.search(r"open critical finding A2-\d{3} → max 5", r.stderr)
    report = load(repo, rel)
    lim = gk.score_limits(report, config(gk))["A2"]
    assert lim["max"] == 5 and {w["kind"] for w in lim["why"]} >= {"critical", "strengths", "enforcement"}


def test_benchmark_caps_by_id_wording_or_free_text(gk):
    caps = gk.catalog_caps()
    assert gk.resolve_cap("C4-cap-1", "C4", caps)["max"] == 7
    assert gk.resolve_cap("Quickstart fails → max 4", "E1", caps)["id"] == "E1-cap-1"
    legacy = gk.resolve_cap("some house rule → max 6", "B3", caps)
    assert legacy["id"] is None and legacy["max"] == 6
    assert gk.resolve_cap("a note", "B3", caps) is None


def test_a_benchmark_cap_must_be_its_own(repo, rel):
    r = cli("report", "score", rel, "C4", "--score", "6", "--confidence", "high", "--cap", "E1-cap-1", cwd=repo, code=1)
    assert "not one of C4's caps" in r.stderr
    cli("report", "score", rel, "C4", "--score", "7", "--confidence", "high", "--cap", "C4-cap-1", cwd=repo)
    r = cli("report", "score", rel, "C4", "--score", "8", "--confidence", "high", cwd=repo, code=1)
    assert "C4-cap-1: Tests not run in CI → max 7" in r.stderr


def test_a_finding_cap_must_be_its_benchmarks(repo, rel):
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "x", "--severity", "minor", "--cap", "E1-cap-1",
           "--absence", "a", "--method", "b", cwd=repo, code=1)
    assert "not one of A1's caps (A1-cap-1: Failing build or tests → max 4; A1-cap-2:" in r.stderr


def test_a_critical_gap_caps_gap_coverage(gk, repo, rel):
    cli("report", "gap", rel, "--gap", "No payments refunds", "--severity", "critical", "--necessity", "must-have", "--benchmarks", "D2", cwd=repo)
    r = cli("report", "score", rel, "D2", "--score", "6", "--confidence", "high", cwd=repo, code=1)
    assert "D2-cap-1: Any critical gap (GAP-" in r.stderr


def test_validate_fails_a_format_5_score_above_its_limit(gk, repo, rel):
    r = load(repo, rel)
    b = next(b for b in r["benchmarks"] if b["id"] == "E1")
    b.update(score=8, confidence="high", caps_applied=["E1-cap-1"])
    errors, _ = gk.validate_report(r, config(gk), gk.load_catalog())
    assert "E1: score 8 is above its limit of 4 (E1-cap-1: Quickstart fails)" in errors


def test_4x_and_migrated_reports_keep_warnings(gk):
    r = json.loads(NEW.read_text())
    b = next(b for b in r["benchmarks"] if isinstance(b.get("score"), int) and b["score"] > 4)
    b["caps_applied"] = [f"{b['id']} house cap → max 2"]
    c = config(gk)
    errors, warnings = gk.validate_report(r, c, gk.load_catalog())
    assert not [e for e in errors if "above its limit" in e] and [w for w in warnings if "above its limit of 2" in w]
    migrated, _ = gk.migrate_report(r)
    assert not gk.limits_enforced(migrated)


def test_the_rollup_lists_limits_and_report_md_shows_them(gk, repo, rel):
    fid = add_quickstart_finding(repo, rel)
    r = load(repo, rel)
    for b in r["benchmarks"]:
        if b["applicability"] != "not_applicable":
            b["score"], b["confidence"] = (4 if b["id"] == "E1" else 7), "medium"
    c = config(gk)
    roll = gk.compute_rollup(r, c)
    assert roll["limits"]["E1"]["max"] == 4
    md = gk.render_report_md(r, c)
    assert f"- Limit: at most 4 while E1-cap-1: Quickstart fails ({fid})" in md
