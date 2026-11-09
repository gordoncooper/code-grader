"""Grading on a schedule (5.0, N2), and the time and cost of runs in the index (N3)."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
PROJ = "projects/orders-api"
LAST = "2026-11-07"   # the example's newest full grade, of commit a1b2c3d


def cli(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def due(repo, *args):
    return json.loads(cli("due", *args, "--json", cwd=repo).stdout)["result"]


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "grading")
    return tmp_path / "grading"


def schedule(repo, every=30, only_if_code_changed=None, project="orders-api"):
    toml = repo / "projects" / project / "project.toml"
    extra = f"\n[schedule]\ngrade_every_days = {every}\n" + ("" if only_if_code_changed is None else f"only_if_code_changed = {str(only_if_code_changed).lower()}\n")
    toml.write_text(toml.read_text() + extra)


def row(res, name="orders-api"):
    return next(r for r in res["projects"] if r["project"] == name)


def test_no_schedule_means_never_due(repo):
    r = row(due(repo, "--today", "2027-06-01"))
    assert not r["due"] and "no schedule" in r["reason"]


def test_not_due_before_the_interval(repo):
    schedule(repo)
    r = row(due(repo, "--today", "2026-11-20", "--code-head", "orders-api=ffffffffff"))
    assert not r["due"] and r["days_since"] == 13 and "next after 30" in r["reason"]


def test_due_after_the_interval_only_if_the_code_moved(repo):
    schedule(repo)
    unknown = row(due(repo, "--today", "2026-12-10"))
    assert not unknown["due"] and "--check-code" in unknown["reason"], "never guesses that the code changed"
    same = row(due(repo, "--today", "2026-12-10", "--code-head", "orders-api=a1b2c3d4e5f6"))
    assert not same["due"] and "hasn't changed" in same["reason"]
    moved = row(due(repo, "--today", "2026-12-10", "--code-head", "orders-api=0badc0ffee11"))
    assert moved["due"] and "33 days" in moved["reason"] and "a1b2c3d to 0badc0f" in moved["reason"]


def test_due_by_time_alone_when_asked(repo):
    schedule(repo, only_if_code_changed=False)
    assert row(due(repo, "--today", "2026-12-07"))["due"]


def test_never_graded_is_due(repo):
    cli("init", "--project", "billing", "--code-repo", "https://example.com/billing", cwd=repo)
    schedule(repo, project="billing")
    r = row(due(repo, "--today", "2026-12-01"), "billing")
    assert r["due"] and r["reason"] == "never graded"


def test_write_orders_asks_once(repo):
    import jsonschema
    schedule(repo)
    res = due(repo, "--today", "2026-12-10", "--code-head", "orders-api=0badc0ffee11", "--write-orders")
    oid = row(res)["order"]
    order = json.loads((repo / PROJ / "orders" / f"{oid}.json").read_text())
    jsonschema.validate(order, json.loads((SRC / "schema" / "work-order.schema.json").read_text()))
    assert (order["role"], order["requested_by"], order["commit"], order["delivery"]) == ("grade", "schedule", "0badc0ffee11", "pr")
    assert order["notes"].startswith("Scheduled grade: 33 days since the last grade")
    again = row(due(repo, "--today", "2026-12-10", "--code-head", "orders-api=0badc0ffee11", "--write-orders"))
    assert not again["due"] and f"already ordered ({oid})" == again["reason"] and "order" not in again


def test_check_code_reads_the_code_repos_head(repo, tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    git(code, "init", "-q", "-b", "main")
    (code / "a.py").write_text("x = 1\n")
    git(code, "add", "-A")
    git(code, "commit", "-qm", "c")
    head = git(code, "rev-parse", "HEAD")
    toml = repo / PROJ / "project.toml"
    toml.write_text(re.sub(r'code_repo\s*=\s*"[^"]*"', f'code_repo = "{code.as_posix()}"', toml.read_text()))
    schedule(repo)
    r = row(due(repo, "--today", "2026-12-10", "--check-code"))
    assert r["due"] and r["code_head"] == head[:7]
    toml.write_text(re.sub(r'code_repo\s*=\s*"[^"]*"', 'code_repo = "/nowhere/at/all"', toml.read_text()))
    r = row(due(repo, "--today", "2026-12-10", "--check-code"))
    assert not r["due"] and "couldn't read /nowhere/at/all" in r["reason"]


@pytest.mark.parametrize("bad, msg", [
    ("grade_every_days = -1", "whole number of days"),
    ('grade_every_days = "monthly"', "whole number of days"),
    ("grade_every_days = 7\nonly_if_code_changed = 1", "true or false"),
    ("grade_every_days = 7\nevery = 3", "schedule.every: unknown setting"),
])
def test_bad_schedules_are_refused(repo, bad, msg):
    toml = repo / PROJ / "project.toml"
    toml.write_text(toml.read_text() + f"\n[schedule]\n{bad}\n")
    r = cli("resolve", "--project", "orders-api", cwd=repo, code=None)
    assert r.returncode != 0 and msg in r.stderr


def test_a_schedule_never_changes_the_config_hash(repo):
    def resolved():
        return json.loads(cli("resolve", "--project", "orders-api", "--json", cwd=repo).stdout)["result"]["config"]
    before = resolved()["hash"]
    schedule(repo)
    after = resolved()
    assert after["hash"] == before and after["schedule"]["grade_every_days"] == 30


def test_the_index_carries_schedule_model_and_usage(repo):
    schedule(repo, every=14)
    rp = repo / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"
    r = json.loads(rp.read_text())
    r["run"].update(model="claude-opus-5-5", usage={"minutes": 52.5, "tokens_in": 1200000, "tokens_out": None, "cost_usd": 3.1})
    rp.write_text(json.dumps(r, indent=2))
    cli("index", cwd=repo)
    idx = json.loads((repo / "projects" / "index.json").read_text())
    p = idx["projects"][0]
    assert p["schedule"] == {"grade_every_days": 14, "only_if_code_changed": True}
    last = p["history"][-1]
    assert last["model"] == "claude-opus-5-5" and last["usage"] == {"minutes": 52.5, "tokens_in": 1200000, "cost_usd": 3.1}
    assert "usage" not in p["history"][0], "nothing recorded, nothing shown"
    import jsonschema
    jsonschema.validate(idx, json.loads((SRC / "schema" / "index.schema.json").read_text()))


def test_the_toml_writer_keeps_the_schedule(tmp_path):
    out = tmp_path / "project.toml"
    cli("init", "--preset", "service", "--name", "x", "--out", out, cwd=tmp_path)
    assert "# [schedule]" in out.read_text(), "a commented example where there's none"
    sys.path.insert(0, str(SRC / "tools"))
    import gradekit as gk
    text = gk.render_project_toml({"project": {"name": "x", "preset": "service"}, "schedule": {"grade_every_days": 30}})
    assert re.search(r"^\[schedule\]\ngrade_every_days\s*=\s*30$", text, re.M)
    assert gk.parse_toml(text)["schedule"] == {"grade_every_days": 30}


def test_the_github_schedule_step_opens_one_pull_request_per_project(repo, tmp_path):
    """The step's own script, run against a bare 'origin' with gh replaced by a stub that records its arguments."""
    yml = (SRC / "ci" / "github-grading.yml").read_text()
    script = yml[yml.index("      - name: Ask for the grades that are due"):]
    script = script[script.index("        run: |\n") + len("        run: |\n"):]
    script = "\n".join(l[10:] for l in script.splitlines())
    cli("init", "--project", "billing", "--code-repo", "https://example.com/billing", cwd=repo)
    schedule(repo)
    schedule(repo, project="billing")
    (repo / ".gitignore").unlink(missing_ok=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/gh.log\n')
    (bin_ / "gh").chmod(0o755)
    # the real job reads the code repos; here, billing has never been graded and orders-api's code is unknown
    env = dict(ENV, PATH=f"{bin_}{os.pathsep}{ENV['PATH']}", KIT=str(SRC), RUNNER_TEMP=str(tmp_path), BASE="main", GH_TOKEN="x", CODE_READ_TOKEN="")
    r = subprocess.run(["bash", "-e", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    branches = git(remote, "branch", "--list", "orders/*")
    assert re.fullmatch(r"\s*orders/billing/schedule-\d{4}-\d{2}-\d{2}", branches), branches
    log = (tmp_path / "gh.log").read_text()
    assert log.count("pr create") == 1 and "--title Scheduled grade: billing" in log
    files = git(remote, "ls-tree", "-r", "--name-only", branches.strip()).splitlines()
    assert [f for f in files if "/orders/" in f] and all(f.startswith("projects/billing/") for f in files if "/orders/" in f)
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
