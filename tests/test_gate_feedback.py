"""What the 5.0 release gate's calibration runs asked for: commands to correct a report, quotes kept short,
`report check` that isn't ready too early, top_priorities filled in, and fewer surprises around the run."""
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


def cli(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def js(*args, cwd, code=0):
    return json.loads(cli(*args, "--json", cwd=cwd, code=code).stdout)


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


@pytest.fixture
def code(tmp_path):
    d = tmp_path / "code"
    d.mkdir()
    (d / "m.py").write_text("def f(x):\n    y = x + 1\n    z = y * 2\n    return z\n\n\nprint(f(1))\n")
    return d


@pytest.fixture
def rel(repo):
    return js("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", cwd=repo)["result"]["report"]


def load(repo, rel):
    return json.loads((repo / rel).read_text())


def bench(report, bid):
    return next(b for b in report["benchmarks"] if b["id"] == bid)


# --------------------------------------------------------------------------- the command line

def test_out_creates_its_folder(repo):
    cli("resolve", "--project", "orders-api", "--out", "new/folder/eff.json", cwd=repo)
    assert json.loads((repo / "new" / "folder" / "eff.json").read_text())["hash"]


def test_a_stray_argument_is_reported_by_its_own_command(repo, rel):
    r = cli("report", "enforcement", rel, "A1", "--text", "t", "--absence", "a", "--method", "b", "--bogus", "x", cwd=repo, code=64)
    assert "usage: gradekit report enforcement" in r.stderr and "unrecognized arguments: --bogus x" in r.stderr


# --------------------------------------------------------------------------- enforcement is shaped like strengths

def test_enforcement_has_text_and_evidence(repo, rel, code):
    cli("report", "enforcement", rel, "A1", "--text", "CI runs the tests", "--cite", "m.py:7", "--repo", code, cwd=repo)
    assert bench(load(repo, rel), "A1")["enforcement"] == [
        {"note": "CI runs the tests", "evidence": [{"type": "code", "file": "m.py", "lines": "7", "quote": "print(f(1))"}]}]
    assert "--text" in cli("report", "enforcement", rel, "A1", "--cite", "m.py:7", "--repo", code, cwd=repo, code=64).stderr


def test_migrate_wraps_format_4_enforcement(gk):
    old = json.loads((EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json").read_text())
    ev = {"type": "command", "command": "ci", "excerpt": "ok", "note": "CI gate"}
    old["benchmarks"][0]["enforcement"] = [ev]
    new, notes = gk.migrate_report(old)
    assert new["benchmarks"][0]["enforcement"] == [{"note": "CI gate", "evidence": [ev]}]
    assert any("enforcement" in n for n in notes)
    assert gk.enforcement_items(old["benchmarks"][0]) == new["benchmarks"][0]["enforcement"], "format 4 still reads"


# --------------------------------------------------------------------------- show, update, remove

def test_show_numbers_what_update_and_remove_change(repo, rel, code):
    for text, line in (("first", "1-2"), ("second", "7")):
        cli("report", "strength", rel, "A1", "--text", text, "--cite", f"m.py:{line}", "--repo", code, cwd=repo)
    cli("report", "action", rel, "A1", "--action", "Fix the totals rounding", "--new-score", "7", "--effort", "S", cwd=repo)
    shown = cli("report", "show", rel, "A1", cwd=repo).stdout
    assert "A1/strength/1 first" in shown and "A1/strength/2 second" in shown and "A1-act-1 → 7" in shown

    cli("report", "update", rel, "A1/strength/2", "--text", "better", "--replace-evidence", "--cite", "m.py:4", "--repo", code, cwd=repo)
    s2 = bench(load(repo, rel), "A1")["strengths"][1]
    assert s2["note"] == "better" and [e["quote"] for e in s2["evidence"]] == ["    return z"]

    cli("report", "update", rel, "A1-act-1", "--optional", "--new-score", "8", "--why-first", "Cheap", cwd=repo)
    act = bench(load(repo, rel), "A1")["path_to_target"][0]
    assert act["optional"] is True and act["expected_new_score"] == 8 and act["why_first"] == "Cheap"
    cli("report", "update", rel, "A1-act-1", "--not-optional", cwd=repo)
    assert "optional" not in bench(load(repo, rel), "A1")["path_to_target"][0]

    wrong = cli("report", "update", rel, "A1-act-1", "--severity", "major", cwd=repo, code=1)
    assert "it has no --severity" in wrong.stderr

    cli("report", "remove", rel, "A1/strength/1", cwd=repo)
    assert [s["note"] for s in bench(load(repo, rel), "A1")["strengths"]] == ["better"]
    assert "has 1 strength" in cli("report", "remove", rel, "A1/strength/2", cwd=repo, code=1).stderr


def test_a_gap_can_be_corrected(repo, rel):
    gid = js("report", "gap", rel, "--gap", "No export", "--severity", "major", "--necessity", "must-have",
             "--benchmarks", "D1", cwd=repo)["result"]["id"]
    cli("report", "update", rel, gid, "--severity", "minor", "--necessity", "nice-to-have", cwd=repo)
    g = next(g for g in load(repo, rel)["gap_register"] if g["id"] == gid)
    assert (g["severity"], g["necessity"]) == ("minor", "nice-to-have")


def test_only_a_finding_new_to_this_report_can_be_removed(repo, rel, code):
    fid = js("report", "finding", "add", rel, "--benchmark", "A3", "--title", "x", "--severity", "minor",
             "--cite", "m.py:2", "--repo", code, cwd=repo)["result"]["id"]
    cli("report", "action", rel, "A3", "--action", "Fix the totals rounding", "--resolves", fid, "--new-score", "7", "--effort", "S", cwd=repo)
    out = cli("report", "remove", rel, fid, cwd=repo).stdout
    r = load(repo, rel)
    assert fid not in {f["id"] for f in r["findings"]} and fid not in bench(r, "A3")["finding_ids"]
    assert bench(r, "A3")["path_to_target"][0]["resolves"] == [] and "no longer resolves it" in out

    cli("report", "finding", "add", rel, "--benchmark", "A1", "--id", "A1-001", "--status", "open", "--title", "kept",
        "--severity", "minor", "--cite", "m.py:2", "--repo", code, cwd=repo)
    refused = cli("report", "remove", rel, "A1-001", cwd=repo, code=1)
    assert "earlier report" in refused.stderr and "finding update" in refused.stderr


# --------------------------------------------------------------------------- quotes

def test_a_quote_is_three_lines_at_most(code):
    r = cli("report", "cite", "m.py:1-4", "--repo", code, cwd=code)   # 5.0: kept to its first three lines, with a note
    assert json.loads(r.stdout)["lines"] == "1-3" and "a quote is at most 3: cited m.py:1-3" in r.stderr
    trimmed = json.loads(cli("report", "cite", "m.py:3-6", "--repo", code, cwd=code).stdout)
    assert trimmed["lines"] == "3-4" and trimmed["quote"] == "    z = y * 2\n    return z", "blank lines at the ends are dropped"


def test_validate_warns_about_long_quotes(gk, repo, rel, code):
    r = load(repo, rel)
    bench(r, "A1")["strengths"] = [{"note": "x", "evidence": [{"type": "code", "file": "m.py", "lines": "1-4",
                                                               "quote": "def f(x):\n    y = x + 1\n    z = y * 2\n    return z"}]}]
    cfg = gk.resolve_config([str(repo / PROJ / "project.toml")])
    _, warnings = gk.validate_report(r, cfg, gk.load_catalog())
    assert any("longer than 3 lines" in w and "A1 strength #1" in w for w in warnings)


# --------------------------------------------------------------------------- report check and the rollup

def test_check_wants_a_summary_and_a_path_for_each_benchmark_below_target(repo, rel):
    todo = js("report", "check", rel, cwd=repo, code=5)["result"]["todo"]
    assert any(t.startswith("write the summary") for t in todo)
    cli("report", "score", rel, "A1", "--score", "3", "--confidence", "medium", cwd=repo)
    todo = js("report", "check", rel, cwd=repo, code=5)["result"]["todo"]
    assert any(t.startswith("A1: 3 is below its target") for t in todo)
    cli("report", "action", rel, "A1", "--action", "Add property tests later", "--new-score", "9", "--effort", "S", "--optional", cwd=repo)
    assert any(t.startswith("A1: 3 is below") for t in js("report", "check", rel, cwd=repo, code=5)["result"]["todo"]), \
        "an optional action isn't a path to the target"
    cli("report", "action", rel, "A1", "--action", "Fix the totals rounding", "--new-score", "8", "--effort", "S", cwd=repo)
    assert not any(t.startswith("A1:") for t in js("report", "check", rel, cwd=repo, code=5)["result"]["todo"])


def two_steps(gk, fmt):
    cfg = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    r = json.loads((EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json").read_text())
    if fmt == 5:
        r, _ = gk.migrate_report(r)
    b = bench(r, "C4")
    b["score"] = 4
    b["path_to_target"] = [
        {"id": "C4-act-1", "action": "a", "resolves": [], "expected_new_score": 6, "effort": "S", "requires_human_decision": False},
        {"id": "C4-act-2", "action": "b", "resolves": [], "expected_new_score": 8, "effort": "S", "requires_human_decision": False}]
    roll = gk.compute_rollup(r, cfg)
    return {p["action_id"]: p["gain"] for p in roll["priorities"] if p["benchmark_id"] == "C4"}, r, cfg


def test_each_action_gains_only_what_it_adds(gk):
    gains, r, cfg = two_steps(gk, 5)
    tv = gk.compute_rollup(r, cfg)["targets"]["C4"]
    assert tv >= 8, "the example's C4 target leaves room for both steps"
    assert gains == {"C4-act-1": 2, "C4-act-2": 2}
    old, *_ = two_steps(gk, 4)
    assert old == {"C4-act-1": 2, "C4-act-2": 4}, "format-4 reports keep the gains their stored rollups have"


def test_a_lower_score_after_an_earlier_action_is_flagged(gk):
    _, r, cfg = two_steps(gk, 5)
    bench(r, "C4")["path_to_target"][1]["expected_new_score"] = 5
    _, warnings = gk.validate_report(r, cfg, gk.load_catalog())
    assert any("C4-act-2" in w and "earlier action" in w for w in warnings)


def test_check_write_fills_top_priorities(gk):
    _, r, cfg = two_steps(gk, 5)
    bench(r, "C4")["path_to_target"][0]["why_first"] = "The one test proves nothing"
    gk.apply_rollup(r, cfg)
    top = r["top_priorities"]
    assert len(top) == min(10, len(r["rollup"]["priorities"]))
    assert [p["action_id"] for p in top] == [p["action_id"] for p in r["rollup"]["priorities"][:10]]
    mine = next(p for p in top if p["action_id"] == "C4-act-1")
    assert mine["why_first"] == "The one test proves nothing" and mine["expected_gain"] == "+2 on C4"
    assert all(p["why_first"] for p in top)
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert not [e for e in errors if "top_priorities" in e]


# --------------------------------------------------------------------------- the run

def test_redact_makes_no_private_file_when_nothing_is_withheld(repo, rel):
    out = cli("redact", rel, "--in-place", cwd=repo).stdout
    assert "nothing to withhold" in out and not (repo / rel).with_name("report.private.json").exists()
    assert load(repo, rel)["publishing"] == {"redacted": True, "withheld": []}


def test_started_counts_the_minutes_from_preflight(repo):
    r = js("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m",
           "--started", "2026-01-02T03:04:05Z", cwd=repo)["result"]["report"]
    assert load(repo, r)["run"]["started"] == "2026-01-02T03:04:05Z"
    late = cli("report", "new", "--project", "orders-api", "--commit", "c3d4e5f", "--started", "2999-01-01T00:00:00Z", cwd=repo, code=1)
    assert "later than now" in late.stderr
    assert "UTC time" in cli("report", "new", "--project", "orders-api", "--commit", "c3d4e5f", "--started", "monday", cwd=repo, code=1).stderr


def test_doctor_warns_when_hot_zones_cover_most_of_the_code(gk, tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text("a = 1\n" * 90)
    (tmp_path / "setup.py").write_text("b = 2\n" * 10)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("c = 3\n" * 500)
    cfg = {"zones": {"list": [{"name": "core", "criticality": "hot", "paths": ["pkg/**"]}], "default": "normal"}}
    share = gk.hot_share(tmp_path, cfg)
    assert share["share"] == 0.9 and share["files"] == ["pkg/core.py"], "tests don't count as the code"
    cfg["zones"]["list"][0]["paths"] = ["nothing/**"]
    assert gk.hot_share(tmp_path, cfg)["share"] == 0


# --------------------------------------------------------------------------- one version on every label

def test_every_version_label_is_the_kits():
    version = json.loads((SRC / "rubric" / "catalog.json").read_text())["suite_version"]
    labels = {}
    for f in [*SRC.glob("*.md"), *(SRC / "prompts").glob("*.md"), *(SRC / "rubric").glob("*.md"), SRC / "config" / "defaults.toml"]:
        if f.name == "CHANGELOG.md":
            continue
        for m in re.finditer(r"Code Grading Suite v(\d+\.\d+\.\d+)|\(suite v(\d+\.\d+\.\d+)\)", f.read_text(encoding="utf-8")):
            labels[f.relative_to(SRC).as_posix()] = m.group(1) or m.group(2)
    assert labels and {f: v for f, v in labels.items() if v != version} == {}
