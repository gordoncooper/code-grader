"""Ways around the scores, closed.

5.0.1 (the suite's self-grade): a finding dropped from its benchmark's finding_ids escaped the open-critical limit, and
`deliver` shipped a stored rollup older than the scores.
5.1.0 (the 5.0.1 review): a gate marked not_applicable dropped out of the gate check, lifting the overall cap; a
grader could mark findings accepted itself (only a warning), while no command recorded people's acceptances; and a
`migrated` marker on any report turned every format-5 rule into a warning."""
import copy
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


# --------------------------------------------------------------------------- gates can't be not applicable (5.1.0)
# The review's probe: every benchmark at 7 and A2 at 2 capped the overall at 4.0 (L0); `report score A2 --applicability
# not_applicable` gave 7.0 (L2), and validate and diff both passed. Dropping a gate is a person's call, in the config.

def not_applicable(r, bid="A2"):
    b = next(b for b in r["benchmarks"] if b["id"] == bid)
    b.update(applicability="not_applicable", applicability_reason="security is the platform team's job", score=None,
             confidence=None, weight=0)
    return b


def graded_here(gk):
    """five(), as if this kit graded it (not migrated from 4.x), so its rules hold."""
    r = five(gk)
    r.pop("migrated", None)
    return r


def migrated_from_4x(gk):
    """five(), still graded under the 4.x rules, as `gradekit migrate` leaves a 4.x report."""
    r = five(gk)
    r["config"]["scoring_version"] = "4.2.0"
    return r


def test_a_gate_cant_be_not_applicable(gk):
    cfg, r = config(gk), graded_here(gk)
    not_applicable(r)
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert any(e.startswith("A2 is a gate (always), so it can't be not_applicable") and '[gates] exclude = ["A2"]' in e
               for e in errors)


def test_reports_graded_under_4x_keep_a_warning(gk):
    cfg, r = config(gk), migrated_from_4x(gk)   # graded before the rule
    not_applicable(r)
    errors, warnings = gk.validate_report(r, cfg, gk.load_catalog())
    assert not [e for e in errors if "can't be not_applicable" in e]
    assert [w for w in warnings if "can't be not_applicable" in w]


def test_a_person_drops_a_gate_in_the_config(gk):
    layers = [("project.toml", gk.load_toml(EXAMPLE / PROJ / "project.toml")), ("org.toml", {"gates": {"exclude": ["A2"]}})]
    cfg, r = gk.resolve_layers(layers), graded_here(gk)
    r["config"]["hash"] = cfg["hash"]
    not_applicable(r)
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert not [e for e in errors if e.startswith("A2")], errors


def test_only_a_real_monorepo_split_leaves_a_gate_to_another_report(gk):
    """A monorepo's repo report leaves A1 to the component reports (graded per component); a project with no
    [[components]] can't claim that split. (The split itself: test_components_disputes_calibration.py.)"""
    cfg, r = config(gk), graded_here(gk)
    assert cfg["components"] == {}
    r["component"] = {"name": "repo", "path": "."}
    not_applicable(r, "A1")
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert any(e.startswith("A1 is a gate (always), so it can't be not_applicable") for e in errors)
    cfg = dict(cfg, components={"api": 2, "web": 1})
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert not [e for e in errors if "can't be not_applicable" in e], "graded per component"


