"""Carrying a report forward (4.3): `gradekit carry` and `gradekit report match`."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

PROJECT = EXAMPLE / "projects" / "orders-api"
NEW = PROJECT / "reports" / "2026-11-07-a1b2c3d" / "report.json"
CODE = EXAMPLE.parent / "sample-repo"
KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t")


def gk(*args, ok=True, cwd=EXAMPLE):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def changed_repo(tmp_path):
    """The sample repo in git, then a change: lines added above everything in service.py,
    the cited charge line edited, and seed.sql deleted. Returns (repo, base, head)."""
    repo = tmp_path / "code"
    shutil.copytree(CODE, repo)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    svc = repo / "src" / "orders" / "service.py"
    svc.write_text("import logging\n\nlog = logging.getLogger(__name__)\n\n" + svc.read_text())
    api = repo / "src" / "payments" / "api.py"
    api.write_text(api.read_text().replace('gateway.charge(request.json["amount"])', 'gateway.charge(validate(request.json["amount"]))'))
    (repo / "scripts" / "seed.sql").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")
    return repo, base, git(repo, "rev-parse", "HEAD")


# --------------------------------------------------------------------------- relocation

def reader(lines):
    return lambda rel: lines if rel == "f.py" else "file not found: " + rel


def ev(lines, quote):
    return {"type": "code", "file": "f.py", "lines": lines, "quote": quote, "note": "n"}


@pytest.mark.parametrize("old, quote, now, outcome, expect_lines", [
    ("2", "b = 2", ["a = 1", "b = 2"], "unchanged", "2"),
    ("2", "b = 2", ["x", "y", "a = 1", "b = 2"], "moved", "4"),
    ("2-3", "b = 2\nc = 3", ["new", "a = 1", "b = 2", "c = 3"], "moved", "3-4"),
    ("1", "charge(amount", ["# hi", "result = charge(amount)"], "moved", "2"),          # part of a line
    ("1", "result = charge(amount)", ["# hi", "result = charge(check(amount))"], "changed", "2"),
    ("1", "gone()", ["other()"], "lost", "1"),
])
def test_relocate(gk, old, quote, now, outcome, expect_lines):
    new, got = gk.relocate_evidence(ev(old, quote), reader(now))
    assert got == outcome and new["lines"] == expect_lines
    if outcome in ("unchanged", "moved"):
        assert new["quote"] == quote, "a quote that still matches is kept as the grader wrote it"
    if outcome == "changed":
        assert new["quote"] == now[1]
    assert new["note"] == "n"


def test_relocate_picks_the_nearest_copy(gk):
    now = ["x = 1", "", "", "", "", "", "", "", "x = 1"]
    assert gk.relocate_evidence(ev("8", "x = 1"), reader(now))[0]["lines"] == "9"


def test_relocate_a_missing_file(gk):
    assert gk.relocate_evidence({**ev("1", "a"), "file": "nope.py"}, reader([]))[1] == "lost"


# --------------------------------------------------------------------------- carry

def carried(tmp_path, changed_repo, *extra):
    repo, base, head = changed_repo
    out = tmp_path / "pr.json"
    res = json.loads(gk("carry", NEW, "--model", "test-model", "--repo", repo, "--commit", head, "--base-commit", base, "--out", out,
                        "--allow-withheld", "--json", *extra).stdout)["result"]
    return res, json.loads(out.read_text())


def test_pr_carry_keeps_ids_and_moves_citations(tmp_path, changed_repo):
    res, r = carried(tmp_path, changed_repo)
    base = json.loads(NEW.read_text())
    assert [f["id"] for f in r["findings"]] == [f["id"] for f in base["findings"]]
    assert all(f["status"] != "new" for f in r["findings"])
    assert "rollup" not in r and "publishing" not in r and r["mode"] == "pr"
    assert r["run"]["commit"] == changed_repo[2] and r["run"]["base_commit"] == changed_repo[1]
    a1 = next(f for f in r["findings"] if f["id"] == "A1-001")["evidence"][0]
    old_a1 = next(f for f in base["findings"] if f["id"] == "A1-001")["evidence"][0]
    a, b = (int(x) for x in old_a1["lines"].split("-"))
    assert a1["lines"] == f"{a + 4}-{b + 4}" and a1["quote"] == old_a1["quote"]
    assert any("A4-001" in x and "seed.sql" in x for x in res["evidence"]["lost"])
    assert any("B5-001" in x for x in res["evidence"]["changed"])


def test_pr_carry_suggests_what_to_regrade(tmp_path, changed_repo):
    res, r = carried(tmp_path, changed_repo, "--touched", "E2")
    assert sorted(res["changed_files"]) == ["scripts/seed.sql", "src/orders/service.py", "src/payments/api.py"]
    regrade = set(res["regrade"])
    assert {"A1", "A3", "C1", "C2", "C3", "C4"} <= regrade, "always re-graded when code changes"
    assert {"A2", "A4", "A5"} <= regrade, "gates, because hot-zone files changed"
    assert "X3" in regrade and "E2" in regrade and "E1" not in regrade
    base = {b["id"]: b for b in json.loads(NEW.read_text())["benchmarks"]}
    for b in r["benchmarks"]:
        assert b["previous_score"] == base[b["id"]]["score"]
        if b["id"] in regrade:
            assert not b["carried_forward"] and (b["score"] is None or b["applicability"] == "not_applicable")
        else:
            assert b["carried_forward"] and b["score"] == base[b["id"]]["score"]


def test_carry_refuses_a_public_copy_by_default(tmp_path, changed_repo):
    repo, base, head = changed_repo
    r = gk("carry", NEW, "--repo", repo, "--commit", head, "--base-commit", base, "--out", tmp_path / "x.json", ok=False)
    assert r.returncode == 1 and "report.private.json" in r.stderr


def test_full_carry_makes_the_next_report_folder(tmp_path, changed_repo):
    repo, base, head = changed_repo
    grading = tmp_path / "grading"
    shutil.copytree(EXAMPLE, grading)
    src = grading / "projects" / "orders-api" / "reports" / "2026-11-07-a1b2c3d" / "report.json"
    res = json.loads(gk("carry", src, "--model", "test-model", "--mode", "full", "--repo", repo, "--commit", head, "--allow-withheld", "--json", cwd=grading).stdout)["result"]
    assert res["report"].endswith(f"-{head[:7]}/report.json")
    r = json.loads((grading / res["report"]).read_text() if not os.path.isabs(res["report"]) else open(res["report"]).read())
    assert all(b["score"] is None and not b["carried_forward"] for b in r["benchmarks"])
    assert r["metrics"] == {} and r["limitations"] == []
    assert len(r["findings"]) == len(json.loads(NEW.read_text())["findings"])


def test_a_pr_check_from_carry_to_comment(tmp_path, changed_repo):
    """The whole PR check with kit commands only: carry, re-grade, check, diff, comment."""
    repo, _, _ = changed_repo
    _, r = carried(tmp_path, changed_repo)
    pr = tmp_path / "pr.json"
    base = {b["id"]: b for b in json.loads(NEW.read_text())["benchmarks"]}
    gk("report", "finding", "update", pr, "A4-001", "--status", "fixed", "--replace-evidence",
       "--absence", "scripts/seed.sql", "--method", "deleted by this change", "--project", "orders-api")
    for b in r["benchmarks"]:
        if not b["carried_forward"] and b["applicability"] != "not_applicable":
            gk("report", "score", pr, b["id"], "--score", base[b["id"]]["score"], "--confidence", "medium", "--project", "orders-api")
    gk("report", "ran", pr, "--command-text", "pytest -q", "--summary", "1 passed", "--project", "orders-api")
    gk("report", "set", pr, "summary", "The seed script is gone, and A4-001 with it.", "--project", "orders-api")
    for b in json.loads(pr.read_text())["benchmarks"]:   # a regraded benchmark below target needs its path again
        if not b["carried_forward"] and isinstance(b["score"], int) and isinstance(b["target"], int) and b["score"] < b["target"] \
                and not b["path_to_target"]:
            gk("report", "action", pr, b["id"], "--action", "Raise it to the target", "--new-score", b["target"], "--effort", "M",
               "--project", "orders-api")
    done = json.loads(gk("report", "check", pr, "--repo", repo, "--project", "orders-api", "--write", "--json").stdout)["result"]
    assert done["status"] == "ready", done
    d = gk("diff", NEW, pr, "--project", "orders-api", "--fail-on-regression")
    assert "verdict: PASS" in d.stdout, d.stdout
    comment = gk("render", "check", NEW, pr, "--project", "orders-api").stdout
    assert comment.startswith("**PR check: PASS**") and "(others carried forward)" in comment


# --------------------------------------------------------------------------- matching

def renamed(tmp_path, mapping):
    r = json.loads(NEW.read_text())
    for f in r["findings"]:
        if f["id"] in mapping:
            f["id"], f["title"] = mapping[f["id"]]
            f["status"] = "new"
    for b in r["benchmarks"]:
        b["finding_ids"] = [mapping.get(i, (i,))[0] for i in b["finding_ids"]]
        for a in b["path_to_target"]:
            a["resolves"] = [mapping.get(i, (i,))[0] for i in a["resolves"]]
    p = tmp_path / "fresh.json"
    p.write_text(json.dumps(r))
    return p


def test_match_finds_reworded_findings_and_applies_clear_ones(tmp_path):
    p = renamed(tmp_path, {"A3-001": ("A3-007", "Errors from stock reservation are swallowed silently"),
                           "D1-001": ("D1-004", "Export to XLSX is advertised in the README but missing")})
    res = json.loads(gk("report", "match", p, "--baseline", NEW, "--project", "orders-api", "--apply", "--json").stdout)["result"]
    pairs = {m["new"]: m["old"] for m in res["matches"]}
    assert pairs == {"A3-007": "A3-001", "D1-004": "D1-001"}
    r = json.loads(p.read_text())
    ids = {f["id"] for f in r["findings"]}
    assert {"A3-001", "D1-001"} <= ids and not {"A3-007", "D1-004"} & ids
    a3 = next(f for f in r["findings"] if f["id"] == "A3-001")
    assert a3["status"] == "open" and a3["first_seen_commit"] == "9f8e7d6"
    d1 = next(b for b in r["benchmarks"] if b["id"] == "D1")
    assert d1["path_to_target"][0]["resolves"] == ["D1-001"]


def test_match_needs_the_same_benchmark(gk):
    a = {"id": "A3-009", "benchmark_id": "A3", "title": "No CI", "evidence": []}
    b = {"id": "F2-001", "benchmark_id": "F2", "title": "No CI", "evidence": []}
    assert gk.finding_similarity(a, b) == 0.0
