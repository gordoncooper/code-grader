"""Markdown made from report data (4.3): `gradekit render`."""
import json
import os
import subprocess
import sys

from conftest import EXAMPLE, SRC

PROJECT = EXAMPLE / "projects" / "orders-api"
OLD = PROJECT / "reports" / "2026-10-24-9f8e7d6" / "report.json"
NEW = PROJECT / "reports" / "2026-11-07-a1b2c3d" / "report.json"
KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def gk(*args, ok=True, cwd=EXAMPLE):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def cfg(gk_mod, extra=""):
    toml = gk_mod.parse_toml((PROJECT / "project.toml").read_text() + extra)
    return gk_mod.resolve_layers([("project.toml", toml)], decisions=json.loads((PROJECT / "decisions.json").read_text())["decisions"])


def test_example_report_md_is_rendered_from_its_json():
    """The committed report.md files are exactly what `render report` makes: same layout every run."""
    for report in (OLD, NEW):
        assert gk("render", "report", report, "--stdout").stdout == report.with_suffix(".md").read_text()


def test_report_md_sections_and_numbers(gk):
    report = json.loads(NEW.read_text())
    md = gk.render_report_md(report, cfg(gk))
    for heading in ("## Summary", "## Gates and maturity", "## Scorecard", "## Top priorities", "## Decisions needed",
                    "## Findings", "## Benchmark detail", "## Limitations"):
        assert heading in md
    assert f"Overall **{report['rollup']['overall_score']}**" in md
    assert report["summary"] in md
    assert "- [ ] **D1-act-1:**" in md


def test_public_text_withholds_sensitive_findings_even_before_redact(gk):
    from test_publishing import full_report
    full = full_report()
    title = next(f for f in full["findings"] if f["id"] == "A3-001")["title"]
    assert title not in gk.render_report_md(full, cfg(gk))
    assert title not in gk.render_report_pr(full, cfg(gk))["body"]
    assert title in gk.render_report_md(full, cfg(gk, "\n[publishing]\npublic = false\n"))


def test_pr_title_body_and_branch(gk):
    pr = gk.render_report_pr(json.loads(NEW.read_text()), cfg(gk), site="https://example.com/grading/",
                             grading_repo="https://github.com/acme/grading")
    assert pr["title"] == "Report: orders-api 2026-11-07 — 4.9 (L0)"
    assert pr["branch"] == "report/orders-api/2026-11-07-a1b2c3d"
    assert "https://example.com/grading/app/review.html?repo=https://github.com/acme/grading&project=orders-api&ref=report/orders-api/2026-11-07-a1b2c3d" in pr["body"]
    assert "D1-act-1" in pr["body"] and "A1: 5 — passed" in pr["body"]
    out = json.loads(gk_cli_pr())["result"]
    assert out["title"] == pr["title"]


def gk_cli_pr():
    return gk("render", "pr", NEW, "--json").stdout


def test_check_comment(gk):
    old, new = json.loads(OLD.read_text()), json.loads(NEW.read_text())
    c = cfg(gk)
    text = gk.render_check_comment(gk.compute_diff(old, new, c, c), new, c)
    assert text.startswith("**Quality check: FAIL**")
    assert "Re-graded: every applicable benchmark" in text
    assert "A2 3 → 5 (A2-002 fixed)" in text and "D2-001" in text


def test_check_comment_always_withholds_sensitive_findings(gk):
    old = json.loads(OLD.read_text())
    new = json.loads(NEW.read_text())
    new["findings"].append({"id": "A2-009", "benchmark_id": "A2", "title": "SQL injection in export", "severity": "critical",
                            "status": "new", "first_seen_commit": "a1b2c3d", "sensitive": True,
                            "evidence": [{"type": "code", "file": "src/payments/api.py", "lines": "5", "quote": "x"}]})
    c = cfg(gk, "\n[publishing]\npublic = false\n")
    text = gk.render_check_comment(gk.compute_diff(old, new, c, c), new, c)
    assert "A2-009" in text and "SQL injection" not in text and "details withheld" in text


def test_improvement_log(gk, tmp_path):
    log = {"done": [{"action_id": "A4-act-1", "commit": "1a2b3c4d5e6f", "resolves": ["A4-001"], "check": "seed ran twice"}],
           "skipped": [{"action_id": "B5-act-1", "reason": "optional"}], "behavior_changes": ["Seeding twice is a no-op"]}
    text = gk.render_improve_log(log, json.loads(NEW.read_text()), cfg(gk))
    assert "**A4-act-1** in `1a2b3c4d5e`, resolves A4-001. Checked with: seed ran twice" in text
    assert "**D1-act-1:** Implement CSV" in text, "pending decisions are listed as blocked"
    assert "Seeding twice is a no-op" in text and "**New issues noticed**" in text
    (tmp_path / "log.json").write_text(json.dumps({"donee": []}))
    assert "unknown section" in gk_cli_log(tmp_path / "log.json").stderr


def gk_cli_log(path):
    return gk("render", "log", path, ok=False)


def test_render_report_writes_beside_the_report(tmp_path):
    import shutil
    shutil.copytree(EXAMPLE, tmp_path / "g")
    rep = tmp_path / "g" / "projects" / "orders-api" / "reports" / "2026-11-07-a1b2c3d"
    (rep / "report.md").unlink()
    out = gk("render", "report", rep / "report.json", "--json", cwd=tmp_path / "g")
    assert json.loads(out.stdout)["result"]["written"].endswith("report.md") and (rep / "report.md").exists()
