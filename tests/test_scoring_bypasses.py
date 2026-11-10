"""Two ways around the scores that the suite's self-grade found (5.0.1): a finding dropped from its benchmark's
finding_ids escaped the open-critical limit, and `deliver` shipped a stored rollup older than the scores."""
import json
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC
from test_severity import config, five

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
PROJ = "projects/orders-api"


def critical_on(r, bid="C4"):
    f = next(f for f in r["findings"] if f.get("benchmark_id") == bid) if any(f.get("benchmark_id") == bid for f in r["findings"]) \
        else {**r["findings"][0], "id": f"{bid}-901", "benchmark_id": bid}
    if f not in r["findings"]:
        r["findings"].append(f)
    f.update(severity="critical", status="open")
    b = next(b for b in r["benchmarks"] if b["id"] == bid)
    b["score"] = 8
    return f, b


def test_the_open_critical_limit_holds_when_the_finding_isnt_listed(gk):
    """The self-grade's probe: C4 at 8 with an open critical finding whose ID was removed from C4's finding_ids."""
    cfg, r = config(gk), five(gk)
    f, b = critical_on(r)
    b["finding_ids"] = [i for i in b.get("finding_ids", []) if i != f["id"]]
    lim = gk.score_limits(r, cfg)["C4"]
    assert lim["max"] == 5 and any(w["kind"] == "critical" and f["id"] in w["why"] for w in lim["why"])
    errors, warnings = gk.validate_report(r, cfg, gk.load_catalog())
    assert any(e.startswith("C4: score 8 is above its limit of 5") for e in errors + warnings)   # an error once limits are enforced
    assert any(e.startswith(f"finding {f['id']} (open) is C4's, but C4's finding_ids doesn't list it") for e in errors)


def test_listing_a_finding_still_counts_too(gk):
    cfg, r = config(gk), five(gk)
    f, b = critical_on(r)
    b.setdefault("finding_ids", []).append(f["id"]) if f["id"] not in b.get("finding_ids", []) else None
    assert gk.score_limits(r, cfg)["C4"]["max"] == 5


def test_a_gap_explains_a_low_score(gk):
    cfg, r = config(gk), five(gk)
    b = next(b for b in r["benchmarks"] if b["id"] == "D2")
    b.update(score=6, finding_ids=[])
    r["findings"] = [f for f in r["findings"] if f.get("benchmark_id") != "D2"]
    warn = lambda: [w for w in gk.validate_report(r, cfg, gk.load_catalog())[1] if w.startswith("D2: score 6")]
    assert warn()
    r["gap_register"].append({"id": "GAP-901", "gap": "x", "severity": "minor", "necessity": "should", "status": "open",
                              "rationale": "y", "benchmark_ids": ["D2"]})
    assert warn() == [], "a gap linked to the benchmark explains it"


# --------------------------------------------------------------------------- stored rollups

@pytest.fixture
def ready(tmp_path):
    """A complete format-5 report written with `report` commands, its rollup stored by `report check --write`."""
    from test_authoring import ALL, CODE, gk as run, start
    repo = tmp_path / "grading"
    shutil.copytree(EXAMPLE, repo)
    rel = start(repo)
    run("report", "strength", rel, "A1", "--text", "Totals in one place", "--cite", "src/orders/service.py:1-2", "--repo", CODE, cwd=repo)
    for bid in ALL:
        run("report", "score", rel, bid, "--score", "7", "--confidence", "medium", cwd=repo)
    for bid in ("X1", "X2", "X3", "X4", "X5", "X6"):
        run("report", "score", rel, bid, "--applicability", "not_applicable", "--reason", "not relevant here", cwd=repo)
    run("report", "set", rel, "scope_examined", "src/", cwd=repo)
    run("report", "ran", rel, "--command-text", "pytest -q", "--exit-code", "0", "--summary", "1 passed", cwd=repo)
    run("report", "set", rel, "limitations", "None", "--append", cwd=repo)
    run("report", "set", rel, "summary", "Small.", cwd=repo)
    left = json.loads(run("report", "check", rel, "--json", cwd=repo, ok=False).stdout)["result"]["todo"]
    for bid in [t.split(":", 1)[0] for t in left if "below its target" in t]:
        run("report", "action", rel, bid, "--action", "Raise it to the target", "--new-score", "8", "--effort", "M", cwd=repo)
    done = json.loads(run("report", "check", rel, "--json", "--write", cwd=repo).stdout)["result"]
    assert done["status"] == "ready", done
    return repo, rel


