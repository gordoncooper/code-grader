"""Versions and pins (5.0): the kit version, the scoring version and each report's version have separate jobs;
5.x reads 4.x reports; projects pin the major they use."""
import copy
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
OLD = EXAMPLE / PROJ / "reports" / "2026-10-24-9f8e7d6" / "report.json"
NEW = EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"
KIT_MAJOR = json.loads((SRC / "rubric" / "catalog.json").read_text())["suite_version"].split(".")[0]


def gk(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    assert r.returncode == code, r.stdout + r.stderr
    return r


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    return g


def pin(repo, value):
    toml = repo / PROJ / "project.toml"
    lines = [ln for ln in toml.read_text().splitlines() if not ln.startswith("suite = ")]
    i = lines.index("[project]")
    toml.write_text("\n".join(lines[:i + 1] + [f"suite = {json.dumps(value)}"] + lines[i + 1:]) + "\n")


def cfg(gk_mod, repo):
    return gk_mod.resolve_config([str(repo / PROJ / "project.toml")])


# --------------------------------------------------------------------------- reading reports across versions

def test_4x_reports_stay_valid(gk):
    """The example's reports were written by 4.2.0; a 5.x kit validates them as they are."""
    report = json.loads(NEW.read_text())
    assert report["suite_version"].startswith("4.")
    c = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    errors, _ = gk.validate_report(report, c, gk.load_catalog())
    assert errors == []


def test_reports_from_older_majors_are_refused(gk):
    report = json.loads(NEW.read_text())
    report["suite_version"] = "3.1.0"
    c = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    errors, _ = gk.validate_report(report, c, gk.load_catalog())
    assert any("reads reports from suite 4.x and 5.x" in e for e in errors)


def test_new_reports_record_both_versions(repo):
    out = json.loads(gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--json", cwd=repo).stdout)["result"]
    r = json.loads((repo / out["report"]).read_text())
    catalog = json.loads((SRC / "rubric" / "catalog.json").read_text())
    assert r["suite_version"] == catalog["suite_version"]
    assert r["config"]["scoring_version"] == "4.2.0"
    assert r["config"]["hash"] == json.loads(NEW.read_text())["config"]["hash"], "the fingerprint carries over from 4.x"


def test_a_dropped_score_is_a_regression_across_kit_majors(gk):
    """A PR check of a 5.x report against a 4.x baseline must still fail on a drop: the scoring rules are the same."""
    old, new = json.loads(NEW.read_text()), json.loads(NEW.read_text())
    new["suite_version"] = f"{KIT_MAJOR}.0.0"
    new["config"]["scoring_version"] = "4.2.0"
    b = next(b for b in new["benchmarks"] if isinstance(b.get("score"), int) and b["score"] > 1)
    b["score"] -= 1
    c = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    d = gk.compute_diff(old, new, c, c)
    assert any(b["id"] in r for r in d["regressions"]), d


def test_different_scoring_majors_are_not_compared(gk):
    old, new = json.loads(NEW.read_text()), json.loads(NEW.read_text())
    new["config"]["scoring_version"] = "9.0.0"
    b = next(b for b in new["benchmarks"] if isinstance(b.get("score"), int) and b["score"] > 1)
    b["score"] -= 1
    c = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    d = gk.compute_diff(old, new, c, c)
    assert d["regressions"] == [] and any("scoring versions differ" in n for n in d["notes"])


def test_a_config_cant_change_the_scoring_version(gk, tmp_path):
    t = tmp_path / "p.toml"
    t.write_text('suite_version = "5.0.0"\n[project]\nname = "x"\npreset = "default"\n')
    with pytest.raises(gk.GradekitError, match="this kit scores with 4.2.0"):
        gk.resolve_config([str(t)])


# --------------------------------------------------------------------------- pins

def test_init_pins_new_projects(tmp_path):
    gk("init", "--project", "demo", "--code-repo", "https://example.com/demo", cwd=tmp_path)
    toml = (tmp_path / "projects" / "demo" / "project.toml").read_text()
    assert f'suite           = "{KIT_MAJOR}"' in toml


def test_a_pin_must_be_a_major_number(gk, repo):
    pin(repo, "five")
    with pytest.raises(gk.GradekitError, match="project.suite is the suite's major version"):
        cfg(gk, repo)


def test_a_pinned_project_gets_reports_only_from_its_major(repo):
    pin(repo, "4" if KIT_MAJOR != "4" else "9")
    r = gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", cwd=repo, code=1)
    assert "pinned to suite" in r.stderr and "/v" in r.stderr
    r = gk("carry", str(NEW.relative_to(EXAMPLE)), "--repo", EXAMPLE.parent / "sample-repo", "--commit", "b2c3d4e5f6",
           "--mode", "full", "--allow-withheld", "--project", "orders-api", cwd=repo, code=1)
    assert "pinned to suite" in r.stderr


def test_pinned_to_this_major_works(repo):
    pin(repo, KIT_MAJOR)
    gk("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", cwd=repo)


def test_doctor_checks_the_pin(repo):
    def status():
        r = subprocess.run(KIT + ["doctor", "--project", "orders-api", "--json"], cwd=repo, env=ENV, capture_output=True, text=True)
        return next(c for c in json.loads(r.stdout)["result"]["checks"] if c["check"] == "suite pin")
    c = status()
    assert c["status"] == "warn" and f'suite = \"{KIT_MAJOR}\"' in c["fix"]
    pin(repo, KIT_MAJOR)
    assert status()["status"] == "ok"
    pin(repo, "9")
    assert status()["status"] == "fail"


def test_ci_needs_changes_when_a_report_comes_from_another_major(repo, tmp_path):
    newest = repo / PROJ / "reports" / "2026-11-07-a1b2c3d"
    shutil.move(str(newest), str(tmp_path / "newest"))
    pin(repo, KIT_MAJOR)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "switch", "-q", "-c", "pr")
    shutil.copytree(tmp_path / "newest", newest)   # written by 4.2.0, for a project pinned to this major
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "report")
    r = subprocess.run(KIT + ["ci", "--base", "main", "--json"], cwd=repo, env=ENV, capture_output=True, text=True)
    res = json.loads(r.stdout)["result"]
    if KIT_MAJOR == "4":
        pytest.skip("the example's reports are 4.x")
    assert not res["ok"] and any("pinned to suite" in p for p in res["problems"]), res
