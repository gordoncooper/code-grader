"""`gradekit migrate` (F4): a project moves to this suite version in one pull request (the pin, and its reports in
format 5 with --reports), scores untouched, and `gradekit ci` checks the migration by redoing it."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
PROJ = "projects/orders-api"
NEWEST = f"{PROJ}/reports/2026-11-07-a1b2c3d"
MAJOR = json.loads((SRC / "rubric" / "catalog.json").read_text())["suite_version"].split(".")[0]


def gk(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    git(g, "init", "-q", "-b", "main")
    git(g, "add", "-A")
    git(g, "commit", "-qm", "base")
    return g


def ci(repo):
    r = subprocess.run(KIT + ["ci", "--base", "main", "--json"], cwd=repo, env=ENV, capture_output=True, text=True)
    return json.loads(r.stdout)["result"]


def test_a_dry_run_lists_the_changes_and_writes_nothing(repo):
    res = json.loads(gk("migrate", "--project", "orders-api", "--reports", "--json", cwd=repo).stdout)["result"]
    assert [f["path"] for f in res["files"]] == ["project.toml", "reports/2026-10-24-9f8e7d6/report.json", "reports/2026-10-24-9f8e7d6/report.md",
                                                 "reports/2026-11-07-a1b2c3d/report.json", "reports/2026-11-07-a1b2c3d/report.md"]
    assert res["scores_unchanged"] and not res["written"]
    assert git(repo, "status", "--porcelain") == ""


def test_never_on_the_default_branch(repo):
    r = gk("migrate", "--project", "orders-api", "--write", cwd=repo, code=1)
    assert "refusing to write on main" in r.stderr


def test_the_pin_alone_changes_only_one_line(repo):
    before = (repo / PROJ / "project.toml").read_text()
    git(repo, "switch", "-q", "-c", "m")
    gk("migrate", "--project", "orders-api", "--write", cwd=repo)
    after = (repo / PROJ / "project.toml").read_text()
    added = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert len(added) == 1 and added[0].startswith(f'suite           = "{MAJOR}"')
    assert len(after.splitlines()) == len(before.splitlines()) + 1, "comments and everything else are kept"
    assert gk("migrate", "--project", "orders-api", "--json", cwd=repo).stdout.count('"files": []') == 1


def test_a_migration_pull_request_end_to_end(gk_mod, repo):
    gk("migrate", "--project", "orders-api", "--reports", "--run", "--base", "main", cwd=repo)
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == f"migrate/orders-api-v{MAJOR}"
    res = ci(repo)
    assert res["ok"] and res["kind"] == "migration" and res["labels"] == ["grading: migration"], res
    assert "**Migration** of `orders-api`" in res["comment"]
    for rel in (f"{PROJ}/reports/2026-10-24-9f8e7d6", NEWEST):
        before = json.loads(git(repo, "show", f"main:{rel}/report.json"))
        after = json.loads((repo / rel / "report.json").read_text())
        assert after["schema_version"] == 5 and after["migrated"] == {"from": before["suite_version"], "by": after["suite_version"]}
        assert after["rollup"] == before["rollup"] and [b.get("score") for b in after["benchmarks"]] == [b.get("score") for b in before["benchmarks"]]
        assert after["run"]["date"].endswith("T00:00:00Z") and after["run"]["started"] == after["run"]["date"]
        assert after["config"]["scoring_version"] == "4.2.0"
        assert all(f.get("fingerprint") or f["evidence"][0]["type"] == "withheld" for f in after["findings"])
        md = (repo / rel / "report.md").read_text()
        assert "(migrated)" in md
    cfg = gk_mod.resolve_config([str(repo / PROJ / "project.toml")], scoring=gk_mod.scoring_version_of(after))   # its own rules
    after = json.loads((repo / NEWEST / "report.json").read_text())
    errors, _ = gk_mod.validate_report(after, cfg, gk_mod.load_catalog())
    assert errors == [], "a migrated report is a valid format-5 report"
    gk("index", "--check", cwd=repo)   # scores, dates and decisions are unchanged, so the index is too


def test_ci_refuses_a_hand_edit_inside_a_migration(repo):
    gk("migrate", "--project", "orders-api", "--reports", "--run", "--base", "main", cwd=repo)
    p = repo / NEWEST / "report.json"
    r = json.loads(p.read_text())
    b = next(b for b in r["benchmarks"] if isinstance(b.get("score"), int))
    b["score"] = 10
    p.write_text(json.dumps(r, indent=2))
    git(repo, "commit", "-qam", "tweak")
    res = ci(repo)
    assert not res["ok"] and any("isn't what `gradekit migrate` makes" in x for x in res["problems"])


def test_a_migration_with_other_changes_isnt_one(repo):
    gk("migrate", "--project", "orders-api", "--reports", "--run", "--base", "main", cwd=repo)
    (repo / PROJ / "decisions.json").write_text((repo / PROJ / "decisions.json").read_text())
    (repo / "README.md").write_text("changed\n")
    git(repo, "commit", "-qam", "more")
    res = ci(repo)
    assert res["kind"] != "migration" and any("never edited" in x for x in res["problems"])


def test_pr_reports_turn_pre_existing_new_findings_into_noticed(gk_mod):
    r = json.loads((EXAMPLE / NEWEST / "report.json").read_text())
    r["mode"] = "pr"
    r["run"]["base_commit"] = "9f8e7d6"
    f = r["findings"][0]
    f["status"], f["first_seen_commit"] = "new", "9f8e7d6"
    out, notes = gk_mod.migrate_report(r)
    assert out["findings"][0]["status"] == "noticed" and any("new → noticed" in n for n in notes)


def test_withheld_findings_get_their_fingerprint_from_the_private_report(gk_mod, repo):
    from test_publishing import full_report
    full = full_report()
    (repo / NEWEST / "report.private.json").write_text(json.dumps(full))
    git(repo, "switch", "-q", "-c", "m")
    gk("migrate", "--project", "orders-api", "--reports", "--write", cwd=repo)
    public = json.loads((repo / NEWEST / "report.json").read_text())
    private = json.loads((repo / NEWEST / "report.private.json").read_text())
    pub = next(f for f in public["findings"] if f["evidence"][0]["type"] == "withheld")
    priv = next(f for f in private["findings"] if f["id"] == pub["id"])
    assert pub["fingerprint"] == priv["fingerprint"] == gk_mod.fingerprint_of(priv)
    assert "report.private.json" not in git(repo, "status", "--porcelain"), "it stays out of git"


def test_an_already_migrated_project_has_nothing_to_do(repo):
    git(repo, "switch", "-q", "-c", "m")
    gk("migrate", "--project", "orders-api", "--reports", "--write", cwd=repo)
    out = gk("migrate", "--project", "orders-api", "--reports", cwd=repo).stdout
    assert "already on suite" in out


@pytest.mark.parametrize("value, want", [
    ("2026-11-07", "2026-11-07T00:00:00Z"), ("2026-11-07T21:04:00Z", "2026-11-07T21:04:00Z"),
    ("2026-11-07T13:04:00-08:00", "2026-11-07T21:04:00Z"), ("yesterday", None),
])
def test_dates_become_utc(gk_mod, value, want):
    assert gk_mod.utc_stamp(value) == want


@pytest.mark.parametrize("kit, scoring", [("4.0.1", "4.0.0"), ("4.1.0", "4.1.0"), ("4.2.2", "4.2.0"), ("4.3.0", "4.2.0")])
def test_the_scoring_version_of_each_4x_release(gk_mod, kit, scoring):
    assert gk_mod.scoring_version_4x(kit) == scoring


@pytest.fixture
def gk_mod(gk):
    return gk