def test_an_edit_drops_the_stored_rollup(ready):
    repo, rel = ready
    r = subprocess.run(KIT + ["report", "score", rel, "B1", "--score", "8", "--confidence", "high"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "stored rollup was dropped" in r.stderr and "rollup" not in json.loads((repo / rel).read_text())


def test_check_warns_about_a_rollup_edited_by_hand(ready):
    repo, rel = ready
    r = json.loads((repo / rel).read_text())
    r["rollup"]["overall_score"] = 4.9
    r["rollup"]["maturity"]["current_level"] = "L0"
    (repo / rel).write_text(json.dumps(r, indent=2))
    out = json.loads(subprocess.run(KIT + ["report", "check", rel, "--json"], cwd=repo, capture_output=True, text=True).stdout)["result"]
    assert any(w.startswith("the stored rollup (4.9, L0) doesn't match the scores") for w in out["warnings"])


def test_deliver_always_ships_the_current_rollup(ready):
    """The self-grade's probe: a stale stored rollup (4.9 L0) while report.md said 5.0 L1."""
    repo, rel = ready
    r = json.loads((repo / rel).read_text())
    right = (r["rollup"]["overall_score"], r["rollup"]["maturity"]["current_level"])
    r["rollup"]["overall_score"] = 4.9
    r["rollup"]["maturity"]["current_level"] = "L0"
    (repo / rel).write_text(json.dumps(r, indent=2))
    d = subprocess.run(KIT + ["deliver", rel, "--delivery", "save"], cwd=repo, capture_output=True, text=True)
    assert d.returncode == 0, d.stdout + d.stderr
    shipped = json.loads((repo / rel).read_text())["rollup"]
    assert (shipped["overall_score"], shipped["maturity"]["current_level"]) == right
    md = (repo / rel).with_name("report.md").read_text()
    assert f"**{right[0]}**" in md or str(right[0]) in md


# --------------------------------------------------------------------------- rounding (A1-act-3)

@pytest.mark.parametrize("items, want", [
    ([(6, 1), (6.5, 1)], 6.3),          # 6.25: round() gave 6.2 (half to even)
    ([(6.45, 1)], 6.5),                 # float 6.45 is 6.4499…: round() gave 6.4
    ([(7.9, 1), (8, 1)], 8.0),          # 7.95 reaches the L3 threshold as shown
    ([(7, 1.15), (8, 0.85)], 7.4),      # 7.425 with float weights
    ([], None),
])
def test_scores_round_half_up_on_exact_values(gk, items, want):
    assert gk.weighted(items) == want


def test_reports_graded_under_4x_rules_keep_their_rounding(gk):
    assert gk.weighted([(6, 1), (6.5, 1)], half_up=False) == round(6.25, 1) == 6.2


def test_init_writes_only_the_answers_given(tmp_path):
    out = tmp_path / "p.toml"
    r = subprocess.run(KIT + ["init", "--preset", "service", "--name", "demo", "--answer", "audience=public", "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "next: edit" in r.stdout and "gradekit.py resolve --config" in r.stdout, "a command you can run"
    text = out.read_text()
    assert 'audience          = "public"' in text and '# failure_impact  = "revenue_loss"   # the service preset\'s' in text
    import tomllib
    assert tomllib.loads(text)["answers"] == {"audience": "public"}, "the rest follow the preset"
