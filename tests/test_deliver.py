"""Handing reports back (4.3): `gradekit deliver`."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
CODE = EXAMPLE.parent / "sample-repo"
FOLDER = "projects/orders-api/reports/2026-11-09-c3d4e5f"


def env(extra_path=None):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
    if extra_path:
        e["PATH"] = f"{extra_path}{os.pathsep}{e['PATH']}"
    return e


def gk(*args, cwd, ok=True, path=None):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=env(path), capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], env=env(), capture_output=True, text=True, check=True).stdout.strip()


def finished_report(grading):
    """A report that needs only delivery: the example's latest, as a fresh full grade with a sensitive finding."""
    from test_publishing import full_report
    r = full_report()
    r["run"]["commit"] = "c3d4e5f6a7"
    r["run"]["date"] = "2026-11-09T10:00:00Z"
    r["rollup"] = None
    folder = grading / FOLDER
    folder.mkdir(parents=True)
    (folder / "report.json").write_text(json.dumps(r, indent=2))
    return f"{FOLDER}/report.json"


@pytest.fixture
def grading(tmp_path):
    """The example grading repo as a git repo with an origin (a bare repo), minus its .gitignore."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    (g / ".gitignore").unlink()
    git(g, "init", "-q", "-b", "main")
    git(g, "add", "-A")
    git(g, "commit", "-qm", "init")
    git(g, "remote", "add", "origin", str(remote))
    git(g, "push", "-q", "-u", "origin", "main")
    git(g, "remote", "set-head", "origin", "main")
    return g


def test_unfinished_reports_are_not_delivered(grading):
    rel = finished_report(grading)
    r = json.loads((grading / rel).read_text())
    r["scope_examined"] = ""
    (grading / rel).write_text(json.dumps(r))
    out = gk("deliver", rel, "--json", cwd=grading, ok=False)
    env_ = json.loads(out.stdout)
    assert out.returncode == 5 and env_["result"]["delivered"] is False and env_["result"]["todo"]


def test_pr_prints_the_steps_without_run(grading):
    rel = finished_report(grading)
    res = json.loads(gk("deliver", rel, "--json", cwd=grading).stdout)["result"]
    assert res["branch"] == "report/orders-api/2026-11-09-c3d4e5f" and res["base"] == "main"
    assert res["title"].startswith("Report: orders-api 2026-11-09 — ")
    assert any(c.startswith("git -C") and " switch -c report/orders-api/2026-11-09-c3d4e5f origin/main" in c for c in res["commands"])
    assert git(grading, "rev-parse", "--abbrev-ref", "HEAD") == "main", "nothing is run without --run"
    folder = grading / FOLDER
    assert (folder / "report.md").exists() and (folder / "report.private.json").exists()
    assert json.loads((folder / "report.json").read_text())["publishing"]["redacted"] is True
    assert "A3-001" in open(res["body_file"]).read() or "Decisions needed" in open(res["body_file"]).read()


def test_pr_run_push_commits_only_the_public_folder(grading):
    rel = finished_report(grading)
    res = json.loads(gk("deliver", rel, "--run", "--push", "--repo", CODE, "--json", cwd=grading).stdout)["result"]
    assert res["delivered"] and res["pushed"]
    files = git(grading, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert sorted(files) == [f"{FOLDER}/report.json", f"{FOLDER}/report.md"]
    assert git(grading, "log", "-1", "--format=%s") == res["title"]
    assert git(grading, "ls-remote", "origin", "refs/heads/report/orders-api/2026-11-09-c3d4e5f").startswith(res["commit"])
    assert git(grading, "rev-parse", "origin/main") == git(grading, "rev-parse", "main"), "main is never touched"
    again = json.loads(gk("deliver", rel, "--run", "--push", "--json", cwd=grading).stdout)["result"]
    assert again["commit"] == res["commit"], "running it again changes nothing"


@pytest.mark.parametrize("host, tool", [("github", "gh"), ("gitlab", "glab")])
def test_open_uses_the_hosts_cli(grading, tmp_path, host, tool):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / f"{tool}.log"
    fake = bin_ / tool
    fake.write_text(f"#!/bin/sh\necho \"$@\" > {log}\necho https://example.com/acme/grading/pull/7\n")
    fake.chmod(0o755)
    rel = finished_report(grading)
    res = json.loads(gk("deliver", rel, "--run", "--push", "--open", host, "--json", cwd=grading, path=bin_).stdout)["result"]
    assert res["url"] == "https://example.com/acme/grading/pull/7"
    called = log.read_text()
    assert "report/orders-api/2026-11-09-c3d4e5f" in called and "main" in called and "Report: orders-api" in called


def test_never_onto_the_default_branch(grading):
    rel = finished_report(grading)
    r = gk("deliver", rel, "--branch", "main", cwd=grading, ok=False)
    assert r.returncode == 1 and "default branch" in r.stderr


def test_return_prints_the_blocks(grading):
    rel = finished_report(grading)
    res = json.loads(gk("deliver", rel, "--delivery", "return", "--json", cwd=grading).stdout)["result"]
    names = [b["name"] for b in res["blocks"]]
    assert names == ["report.json", "report.md", "report.private.json (private: don't commit)"]
    assert json.loads(res["blocks"][0]["content"])["publishing"]["redacted"] is True


def test_save_without_git(tmp_path):
    g = tmp_path / "files-only"
    shutil.copytree(EXAMPLE, g)
    rel = finished_report(g)
    res = json.loads(gk("deliver", rel, "--delivery", "save", "--json", cwd=g).stdout)["result"]
    assert res["delivered"] and res["folder"].endswith("2026-11-09-c3d4e5f") and res["files"]["private"]


def test_flags_that_need_run(grading):
    rel = finished_report(grading)
    assert "--run" in gk("deliver", rel, "--push", cwd=grading, ok=False).stderr
