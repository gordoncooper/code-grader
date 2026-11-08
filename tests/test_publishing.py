"""Safe publishing (4.3): sensitive findings are withheld from public reports without changing any score."""
import copy
import json
import os
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

PROJECT = EXAMPLE / "projects" / "orders-api"
NEW = PROJECT / "reports" / "2026-11-07-a1b2c3d" / "report.json"
KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
SENSITIVE = ("A3-001", "D1-001")   # A3-001 has a top priority, D1-001 a decision question


def run(*args, cwd=EXAMPLE):
    return subprocess.run(KIT + list(args), cwd=cwd, env=ENV, capture_output=True, text=True)


def payload(extra_toml: str = "") -> dict:
    return {"project_toml": (PROJECT / "project.toml").read_text() + extra_toml,
            "decisions_json": (PROJECT / "decisions.json").read_text(),
            "dispositions_json": (PROJECT / "dispositions.json").read_text()}


def call(gk, name, p):
    out = gk.web_api(name, p)
    assert out.get("ok", True) is not False, out
    return out


def full_report() -> dict:
    """The example report as a grader writes it before redacting: real evidence on sensitive findings."""
    r = json.loads(NEW.read_text())
    r.pop("publishing", None)
    r["holdout"]["private_details"] = [{"check": "refund-negative-amount", "passed": False}]
    for f in r["findings"]:
        if f["id"] in SENSITIVE:
            f["sensitive"] = True
        if f["id"] == "A2-001":   # the example's own withheld finding, given back its details
            f.update(title="No input validation on charge amount", sensitive=False, evidence=[
                {"type": "code", "file": "src/payments/api.py", "lines": "5",
                 "quote": "result = gateway.charge(request.json[\"amount\"])", "note": "negative amounts accepted"}])
            f.pop("paths", None)
            f.pop("sensitive")
    return r


def finding(report, fid):
    return next(f for f in report["findings"] if f["id"] == fid)


def action(report, aid):
    return next(a for b in report["benchmarks"] for a in b.get("path_to_target", []) if a["id"] == aid)


# --------------------------------------------------------------------------- redaction

def test_sensitive_findings_keep_what_scoring_needs_and_nothing_else(gk):
    full = full_report()
    public, leaks = gk.redact_report(full)
    assert leaks == []
    orig, f = finding(full, "A3-001"), finding(public, "A3-001")
    for key in ("id", "benchmark_id", "severity", "status", "first_seen_commit"):
        assert f[key] == orig[key]
    assert f["sensitive"] is True and "withheld" in f["title"] and orig["title"] not in json.dumps(public)
    assert [e["type"] for e in f["evidence"]] == ["withheld"]
    assert set(f["paths"]) >= {e["file"] for e in orig["evidence"] if e["type"] == "code"}
    assert public["publishing"] == {"redacted": True, "withheld": sorted(SENSITIVE)}
    assert public["holdout"]["private_details"] == "[redacted]"
    assert finding(public, "A1-001") == finding(full, "A1-001")
    assert full == full_report(), "redact must not change its input"


def test_actions_and_questions_that_fix_sensitive_findings_are_reworded(gk):
    full = full_report()
    public, _ = gk.redact_report(full)
    for aid in ("A3-act-1", "D1-act-1"):
        assert action(public, aid)["action"] != action(full, aid)["action"]
        assert "withheld" in action(public, aid)["action"]
    assert "withheld" in action(public, "D1-act-1")["decision_question"]
    prio = next(p for p in public["top_priorities"] if p["action_id"] == "A3-act-1")
    assert "withheld" in prio["why_first"]
    text = json.dumps(public)
    assert action(full, "D1-act-1")["decision_question"] not in text
    assert action(full, "A3-act-1")["action"] not in text


def test_public_report_scores_exactly_like_the_full_one(gk):
    """Invariant: the rollup of the public report is the redacted rollup of the full report."""
    cfg = call(gk, "check", {"report": full_report(), **payload()})
    full = full_report()
    full["rollup"] = cfg["rollup"]
    public, leaks = gk.redact_report(full)
    assert leaks == []
    again = call(gk, "check", {"report": public, **payload()})
    assert again["rollup"] == public["rollup"]
    for key in ("overall_score", "pillar_scores", "gates", "maturity"):
        assert again["rollup"][key] == cfg["rollup"][key], key


def test_redact_refuses_while_withheld_text_shows_elsewhere(gk):
    full = full_report()
    title = finding(full, "A3-001")["title"]
    next(b for b in full["benchmarks"] if b["id"] == "A3")["change_explanation"] = f"Down because of {title}."
    _, leaks = gk.redact_report(full)
    assert leaks and "A3-001" in leaks[0] and "benchmark A3" in leaks[0]


def test_another_finding_may_quote_the_same_line(gk):
    """Code is public in the code repo; only the analysis is withheld."""
    full = full_report()
    quote = finding(full, "A3-001")["evidence"][0]["quote"]
    other = finding(full, "A1-001")
    other["evidence"].append({"type": "code", "file": "x.py", "lines": "1", "quote": quote, "note": ""})
    assert gk.redact_report(full)[1] == []
    other["evidence"][-1]["note"] = f"same as {quote}"
    assert gk.redact_report(full)[1], "quoted code in prose still counts"


