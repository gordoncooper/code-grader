"""Scoring 5.0: severity is judged by consequence where the code runs. Zones don't shift it; they raise the bar
(no critical findings in hot zones from L2, no major ones from L3). Reports graded under 4.x keep their rules."""
import json
import re

from conftest import EXAMPLE, SRC

PROJ = "projects/orders-api"
NEW = EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json"


def config(gk, scoring=None):
    return gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")], scoring=scoring)


def five(gk):
    """The example's latest report as if graded under the 5.0 rules, with every benchmark at 9 and every gap closed."""
    r, _ = gk.migrate_report(json.loads(NEW.read_text()))
    r["config"]["scoring_version"] = "5.0.0"
    for b in r["benchmarks"]:
        if b.get("applicability") != "not_applicable":
            b["score"] = 9
    for g in r["gap_register"]:
        g["status"] = "fixed"
    for f in r["findings"]:
        f["status"] = "fixed"
    r["holdout"] = {"run": False, "checks_run": None, "pass_rate": None, "private_details": None}
    return r


def hot_finding(r):
    """An example finding whose evidence is in a hot zone (src/orders/** and src/payments/** are hot)."""
    return next(f for f in r["findings"] if any(str(e.get("file", "")).startswith(("src/orders/", "src/payments/")) for e in f["evidence"]))


def test_zones_dont_shift_severity(gk):
    cfg, r = config(gk), five(gk)
    f = hot_finding(r)
    f["severity"], f["status"] = "major", "open"
    z = gk.analyze_findings(r, cfg)[f["id"]]
    assert z["criticality"] == "hot" and z["effective_severity"] == "major"
    lim = gk.score_limits(r, cfg, gk.analyze_findings(r, cfg)).get(f["benchmark_id"], {"max": 10})
    assert lim["max"] > 5, "a major finding in a hot zone doesn't hold its benchmark at 5"


def test_l3_allows_no_major_finding_in_a_hot_zone(gk):
    cfg, r = config(gk), five(gk)
    assert gk.compute_rollup(r, cfg)["maturity"]["current_level"] in ("L3", "L4")
    f = hot_finding(r)
    f["severity"], f["status"] = "major", "open"
    m = gk.compute_rollup(r, cfg)["maturity"]
    assert m["current_level"] == "L2" and m["next_level"] == "L3"
    assert any(f["id"] in b.get("finding_ids", []) for b in m["blockers"]), m["blockers"]
    f["evidence"] = [{"type": "absence", "searched": "x", "method": "y"}]
    f.pop("paths", None)   # the same major outside the hot zones
    assert gk.compute_rollup(r, cfg)["maturity"]["current_level"] == "L3"


def test_a_project_that_still_sets_the_shift_is_told(gk, tmp_path):
    t = tmp_path / "p.toml"
    t.write_text('[project]\nname = "x"\npreset = "default"\n[zone_settings]\nseverity_shift = { hot = 1, normal = 0, cold = -1 }\n')
    cfg = gk.resolve_config([str(t)])
    assert "severity_shift" not in cfg["zones"]
    assert any("no longer apply" in w for w in cfg["warnings"])


def test_4x_reports_keep_their_rules(gk):
    """Graded when a hot zone shifted severity: recomputed under the 4.x rules, its effective severities are shifted."""
    r = json.loads(NEW.read_text())
    cfg = config(gk, gk.scoring_version_of(r))
    assert cfg["zones"]["severity_shift"] == {"hot": 1, "normal": 0, "cold": -1}
    z = gk.analyze_findings(r, cfg)
    shifted = [i for i, v in z.items() if v["criticality"] == "hot" and v["severity"] in ("minor", "major")]
    assert shifted and all(z[i]["effective_severity"] != z[i]["severity"] for i in shifted)
    assert gk.compute_rollup(r, cfg)["maturity"] == r["rollup"]["maturity"]


def test_the_browser_engine_has_every_scoring_rules_file(gk):
    engine = (SRC / "tools" / "web" / "engine.js").read_text()
    files = re.search(r"SUITE_FILES = \[(.*?)\]", engine, re.S).group(1)
    for path in gk.SCORING_RULES.values():
        rel = path.relative_to(SRC).as_posix()
        assert f'"{rel}"' in files, f"engine.js doesn't load {rel}"
        assert path.exists()


def test_the_4x_rules_are_a_record_of_4x(gk):
    old = gk.load_toml(gk.SCORING_RULES["4"])
    assert old["suite_version"] == "4.2.0" and old["zone_settings"]["severity_shift"]["hot"] == 1
    assert gk.load_toml(gk.DEFAULTS_PATH)["suite_version"].startswith("5.")


def test_severity_is_defined_where_graders_read(gk):
    grader = (SRC / "prompts" / "grader.md").read_text()
    for level in ("`critical`", "`major`", "`minor`"):
        assert re.search(rf"\| {re.escape(level)} \| ", grader), level
    assert "Severity is consequence, where the code runs." in (SRC / "prompts" / "cards" / "grader.md").read_text()
    assert "intrinsic" not in grader.lower()


def test_a_minor_finding_cant_hold_a_cap(gk, tmp_path):
    import shutil
    import subprocess
    import sys
    repo = tmp_path / "grading"
    shutil.copytree(EXAMPLE, repo)
    kit = [sys.executable, str(SRC / "tools" / "gradekit.py")]
    rel = json.loads(subprocess.run(kit + ["report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--json"],
                                    cwd=repo, capture_output=True, text=True).stdout)["result"]["report"]
    add = kit + ["report", "finding", "add", rel, "--benchmark", "E1", "--title", "Quickstart misses a step", "--cap", "E1-cap-1",
                 "--absence", "a", "--method", "b"]
    r = subprocess.run(add + ["--severity", "minor"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1 and "major or worse" in r.stderr
    assert subprocess.run(add + ["--severity", "major"], cwd=repo, capture_output=True, text=True).returncode == 0
    report = json.loads((repo / rel).read_text())
    cfg = config(gk)
    assert gk.score_limits(report, cfg)["E1"]["max"] == 4
    report["findings"][-1]["severity"] = "minor"   # lowered later: the cap stops holding, and validate says why
    assert gk.score_limits(report, cfg)["E1"]["max"] > 4
    _, warnings = gk.validate_report(report, cfg, gk.load_catalog())
    assert any("doesn't hold on a minor finding" in w for w in warnings)
