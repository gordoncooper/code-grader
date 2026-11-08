"""Unit tests for gradekit (source/tools/gradekit.py). Several pin bugs fixed in 4.2.1 and 4.2.2."""
import copy
import json
import zipfile
from pathlib import Path

import pytest

from conftest import EXAMPLE, SRC

PROJECT = EXAMPLE / "projects" / "orders-api"
OLD = PROJECT / "reports" / "2026-10-24-9f8e7d6" / "report.json"
NEW = PROJECT / "reports" / "2026-11-07-a1b2c3d" / "report.json"


def project_payload() -> dict:
    return {"project_toml": (PROJECT / "project.toml").read_text(), "decisions_json": (PROJECT / "decisions.json").read_text(),
            "dispositions_json": (PROJECT / "dispositions.json").read_text()}


def call(gk, name, payload):
    out = gk.web_api(name, payload)
    assert out.get("ok", True) is not False, out
    return out


# --------------------------------------------------------------------------- paths and zones

@pytest.mark.parametrize("given, expected", [
    ("./src/a.py", "src/a.py"), ("/src/a.py", "src/a.py"), ("src/a.py", "src/a.py"),
    (".github/workflows/ci.yml", ".github/workflows/ci.yml"), (".env.example", ".env.example"),
    ("././x", "x"), ("../up", "../up"),
])
def test_repo_relative_keeps_leading_dots(gk, given, expected):
    assert gk.repo_relative(given) == expected


def test_dot_folder_zone_patterns_match_only_dot_folders(gk):
    assert gk.glob_to_regex(".github/**").match(".github/workflows/ci.yml")
    assert not gk.glob_to_regex("github/**").match(".github/workflows/ci.yml")
    assert gk.glob_to_regex("docs/").match("docs/a/b.md")


def test_verify_zip_finds_quotes_in_dot_folders(gk, tmp_path):
    z = tmp_path / "code.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("repo-abc/.github/workflows/ci.yml", "name: Tests\non: push\n")
        zf.writestr("repo-abc/src/app.py", "print('hi')\n")
    report = {"benchmarks": [{"id": "F2", "strengths": [{"note": "", "evidence": [
        {"type": "code", "file": ".github/workflows/ci.yml", "lines": "1", "quote": "name: Tests", "note": ""},
        {"type": "code", "file": "src/app.py", "lines": "1", "quote": "print('hi')", "note": ""}]}],
        "enforcement": [], "path_to_target": []}], "findings": []}
    out = call(gk, "verify_zip", {"report": report, "zip_path": str(z)})
    assert out["failures"] == [] and out["checked"] == 2


# --------------------------------------------------------------------------- config

def test_example_config_fingerprint_is_stable(gk):
    """Patch releases must not change fingerprints, or every existing report stops validating."""
    out = call(gk, "check", {"report": json.loads(NEW.read_text()), **project_payload()})
    assert out["config_hash_match"] is True
    assert out["validation"]["errors"] == []


def test_scoring_version_is_separate_from_kit_version(gk):
    catalog = json.loads((SRC / "rubric" / "catalog.json").read_text())
    info = call(gk, "info", {})
    assert info["suite_version"] == catalog["suite_version"]
    # 5.0 also changes what severity means, so the scoring rules are 5.0.0; 4.x reports keep theirs (config/scoring/)
    assert info["scoring_version"] == "5.0.0"
    assert catalog["suite_version"].split(".")[0] in gk.READABLE_REPORT_MAJORS


def test_generated_project_toml_names_its_folder(gk):
    out = call(gk, "build", {"project": {"project": {"name": "shop-api", "preset": "service"}}})
    assert "projects/shop-api/project.toml" in out["toml"]
    assert out["config_error"] is None


def test_check_reports_runtime_notes_separately(gk):
    out = call(gk, "check", {"report": json.loads(NEW.read_text()), **project_payload()})
    assert "notes" in out["validation"]
    assert not any(w.startswith("jsonschema not installed") for w in out["validation"]["warnings"])


# --------------------------------------------------------------------------- report ordering

def write_report(folder: Path, run_date: str):
    folder.mkdir(parents=True)
    r = json.loads(NEW.read_text())
    r["run"]["date"] = run_date
    (folder / "report.json").write_text(json.dumps(r))


def test_same_day_reports_are_ordered_by_run_date(gk, tmp_path):
    reports = tmp_path / "reports"
    write_report(reports / "2026-11-07-0000aaa", "2026-11-07T16:30:00Z")  # the later run, but its name sorts first
    write_report(reports / "2026-11-07-ffff000", "2026-11-07T09:00:00Z")
    write_report(reports / "2026-11-06-9999999", "2026-11-06")
    assert [d.name for d in gk.report_folders(tmp_path)] == ["2026-11-06-9999999", "2026-11-07-ffff000", "2026-11-07-0000aaa"]


