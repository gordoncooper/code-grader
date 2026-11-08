"""The gradekit command line, as agents and people run it."""
import os
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def run(*args, cwd=EXAMPLE):
    return subprocess.run(KIT + list(args), cwd=cwd, env=ENV, capture_output=True, text=True)


@pytest.mark.parametrize("args", [
    ["validate", "--project", "orders-api"],
    ["verify-evidence", "--project", "orders-api", "--repo", "../sample-repo"],
    ["rollup", "--project", "orders-api"],
    ["resolve", "--project", "orders-api"],
    ["presets"],
    ["diff", "--project", "orders-api"],
])
def test_commands_succeed_on_the_example(args):
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr


def test_validate_reports_no_errors():
    assert "0 error(s), 0 warning(s)" in run("validate", "--project", "orders-api").stdout


def test_diff_fails_on_regression_when_asked():
    r = run("diff", "--project", "orders-api", "--fail-on-regression")
    assert r.returncode == 2 and "verdict: FAIL" in r.stdout


def test_resolve_fingerprint_is_stable():
    assert "Effective config c068a92b5feead6f" in run("resolve", "--project", "orders-api").stdout


def test_init_creates_a_project_folder(tmp_path):
    r = run("init", "--preset", "service", "--project", "demo", "--code-repo", "https://example.com/demo", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    folder = tmp_path / "projects" / "demo"
    assert {p.name for p in folder.iterdir()} >= {"project.toml", "decisions.json", "dispositions.json", "reports"}
    assert "projects/demo/project.toml" in (folder / "project.toml").read_text() or "--project demo" in (folder / "project.toml").read_text()
    assert run("resolve", "--project", "demo", cwd=tmp_path).returncode == 0


def test_runs_on_python_311_syntax():
    """The kit promises Python 3.11+: compile it with the oldest supported grammar."""
    import ast
    ast.parse((SRC / "tools" / "gradekit.py").read_text(), feature_version=(3, 11))
