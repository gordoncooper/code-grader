"""run.citations_checked (5.0.1): the report records that its code quotes were checked against the code, so
`gradekit ci`, which can't see the code, can say when they weren't. The lighter alternative to CI reading code."""
import json
import subprocess
import sys

from conftest import SRC
from test_scoring_bypasses import ready  # noqa: F401  (fixture)

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
CODE = SRC / "examples" / "sample-repo"


def run(*args, cwd):
    return subprocess.run(KIT + [str(a) for a in args], cwd=cwd, capture_output=True, text=True)


def rec(repo, rel):
    return json.loads((repo / rel).read_text())["run"].get("citations_checked")


def test_check_with_the_code_records_it_and_an_edit_drops_it(ready):
    repo, rel = ready
    assert rec(repo, rel) is None, "checked without --repo: nothing recorded"
    out = run("report", "check", rel, "--repo", CODE, "--write", cwd=repo)
    assert out.returncode == 0, out.stdout + out.stderr
    r = rec(repo, rel)
    assert r["code_citations"] == 1 and r["kit"] and r["date"]
    run("report", "set", rel, "summary", "Small, and one thin test.", cwd=repo)
    assert rec(repo, rel) is None, "the quotes may have changed"


def test_deliver_with_the_code_records_it(ready):
    repo, rel = ready
    out = run("deliver", rel, "--delivery", "save", "--repo", CODE, cwd=repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert rec(repo, rel)["code_citations"] == 1


def test_ci_says_when_quotes_werent_checked_or_changed(gk, ready):
    repo, rel = ready
    r = json.loads((repo / rel).read_text())
    assert gk.citations_check_note(r).startswith("its code quote wasn't checked against the code: the grader runs")
    r["run"]["citations_checked"] = {"code_citations": 1, "date": "2026-11-10T00:00:00Z", "kit": "5.0.1"}
    assert gk.citations_check_note(r) is None
    r["run"]["citations_checked"]["code_citations"] = 3
    assert "changed after they were checked against the code (3 then, 1 now)" in gk.citations_check_note(r)
    r.pop("schema_version")
    assert gk.citations_check_note(r) is None, "4.x reports never had the record"