def test_report_score_refuses_a_gate_as_not_applicable(ready):
    repo, rel = ready
    r = subprocess.run(KIT + ["report", "score", rel, "A2", "--applicability", "not_applicable", "--reason", "the platform team's"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1 and "A2 is a gate (always)" in r.stderr and "[gates] exclude" in r.stderr
    a2 = next(b for b in json.loads((repo / rel).read_text())["benchmarks"] if b["id"] == "A2")
    assert a2["applicability"] == "full" and a2["score"] == 7, "nothing was saved"


def test_a_gate_leaving_the_score_is_a_regression(gk):
    cfg, old = config(gk), graded_here(gk)
    new = copy.deepcopy(old)
    not_applicable(new)
    d = gk.compute_diff(old, new, cfg, cfg)
    assert d["verdict"] == "FAIL"
    assert "gate A2 is no longer scored (it was 9): a gate can't be not_applicable" in d["regressions"]
    assert not [n for n in d["notes"] if n.startswith("A2 went from")], "said once, as the regression"


# --------------------------------------------------------------------------- only people accept findings (5.1.0)
# The review's probe: C4 at 8 was refused while its critical finding was open; marking the finding accepted by hand,
# with made-up text and no entry in dispositions.json, let 8 through, and validate and diff passed.

PEOPLE = {"finding_id": "C4-901", "decision": "won't fix", "reason": "the suite is replaced next quarter",
          "decided_by": "jane@example.com", "date": "2026-11-20"}


def accepted_by_hand(r, fid="C4-901"):
    f, b = critical_on(r)
    f.update(id=fid, status="accepted", disposition="won't fix")
    b["finding_ids"] = [fid]
    return f


def acceptance_errors(gk, r, cfg):
    return [e for e in gk.validate_report(r, cfg, gk.load_catalog())[0] if "dispositions.json" in e]


def test_a_grader_cant_accept_a_finding(gk):
    cfg, r = config(gk), graded_here(gk)
    accepted_by_hand(r)
    assert acceptance_errors(gk, r, cfg) == ["finding C4-901 is accepted, but no entry in dispositions.json accepts it: only people "
                                             "accept findings, by adding an entry for it there (`report finding accept REPORT C4-901` "
                                             "then records it)"]
    cfg["dispositions"] = [PEOPLE]
    assert acceptance_errors(gk, r, cfg) == [], "people's entry accepts it"


def test_a_match_entry_accepts_only_the_findings_that_name_it(gk):
    cfg, r = config(gk), graded_here(gk)
    f = accepted_by_hand(r)
    cfg["dispositions"] = [{"match": "anything about the old test suite", "decision": "won't fix", "reason": "replaced soon"}]
    assert acceptance_errors(gk, r, cfg), "one match entry no longer covers every accepted finding"
    f["disposition_ref"] = 1
    assert acceptance_errors(gk, r, cfg) == []
    f["disposition_ref"] = 2
    assert acceptance_errors(gk, r, cfg), "an entry that isn't there"


def test_reports_graded_under_4x_keep_their_warning(gk):
    cfg, r = config(gk), migrated_from_4x(gk)
    accepted_by_hand(r)
    errors, warnings = gk.validate_report(r, cfg, gk.load_catalog())
    assert not [e for e in errors if "dispositions.json" in e]
    assert "finding C4-901 is 'accepted' but no entry in dispositions.json covers it" in warnings


def test_diff_says_who_accepted_a_finding(gk):
    cfg, old = config(gk), graded_here(gk)
    f, _ = critical_on(old)
    f["id"] = "C4-901"
    new = copy.deepcopy(old)
    accepted_by_hand(new)
    d = gk.compute_diff(old, new, cfg, cfg)
    assert d["findings"]["accepted"][0]["id"] == "C4-901" and d["findings"]["accepted"][0]["decided_by"] is None
    assert any(x.startswith("finding C4-901 was accepted without an entry in dispositions.json") for x in d["regressions"])
    cfg["dispositions"] = [PEOPLE]
    d = gk.compute_diff(old, new, cfg, cfg)
    assert not [x for x in d["regressions"] if "C4-901" in x]
    assert d["findings"]["accepted"][0]["decided_by"] == "jane@example.com"
    assert any(n.startswith("accepted by people: C4-901 (jane@example.com)") for n in d["notes"])
    assert "Accepted: C4-901" in gk.render_check_comment(d, new, cfg)


def test_report_finding_accept_records_the_peoples_entry(ready):
    """The example project's dispositions.json accepts B5-001, so the grader records it, with the entry's text."""
    repo, rel = ready
    from test_authoring import CODE, gk as run
    run("report", "finding", "add", rel, "--id", "B5-001", "--status", "open", "--benchmark", "B5", "--title", "Single payment gateway assumed",
        "--severity", "minor", "--cite", "src/payments/api.py:5", "--note", "no currency or provider abstraction", "--repo", CODE, cwd=repo)
    out = run("report", "finding", "accept", rel, "B5-001", cwd=repo).stdout
    assert "B5-001: accepted (won't fix: One payment provider is a deliberate business constraint through 2027" in out
    f = next(f for f in json.loads((repo / rel).read_text())["findings"] if f["id"] == "B5-001")
    assert f["status"] == "accepted" and "disposition_ref" not in f, "the entry names it"
    check = json.loads(run("report", "check", rel, "--json", cwd=repo, ok=False).stdout)["result"]
    assert not [e for e in check["errors"] if "B5-001" in e], check["errors"]


def test_an_id_people_accepted_doesnt_cover_another_problem(ready):
    """5.1.0, from a red-team review: a new critical filed as B5-001 took over people's acceptance of B5-001, a minor
    finding about the payment gateway, because acceptances matched on the ID alone."""
    repo, rel = ready
    from test_authoring import CODE, gk as run
    run("report", "finding", "add", rel, "--id", "B5-001", "--status", "open", "--benchmark", "B5", "--title", "SQL built from user input",
        "--severity", "critical", "--cite", "src/payments/api.py:1", "--repo", CODE, cwd=repo)
    r = run("report", "finding", "accept", rel, "B5-001", cwd=repo, ok=False)
    assert r.returncode == 1 and "B5-001 isn't the finding people accepted: it's critical now, and in 2026-10-24-9f8e7d6 it was minor" in r.stderr
    run("report", "finding", "update", rel, "B5-001", "--severity", "minor", cwd=repo)
    r = run("report", "finding", "accept", rel, "B5-001", cwd=repo, ok=False)
    assert r.returncode == 1 and "its title and evidence don't match B5-001 in 2026-10-24-9f8e7d6" in r.stderr


def test_only_an_answered_dispute_withdraws_a_finding(gk, ready):
    """5.1.0, from a red-team review: `report finding update --status withdrawn` made any finding count nowhere."""
    repo, rel = ready
    from test_authoring import CODE, gk as run
    run("report", "finding", "add", rel, "--benchmark", "C4", "--title", "Flaky tests", "--severity", "critical",
        "--cite", "src/payments/api.py:1", "--repo", CODE, cwd=repo)
    fid = next(f["id"] for f in json.loads((repo / rel).read_text())["findings"] if f["benchmark_id"] == "C4")
    r = run("report", "finding", "update", rel, fid, "--status", "withdrawn", cwd=repo, ok=False)
    assert r.returncode == 1 and "withdrawn by answering a person's dispute" in r.stderr
    cfg, rep = config(gk), graded_here(gk)
    f, _ = critical_on(rep)
    f["status"] = "withdrawn"
    errors, _ = gk.validate_report(rep, cfg, gk.load_catalog())
    assert any(e.startswith(f"finding {f['id']} is withdrawn, but no answered dispute withdraws it") for e in errors)


def test_a_finding_no_entry_accepts_cant_be_accepted(ready):
    repo, rel = ready
    from test_authoring import CODE, gk as run
    run("report", "finding", "add", rel, "--benchmark", "C4", "--title", "Flaky tests", "--severity", "major",
        "--cite", "src/payments/api.py:1", "--repo", CODE, cwd=repo)
    fid = next(f["id"] for f in json.loads((repo / rel).read_text())["findings"] if f["benchmark_id"] == "C4")
    r = run("report", "finding", "accept", rel, fid, cwd=repo, ok=False)
    assert r.returncode == 1 and f"no entry in dispositions.json accepts {fid}: only people accept findings" in r.stderr
    r = run("report", "finding", "update", rel, fid, "--status", "accepted", cwd=repo, ok=False)
    assert r.returncode == 1 and "report finding accept REPORT ID" in r.stderr
    r = run("report", "finding", "add", rel, "--benchmark", "C4", "--title", "x", "--severity", "minor", "--status", "accepted",
            "--absence", "x", "--method", "y", cwd=repo, ok=False)
    assert r.returncode == 1 and "report finding accept REPORT ID" in r.stderr
    assert next(f for f in json.loads((repo / rel).read_text())["findings"] if f["id"] == fid)["status"] == "new"


# --------------------------------------------------------------------------- the migrated marker (5.1.0)
# `migrated` marks a 4.x report that `gradekit migrate` converted, which keeps its 4.x rules (warnings). Nothing checked
# the claim, so adding it to any report relaxed every format-5 rule: limits, gates, acceptances.

def test_a_migrated_marker_relaxes_nothing_on_a_report_graded_under_5x(gk):
    cfg, r = config(gk), graded_here(gk)
    r["migrated"] = {"from": "4.2.0", "by": "5.0.1"}
    not_applicable(r)
    assert gk.limits_enforced(r)
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert any(e.startswith("migrated: only a 4.x report that `gradekit migrate` converted carries this marker") for e in errors)
    assert any("so it can't be not_applicable" in e for e in errors), "the gate rule still holds"
    assert not gk.limits_enforced(migrated_from_4x(gk)), "a real migration keeps its 4.x rules"


def test_a_format_5_report_cant_choose_the_4x_rules(gk):
    """5.1.0, from a red-team review: config.scoring_version 4.2.0 on a new report picked the 4.x rules, whose zone
    severity shift turns a critical finding in cold code into a major one, so the open-critical limit never applied."""
    cfg, r = config(gk), graded_here(gk)
    r["config"]["scoring_version"] = "4.2.0"
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert any(e.startswith("config.scoring_version is 4.2.0, but a format-5 report is graded under the 5.x scoring rules")
               for e in errors)
    assert not [e for e in gk.validate_report(migrated_from_4x(gk), cfg, gk.load_catalog())[0] if "scoring_version" in e]


def test_repo_rollup_needs_a_monorepo(gk):
    """A single-repo report carrying a repo-wide result would put that result in index.json."""
    cfg, r = config(gk), graded_here(gk)
    r["repo_rollup"] = {"overall_score": 9.6, "maturity": "L4", "components": []}
    errors, _ = gk.validate_report(r, cfg, gk.load_catalog())
    assert "repo_rollup is only for a monorepo's repo report, and project.toml defines no [[components]]" in errors


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
