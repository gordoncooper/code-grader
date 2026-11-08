"""The preflight (4.3): `gradekit doctor`."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def env(path=None, **extra):
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", **extra)
    if path:
        e["PATH"] = f"{path}{os.pathsep}{e['PATH']}"
    return e


def doctor(*args, cwd=EXAMPLE, kit=SRC, path=None, **extra):
    r = subprocess.run([sys.executable, str(kit / "tools" / "gradekit.py"), "doctor", *map(str, args), "--json"],
                       cwd=cwd, env=env(path, **extra), capture_output=True, text=True)
    out = json.loads(r.stdout)
    assert out["exit_code"] == r.returncode
    return out["result"], {c["check"]: c for c in out["result"]["checks"]}


def test_basics_and_project():
    res, c = doctor("--project", "orders-api", "--repo", "../sample-repo")
    assert res["ready"]
    for name in ("python", "kit", "temp", "config", "project folder", "previous report", "code repo"):
        assert c[name]["status"] == "ok", c[name]
    assert "2026-11-07-a1b2c3d" in c["previous report"]["detail"]


def test_problems_come_with_fixes(tmp_path):
    g = tmp_path / "g"
    shutil.copytree(EXAMPLE, g)
    (g / "projects" / "orders-api" / "project.toml").write_text("[project]\nname = 'x'\npreset = 'nope'\n")
    res, c = doctor("--project", "orders-api", "--repo", tmp_path / "missing", cwd=g)
    assert not res["ready"]
    assert c["config"]["status"] == "fail" and c["config"]["fix"]
    assert c["code repo"]["status"] == "fail" and "--repo" in c["code repo"]["fix"]


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=env(**GIT_ENV), capture_output=True, text=True, check=True).stdout


@pytest.fixture
def grading(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    git(g, "init", "-q", "-b", "main")
    git(g, "add", "-A")
    git(g, "commit", "-qm", "init")
    git(g, "remote", "add", "origin", str(remote))
    git(g, "push", "-q", "origin", "main")
    return g


def test_pr_delivery_checks_git_and_push(grading):
    git(grading, "config", "user.name", "Grader")
    git(grading, "config", "user.email", "grader@example.com")
    res, c = doctor("--project", "orders-api", "--delivery", "pr", cwd=grading)
    assert res["ready"], c
    assert c["git identity"]["detail"] == "Grader <grader@example.com>"
    assert c["remote read"]["status"] == "ok" and "main" in c["remote read"]["detail"]
    assert c["remote push"]["status"] == "ok"
    assert "gradekit-doctor" not in git(grading, "ls-remote", "origin"), "the push check is a dry run"


def test_pr_delivery_problems(grading, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    git(grading, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    _, c = doctor("--project", "orders-api", "--delivery", "pr", cwd=grading, HOME=str(home), GIT_CONFIG_NOSYSTEM="1",
                  XDG_CONFIG_HOME=str(home))
    assert c["git identity"]["status"] == "fail" and "user.email" in c["git identity"]["fix"]
    assert c["remote read"]["status"] == "fail"
    _, c = doctor("--delivery", "pr", cwd=tmp_path)
    assert c["grading repo"]["status"] == "fail" and "save or return" in c["grading repo"]["fix"]


def test_open_checks_the_cli_sign_in(grading, tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "glab").write_text("#!/bin/sh\necho 'You are not logged into any GitLab hosts' >&2\nexit 1\n")
    (bin_ / "glab").chmod(0o755)
    git(grading, "config", "user.name", "G")
    git(grading, "config", "user.email", "g@g")
    res, c = doctor("--project", "orders-api", "--delivery", "pr", "--open", "gitlab", cwd=grading, path=bin_)
    assert not res["ready"] and c["glab"]["status"] == "fail" and "not logged" in c["glab"]["detail"]


def test_site_version_and_kit_files(static_site, tmp_path):
    res, c = doctor("--site", static_site)
    assert c["suite website"]["status"] == "ok" and c["kit files"]["status"] == "ok", c
    kit = tmp_path / "kit"
    shutil.copytree(SRC, kit)
    (kit / "prompts" / "grader.md").write_text("changed\n")
    _, c = doctor("--site", static_site, kit=kit)
    assert c["kit files"]["status"] == "warn" and "prompts/grader.md" in c["kit files"]["detail"]
    _, c = doctor("--site", "http://127.0.0.1:9/none")
    assert c["suite website"]["status"] == "fail" and "allowlist" in c["suite website"]["fix"]