# --------------------------------------------------------------------------- validate

def warnings_for(gk, report, extra=""):
    return call(gk, "check", {"report": report, **payload(extra)})["validation"]["warnings"]


def test_public_repos_warn_about_unmarked_security_findings(gk):
    full = full_report()
    assert any("A2-001" in w and "sensitive" in w for w in warnings_for(gk, full))
    assert any("redact --in-place" in w for w in warnings_for(gk, full))
    assert not any("A2-001" in w for w in warnings_for(gk, full, "\n[publishing]\npublic = false\n"))
    assert not any("A2-001" in w for w in warnings_for(gk, full, "\n[publishing]\nwarn_at = \"critical\"\n"))


def test_withheld_evidence_only_on_sensitive_findings(gk):
    r = json.loads(NEW.read_text())
    finding(r, "A1-001")["evidence"] = [{"type": "withheld"}]
    errors = call(gk, "check", {"report": r, **payload()})["validation"]["errors"]
    assert any("A1-001" in e and "withheld" in e for e in errors)


def test_publish_problems(gk):
    full = full_report()
    problems = gk.publish_problems(full)
    assert any("not redacted" in p for p in problems)
    assert any("A3-001" in p for p in problems)
    assert any("hidden-check" in p for p in problems)
    assert gk.publish_problems(gk.redact_report(full)[0]) == []
    assert gk.publish_problems(json.loads(NEW.read_text())) == []


def test_publishing_settings_do_not_change_the_fingerprint(gk):
    a = call(gk, "check", {"report": full_report(), **payload()})
    b = call(gk, "check", {"report": full_report(), **payload("\n[publishing]\npublic = false\nsensitive_benchmarks = [\"A2\", \"A1\"]\n")})
    assert a["config"]["hash"] == b["config"]["hash"] and b["config"]["publishing"]["public"] is False


def test_bad_publishing_settings_are_config_errors(gk):
    out = gk.web_api("check", {"report": full_report(), **payload("\n[publishing]\nsensitive_benchmarks = [\"Z9\"]\n")})
    assert "Z9" in json.dumps(out)


# --------------------------------------------------------------------------- command line

def test_redact_in_place_then_validate_publish(tmp_path):
    folder = tmp_path / "r"
    folder.mkdir()
    report = folder / "report.json"
    report.write_text(json.dumps(full_report(), indent=2))
    args = ["--project-dir", str(PROJECT)]
    assert run("validate", str(report), "--publish", *args).returncode == 1
    r = run("redact", str(report), "--in-place")
    assert r.returncode == 0, r.stdout + r.stderr
    private = folder / "report.private.json"
    assert json.loads(private.read_text()) == full_report()
    assert "A3-001" in r.stdout
    v = run("validate", str(report), "--publish", *args)
    assert v.returncode == 0 and "\n0 error(s)" in v.stdout, v.stdout
    again = run("redact", str(report), "--in-place")
    assert again.returncode != 0 and "already redacted" in again.stderr + again.stdout
    assert json.loads(private.read_text()) == full_report(), "a second run must not overwrite the full report"


def test_redact_writes_nothing_on_a_leak(tmp_path):
    full = full_report()
    next(b for b in full["benchmarks"] if b["id"] == "A3")["change_explanation"] = finding(full, "A3-001")["title"]
    report = tmp_path / "report.json"
    report.write_text(json.dumps(full))
    r = run("redact", str(report), "--in-place")
    assert r.returncode == 1 and "LEAK" in r.stdout
    assert not (tmp_path / "report.private.json").exists() and json.loads(report.read_text()) == full


def test_example_is_safe_to_publish():
    r = run("validate", "--project", "orders-api", "--publish")
    assert r.returncode == 0 and "0 error(s), 0 warning(s)" in r.stdout, r.stdout


def test_verify_evidence_counts_withheld():
    r = run("verify-evidence", "--project", "orders-api", "--repo", "../sample-repo")
    assert r.returncode == 0 and "withheld: 1" in r.stdout


def test_init_ignores_private_reports(tmp_path):
    assert run("init", "--preset", "service", "--project", "demo", cwd=tmp_path).returncode == 0
    assert "*.private.json" in (tmp_path / ".gitignore").read_text().splitlines()
    run("init", "--preset", "service", "--project", "demo2", cwd=tmp_path)
    assert (tmp_path / ".gitignore").read_text().count("*.private.json") == 1


def test_project_toml_keeps_publishing(gk):
    out = call(gk, "build", {"project": {"project": {"name": "shop-api", "preset": "service"}, "publishing": {"public": False}}})
    assert "[publishing]" in out["toml"] and "public = false" in out["toml"]
    assert out["config"]["publishing"]["public"] is False
    plain = call(gk, "build", {"project": {"project": {"name": "shop-api", "preset": "service"}}})
    assert "# [publishing]" in plain["toml"]