def test_scan_paths_orders_same_day_reports(gk):
    r1 = json.dumps({"run": {"date": "2026-11-07T08:00:00Z"}})
    r2 = json.dumps({"run": {"date": "2026-11-07T16:00:00Z"}})
    files = {"g/projects/p/project.toml": lambda: "[project]\n", "g/projects/p/reports/2026-11-07-fff/report.json": lambda: r1,
             "g/projects/p/reports/2026-11-07-aaa/report.json": lambda: r2}
    out = gk.scan_paths(files)
    assert [r["folder"] for r in out["p"]["reports"]] == ["2026-11-07-fff", "2026-11-07-aaa"]


# --------------------------------------------------------------------------- project discovery

def test_scan_paths_skips_example_projects_inside_kit_copies(gk):
    rep = lambda: json.dumps({"run": {"date": "2026-11-07"}})
    files = {
        "repo/projects/real/project.toml": lambda: "[project]\n",
        "repo/projects/real/reports/2026-11-07-aaa/report.json": rep,
        "repo/bundle/bare/tools/gradekit.py": lambda: "",
        "repo/bundle/bare/examples/grading-repo/projects/orders-api/project.toml": lambda: "[project]\n",
        "repo/bundle/web/suite/tools/gradekit.py": lambda: "",
        "repo/bundle/web/suite/examples/grading-repo/projects/orders-api/project.toml": lambda: "[project]\n",
    }
    assert list(gk.scan_paths(files)) == ["real"]
    del files["repo/projects/real/project.toml"], files["repo/projects/real/reports/2026-11-07-aaa/report.json"]
    only = gk.scan_paths(files)
    assert list(only) == ["orders-api"], "with no real project, the example shows once"


# --------------------------------------------------------------------------- PR checks (diff)

def pr_copy(base: dict, head: str = "ffff111") -> dict:
    r = copy.deepcopy(base)
    r["mode"] = "pr"
    r["run"].update(commit=head, base_commit=base["run"]["commit"])
    for b in r["benchmarks"]:
        b["carried_forward"] = True
    return r


def compare(gk, old, new):
    return call(gk, "compare", {"old": old, "new": new, **project_payload()})["diff"]


def test_carried_findings_with_status_new_are_not_new(gk):
    base = json.loads(NEW.read_text())
    assert any(f["status"] == "new" for f in base["findings"]), "fixture needs a finding with status new"
    d = compare(gk, base, pr_copy(base))
    assert d["findings"]["new"] == [] and d["verdict"] == "PASS"


@pytest.mark.parametrize("first_seen, verdict", [("a1b2c3d", "PASS"), ("ffff111", "FAIL")])
def test_pre_existing_problems_do_not_fail_a_pr(gk, first_seen, verdict):
    base = json.loads(NEW.read_text())
    pr = pr_copy(base)
    pr["findings"].append({"id": "A1-099", "benchmark_id": "A1", "title": "Refund path skips validation", "severity": "major",
                           "status": "new", "first_seen_commit": first_seen,
                           "evidence": [{"type": "code", "file": "src/payments/api.py", "lines": "1", "quote": "x", "note": ""}],
                           "disposition": None, "disposition_concern": None})
    d = compare(gk, base, pr)
    assert [f["id"] for f in d["findings"]["new"]] == ["A1-099"]
    assert d["verdict"] == verdict
    assert d["findings"]["new"][0]["pre_existing"] is (verdict == "PASS")


def test_sample_diff_still_fails_on_its_real_regression(gk):
    d = compare(gk, json.loads(OLD.read_text()), json.loads(NEW.read_text()))
    assert d["verdict"] == "FAIL"
    assert any("D2-001" in r for r in d["regressions"])


# --------------------------------------------------------------------------- decisions

def test_decisions_update_appends_and_validates(gk):
    before = (PROJECT / "decisions.json").read_text()
    out = call(gk, "decisions_update", {"decisions_json": before, "decisions": [
        {"action_id": "A4-act-1", "question": "q?", "approved": True, "decided_by": "t", "date": "2026-11-07"}]})
    after = json.loads(out["json"])
    assert out["added"] == 1 and after["decisions"][-1]["action_id"] == "A4-act-1"
    assert len(after["decisions"]) == len(json.loads(before)["decisions"]) + 1
    bad = gk.web_api("decisions_update", {"decisions_json": before, "decisions": [{"action_id": "x"}]})
    assert bad.get("ok") is False
