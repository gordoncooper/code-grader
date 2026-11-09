"""The gradekit command line, as agents and people run it."""
import json
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
    """It changes only with the config or the scoring rules: 99965e… under scoring 5.0, c068… (the example reports') under 4.x."""
    assert "Effective config 99965e49bb3352f4" in run("resolve", "--project", "orders-api").stdout


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


# --------------------------------------------------------------------------- --json everywhere (4.3)

class _Stop(Exception):
    pass



def leaf_commands():
    """Every leaf command, as an argv prefix, read from the real parser."""
    import argparse
    sys.path.insert(0, str(SRC / "tools"))
    import gradekit
    built = {"ap": gradekit.build_parser()}

    def walk(parser, prefix):
        subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            yield prefix, parser
        for a in subs:
            for name, sp in a.choices.items():
                yield from walk(sp, prefix + [name])
    return list(walk(built["ap"], []))


def test_every_command_takes_json():
    leaves = leaf_commands()
    assert len(leaves) >= 30
    for argv, parser in leaves:
        assert any("--json" in a.option_strings for a in parser._actions), " ".join(argv)


def test_json_envelope_on_success_and_failure(tmp_path):
    ok = json.loads(run("validate", "--project", "orders-api", "--json").stdout)
    assert ok["ok"] is True and ok["exit_code"] == 0 and ok["command"] == "validate"
    assert ok["result"]["valid"] and ok["result"]["config_hash"] and "0 error(s)" in ok["text"]
    d = run("diff", "--project", "orders-api", "--fail-on-regression", "--json")
    env = json.loads(d.stdout)
    assert d.returncode == env["exit_code"] == 2 and env["result"]["verdict"] == "FAIL" and env["result"]["regressions"]
    bad = run("validate", str(tmp_path / "missing.json"), "--json")
    env = json.loads(bad.stdout)
    assert bad.returncode == 1 and env["ok"] is False and "error" in env and env["result"] is None


@pytest.mark.parametrize("argv, key", [
    (["resolve", "--project", "orders-api"], "config"),
    (["presets"], "weights"),
    (["rollup", "--project", "orders-api"], "rollup"),
    (["verify-evidence", "--project", "orders-api", "--repo", "../sample-repo"], "checked"),
    (["stability", "projects/orders-api/reports/2026-10-24-9f8e7d6/report.json",
      "projects/orders-api/reports/2026-11-07-a1b2c3d/report.json", "--project", "orders-api"], "unstable"),
    (["render", "pr", "projects/orders-api/reports/2026-11-07-a1b2c3d/report.json"], "title"),
])
def test_json_results_are_structured(argv, key):
    env = json.loads(run(*argv, "--json").stdout)
    assert env["ok"], env
    assert key in env["result"]


def test_bad_arguments_exit_64():
    r = run("validate", "--no-such-flag")
    assert r.returncode == 64 and "usage:" in r.stderr
