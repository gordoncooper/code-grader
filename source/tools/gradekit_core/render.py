"""render: Markdown from data (report.md, the PR title and body, the PR-check comment, the improvement log)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .common import (
    benchmarks_by_id, dash, DECISIONS_FILE, die, emit, enforcement_items, evidence_line, load_catalog, load_json,
    load_report, PILLARS, PROJECT_FILE, utc_now,
)
from .config import load_config, project_dir_or_die, PUBLISHING_DEFAULTS, report_folders, with_config
from .rollup import compute_rollup, decision_for
from .publishing import redact_report, sensitive_ids
from .compare import compute_diff
from .settings import append_entries
from .authoring import authoring_config
from .guard import render_guard


# Markdown made from report data, so every report, pull request, PR check and improvement log
# has the same layout and no hand-copied numbers. Public text never carries withheld details.

def md_cell(text) -> str:
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ").strip()


def report_label(report: dict) -> tuple[str, str, str]:
    run = report.get("run") or {}
    project = run.get("project") or (report.get("component") or {}).get("name") or "project"
    commit = str(run.get("commit") or "?")[:7]
    return project, commit, str(run.get("date") or "")[:10]


def public_view(report: dict, cfg: dict) -> dict:
    """The report as it may be shown publicly: sensitive findings withheld unless the repo is private."""
    if not (cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public") or (report.get("publishing") or {}).get("redacted"):
        return report
    public, leaks = redact_report(report)
    if leaks:
        die("withheld text still appears elsewhere in the report; fix these first (or run `gradekit redact`):\n  "
            + "\n  ".join(leaks))
    return public


def rendering_rollup(report: dict, cfg: dict) -> dict:
    roll = compute_rollup(report, cfg)
    if roll["weight_issues"]:
        die("weights don't match the config; run `gradekit report check` first:\n  " + "\n  ".join(roll["weight_issues"]))
    return roll


def decisions_block(roll: dict, decline_boxes: bool = False) -> list[str]:
    """The pending questions as a checklist. With decline_boxes (a report PR), each gets a second box to decline it,
    so a person answers by ticking and the decide CI job records it."""
    pending = [p for p in roll["priorities"] if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
    if not pending:
        return ["None."]
    out = []
    for p in pending:
        out.append(f"- [ ] **{p['action_id']}:** {p.get('decision_question')}")
        if decline_boxes:
            out.append(f"  - [ ] Decline {p['action_id']} instead")
    return out


CHECKLIST = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(?:\*\*)?(decline\s+)?([A-Z]\d+-act-\d+)\b", re.I | re.M)


def checklist_answers(text: str) -> tuple[str | None, dict, list[str]]:
    """A report PR's checklist: the project it names (`<!-- gradekit:project=NAME -->`), {action_id: approved} for each
    ticked box (a "Decline ID" box declines), and the IDs with both boxes ticked (no answer). Unticked boxes are no answer."""
    m = re.search(r"<!--\s*gradekit:project=([\w.-]+)\s*-->", text or "")
    seen: dict[str, set] = {}
    for box, decline, aid in CHECKLIST.findall(text or ""):
        if box.strip():
            seen.setdefault(aid, set()).add(not decline)
    both = sorted(a for a, v in seen.items() if len(v) > 1)
    return (m.group(1) if m else None), {a: v.pop() for a, v in seen.items() if len(v) == 1}, both


def decision_rows(pdir: Path) -> tuple[Path | None, list[dict]]:
    """The newest full report's decision questions, each with its status: [{action_id, question, benchmark_id, action,
    status, decided_by, date, answer}]."""
    folders = [f for f in report_folders(pdir) if load_json(f / "report.json").get("mode") != "pr"]
    if not folders:
        return None, []
    rpath = folders[-1] / "report.json"
    report = load_json(rpath)
    cfg = load_config(argparse.Namespace(project_dir=str(pdir), project=None, config=None, component=None), report, quiet=True)
    rows = []
    for b in report.get("benchmarks", []):
        for a in b.get("path_to_target", []):
            if not a.get("requires_human_decision"):
                continue
            d = decision_for(a, cfg) or {}
            rows.append({"action_id": a["id"], "question": a.get("decision_question"), "benchmark_id": b["id"], "action": a.get("action"),
                         "status": d.get("status", "pending"), "decided_by": d.get("decided_by"), "date": d.get("date"),
                         "answer": d.get("answer"), "note": d.get("note")})
    return rpath, rows


def cmd_decisions(args) -> int:
    pdir = project_dir_or_die(args)
    rpath, rows = decision_rows(pdir)
    if args.approved:
        rows = [r for r in rows if r["status"] == "approved"]
        emit(args, {"report": str(rpath) if rpath else None, "approved": rows}, "\n".join(r["action_id"] for r in rows))
        return 0
    lines = [f"{r['action_id']} {r['status']}" + (f" by {r['decided_by']} on {r['date']}" if r.get("decided_by") else "")
             + f": {r['question']}" + (f" ({r['note']})" if r.get("note") else "") for r in rows]
    emit(args, {"report": str(rpath) if rpath else None, "decisions": rows},
         "\n".join(lines) if lines else "no decision questions in the newest report")
    return 0


def cmd_decide(args) -> int:
    """Record answers in decisions.json (append-only): by ID, or from a report PR's checklist."""
    text = None
    if args.from_checklist:
        text = sys.stdin.read() if args.from_checklist == "-" else Path(args.from_checklist).read_text(encoding="utf-8", errors="replace")
    named, ticked, both = checklist_answers(text) if text is not None else (None, {}, [])
    if getattr(args, "project_dir", None) or getattr(args, "project", None):
        pdir = project_dir_or_die(args)
    elif named:
        pdir = Path(args.grading_repo or ".") / "projects" / named
        if not (pdir / PROJECT_FILE).exists():
            die(f"the checklist names project {named}, but {pdir / PROJECT_FILE} doesn't exist (run from the grading repo's root, or give --grading-repo)")
    else:
        die("say which project: --project-dir projects/NAME, or a checklist with its <!-- gradekit:project=NAME --> marker")
    wanted = dict(ticked)
    wanted.update({a: True for a in args.approve or []})
    wanted.update({a: False for a in args.decline or []})
    if not wanted:
        emit(args, {"added": [], "skipped": [], "conflicting": both},
             "\n".join([f"{a}: both approve and decline are ticked, so no answer was recorded" for a in both])
             or "nothing ticked or named: no decisions to record")
        return 0
    rpath, rows = decision_rows(pdir)
    by_id = {r["action_id"]: r for r in rows}
    unknown = [a for a in wanted if a not in by_id]
    if unknown:
        die(f"{', '.join(unknown)}: not a decision question in the newest report ({rpath or 'none'}); "
            f"`gradekit decisions --project-dir {pdir}` lists them")
    date = args.date or utc_now()[:10]
    added, skipped = [], []
    for aid, approved in wanted.items():
        r = by_id[aid]
        if r["status"] == ("approved" if approved else "declined"):
            skipped.append(aid)   # already answered that way: running again on the same checklist changes nothing
            continue
        e = {"action_id": aid, "question": r["question"], "approved": approved}
        if args.answer:
            e["answer"] = args.answer
        e.update({"decided_by": args.by, "date": date})
        added.append(e)
    rerendered = None
    if added:
        f = pdir / DECISIONS_FILE
        f.write_text(append_entries(f.read_text(encoding="utf-8") if f.exists() else None, "decisions", added), encoding="utf-8")
        md = rpath.with_name("report.md") if rpath else None
        if md and md.exists():   # report.md shows each decision's status: keep it in step, or CI calls it stale
            report = load_json(rpath)
            cfg = load_config(argparse.Namespace(project_dir=str(pdir), project=None, config=None, component=None), report, quiet=True)
            md.write_text(render_report_md(report, cfg), encoding="utf-8")
            rerendered = str(md)
    msg = [f"{'approved' if e['approved'] else 'declined'} {e['action_id']} (by {e['decided_by']})" for e in added]
    msg += [f"{a}: already {by_id[a]['status']}" for a in skipped]
    msg += [f"{a}: both approve and decline are ticked, so no answer was recorded" for a in both]
    if added and args.by.lower().startswith("agent"):
        msg.append("note: answers by an agent count only with [review] allow_agent_decisions = true in project.toml")
    if rerendered:
        msg.append(f"updated {rerendered} to show them")
    emit(args, {"file": str(pdir / DECISIONS_FILE), "added": added, "skipped": skipped, "conflicting": both, "report_md": rerendered},
         "\n".join(msg) or "nothing new")
    return 0


def provenance_line(run: dict) -> str:
    """Who graded, with what, and how long it took."""
    who = " ".join(x for x in (str(run.get("grader") or "").strip(), f"({run['model']})" if run.get("model") else "") if x)
    parts = [f"Graded by {md_cell(who or 'unknown')}"]
    mins = (run.get("usage") or {}).get("minutes")
    if mins is not None:
        parts.append(f"{mins:g} min")
    for key, label in (("work_order", "work order"), ("session", "session")):
        if run.get(key):
            parts.append(f"{label} `{md_cell(run[key])}`")
    return "*" + " · ".join(parts) + "*"


def blocker_text(x: dict) -> str:
    """One maturity blocker for people: what it requires, and which benchmark or findings are short of it."""
    who = x.get("benchmark_id") or ", ".join(x.get("finding_ids") or [])
    return f"{x['requirement']} ({who + ' ' if who else ''}now {dash(x.get('current'))})"


def render_report_md(report: dict, cfg: dict, catalog: dict | None = None) -> str:
    catalog = catalog or load_catalog()
    report = public_view(report, cfg)
    roll = rendering_rollup(report, cfg)
    project, commit, date = report_label(report)
    by_id = benchmarks_by_id(report)
    fz = roll["finding_zones"]
    gates = {g["benchmark_id"]: g for g in roll["gates"]}
    mat = roll["maturity"]
    findings = report.get("findings", [])
    out = [f"# Grading report: {project} @ {commit} ({date})", ""]
    if report.get("mode") == "pr":
        out += [f"*PR check against base `{str((report.get('run') or {}).get('base_commit') or '?')[:7]}`. "
                f"Untouched benchmarks are carried forward from the last full report.*", ""]
    out += [provenance_line(report.get("run") or {}), ""]

    out += ["## Summary", "", f"Overall **{dash(roll['overall_score'])}**"
            + (" (capped by a failed gate)" if roll["overall_cap_applied"] else "")
            + f", maturity **{mat['current_level']}**" + (f" (next: {mat['next_level']})" if mat.get("next_level") else "") + "."]
    if str(report.get("summary") or "").strip():
        out += ["", report["summary"].strip()]
    out.append("")

    out += ["## Gates and maturity", "", "| Gate | Score | Status |", "|---|:-:|---|"]
    for g in roll["gates"]:
        b = by_id.get(g["benchmark_id"], {})
        out.append(f"| {g['benchmark_id']} {md_cell(b.get('name'))} | {dash(g['score'])} | {g['status']} ({', '.join(g['why'])}) |")
    out.append("")
    if mat.get("level_before_integrity_cap"):
        out += [f"Maturity is capped at {mat['current_level']} by an integrity flag (it would be {mat['level_before_integrity_cap']}).", ""]
    if mat.get("next_level"):
        blockers = "; ".join(blocker_text(x) for x in mat.get("blockers", []))
        out += [f"Blocking {mat['next_level']}: {blockers or 'nothing'}", ""]

    out += ["## Scorecard", "", "Gates are marked ★. Weight is the weight used, after applicability.", "",
            "| ID | Benchmark | Score | Target | Weight | Confidence | Applicability | Notes |", "|---|---|:-:|:-:|:-:|---|---|---|"]
    for pillar in PILLARS:
        rows = [b for b in report["benchmarks"] if b.get("pillar") == pillar]
        if not rows:
            continue
        for b in rows:
            why = b.get("rationale") or b.get("change_explanation") or b.get("applicability_reason") or ""
            out.append(f"| {b['id']}{' ★' if b['id'] in gates else ''} | {md_cell(b.get('name'))} | {dash(b.get('score'))} | "
                       f"{dash(roll['targets'].get(b['id']))} | {b.get('weight')} | {dash(b.get('confidence'))} | "
                       f"{b.get('applicability')} | {md_cell(why)} |")
        pname = catalog.get("pillars", {}).get(pillar, {})
        pname = pname.get("name") if isinstance(pname, dict) else pname
        out.append(f"| | **{pillar}{(' ' + md_cell(pname)) if pname else ''}** | **{dash(roll['pillar_scores'].get(pillar))}** | | | | | |")
    out += [f"| | **Overall** | **{dash(roll['overall_score'])}** | | | | | |", ""]

    app = roll.get("applicability", {})
    notes = [f"- **{bid}** limited: {by_id[bid].get('applicability_reason')}" for bid in app.get("limited", [])]
    notes += [f"- **{bid}** not applicable: {by_id[bid].get('applicability_reason')}" for bid in app.get("not_applicable", [])]
    notes += [f"- **{bid}** weight note: {n}" for bid, n in (app.get("weight_notes") or {}).items()]
    out += ["## Applicability and weight notes", ""] + (notes or ["Every benchmark fully applies, and no weight looked wrong."]) + [""]

    top = roll["priorities"][:10]
    out += ["## Top priorities", ""]
    for i, p in enumerate(top, 1):
        dec = p.get("decision") or {}
        tag = ""
        if p.get("requires_human_decision"):
            tag = f" — **decision {dec.get('status', 'pending')}:** {p.get('decision_question')}"
        out.append(f"{i}. **{p['action_id']}** (tier {p['tier']}, {p['zone']} zone, +{p['gain']}, effort {p['effort']}): {p.get('action')}{tag}")
    out += (["No actions."] if not top else []) + [""]

    out += ["## Decisions needed", ""] + decisions_block(roll)
    decided = [p for p in roll["priorities"] if p.get("requires_human_decision")
               and (p.get("decision") or {}).get("status") in ("approved", "declined")]
    if decided:   # answered ones too, wherever their actions rank
        out += ["", "Decided:"] + [f"- **{p['action_id']}:** decision {p['decision']['status']}"
                                   + "".join(f", {x}" for x in (p["decision"].get("decided_by"), p["decision"].get("date")) if x)
                                   + f": {p.get('decision_question')}" for p in decided]
    out += ["", "Answers go in `decisions.json`: tick the boxes in this report's pull request (the grading CI records them), "
            "run `gradekit decide --approve ID --by NAME`, or use the suite website's *Review a report* page.", ""]

    metrics = report.get("metrics") or {}
    if metrics:
        mn = report.get("metrics_notes") or {}
        out += ["## Metrics", "", "| Metric | Value | Note |", "|---|---|---|"]
        out += [f"| {k} | {dash(v)} | {md_cell(mn.get(k))} |" for k, v in metrics.items()] + [""]

    out += ["## Findings", ""]
    if findings:
        out += ["| ID | Severity | Zone | Status | Title |", "|---|---|---|---|---|"]
        for f in findings:
            z = fz.get(f.get("id"), {})
            out.append(f"| {f.get('id')} | {f.get('severity')} | {z.get('criticality', '')} | {f.get('status')} | {md_cell(f.get('title'))} |")
        for status, label in (("fixed", "Fixed since the last report"), ("regressed", "Regressed (fixed before, back again)")):
            ids = [f["id"] for f in findings if f.get("status") == status]
            if ids:
                out += ["", f"{label}: {', '.join(ids)}."]
    else:
        out.append("None.")
    out.append("")

    feats = report.get("feature_inventory") or []
    gaps = report.get("gap_register") or []
    if feats:
        out += ["## Feature inventory", "", "| Feature | Claimed in | Status |", "|---|---|---|"]
        out += [f"| {md_cell(x.get('feature'))} | {md_cell(x.get('source'))} | {x.get('status')} |" for x in feats] + [""]
    if gaps:
        out += ["## Gap register", "", "| ID | Gap | Severity | Necessity | Status | Benchmarks |", "|---|---|---|---|---|---|"]
        out += [f"| {g.get('id')} | {md_cell(g.get('gap'))} | {g.get('severity')} | {g.get('necessity')} | {g.get('status')} | "
                f"{', '.join(g.get('benchmark_ids', []))} |" for g in gaps] + [""]

    out += ["## Benchmark detail", ""]
    fmap = {f.get("id"): f for f in findings}
    for b in report["benchmarks"]:
        if b.get("applicability") == "not_applicable":
            continue
        out.append(f"### {b['id']} {b.get('name')}: {dash(b.get('score'))} (target {dash(roll['targets'].get(b['id']))})")
        out.append("")
        if b.get("carried_forward"):
            out += ["Carried forward from the last full report.", ""]
        for label, text in (("Why", b.get("rationale")), ("Change", b.get("change_explanation"))):
            if text:
                out += [f"{label}: {text}", ""]
        for s in b.get("strengths", []):
            out.append(f"- Strength: {s.get('note')} ({'; '.join(evidence_line(e) for e in s.get('evidence', []))})")
        for fid in b.get("finding_ids", []):
            f = fmap.get(fid, {})
            evs = [evidence_line(e) for e in f.get("evidence", []) if e.get("type") != "withheld"]
            out.append(f"- Finding {fid} ({f.get('severity')}, {f.get('status')}): {f.get('title')}" + (f" ({'; '.join(evs)})" if evs else ""))
        for e in enforcement_items(b):
            evs = '; '.join(evidence_line(x) for x in e["evidence"])
            out.append(f"- Enforced by: {e['note']} ({evs})" if e["note"] else f"- Enforced by: {evs}")
        lim = (roll.get("limits") or {}).get(b.get("id"))
        held = [w for w in (lim or {}).get("why", []) if w["kind"] in ("cap", "critical")]
        if held:
            out.append(f"- Limit: at most {min(w['max'] for w in held)} while {'; '.join(w['why'] for w in held)}")
        for a in b.get("path_to_target", []):
            out.append(f"- Next: **{a['id']}** → {a.get('expected_new_score')} (effort {a.get('effort')}): {a.get('action')}"
                       + (" *(needs a decision)*" if a.get("requires_human_decision") else ""))
        out.append("")

    flags = report.get("integrity_flags") or []
    gaming = [(b["id"], g) for b in report["benchmarks"] for g in b.get("gaming_flags", [])]
    if flags or gaming:
        out += ["## Integrity and gaming flags", ""]
        out += [f"- Integrity: {f.get('description')} ({'; '.join(evidence_line(e) for e in f.get('evidence', []))})" for f in flags]
        out += [f"- Gaming ({bid}): {g}" for bid, g in gaming] + [""]

    out += ["## Limitations", ""]
    out += [f"- {x}" for x in report.get("limitations") or []] or ["- None recorded."]
    h = report.get("holdout") or {}
    if h.get("run"):
        out.append(f"- Hidden checks: {h.get('checks_run')} run, {h.get('pass_rate', 0):.0%} passed.")
    out += ["", f"<sub>Rendered by gradekit from report.json (suite {report.get('suite_version')}, config {roll['config_hash']}).</sub>", ""]
    return "\n".join(out)


def roll_pending(roll: dict) -> bool:
    return any(p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending" for p in roll.get("priorities", []))


def review_link(site: str | None, grading_repo: str | None, project: str, ref: str, folder: str | None = None,
                view: str | None = None) -> str | None:
    """A deep link to Review (any host serving the site): the project at a ref, and optionally one report and a view
    such as "tab=decisions"."""
    if not (site and grading_repo):
        return None
    from urllib.parse import quote
    link = f"{site.rstrip('/')}/app/review.html?repo={quote(grading_repo, safe='/:')}&project={quote(project)}&ref={quote(ref, safe='/')}"
    if folder:
        link += f"&report={quote(folder)}"
    return link + (f"#{view}" if view else "")


def render_report_pr(report: dict, cfg: dict, site: str | None = None, grading_repo: str | None = None,
                     branch: str | None = None, folder: str | None = None) -> dict:
    report = public_view(report, cfg)
    roll = rendering_rollup(report, cfg)
    project, commit, date = report_label(report)
    folder = folder or f"{date}-{commit}"
    branch = branch or f"report/{project}/{folder}"
    mat = roll["maturity"]
    title = f"Report: {project} {date} — {dash(roll['overall_score'])} ({mat['current_level']})"
    body = [f"Grading report for **{project}** at `{commit}`: overall **{dash(roll['overall_score'])}**"
            + (" (capped by a failed gate)" if roll["overall_cap_applied"] else "")
            + f", maturity **{mat['current_level']}**" + (f" (next: {mat['next_level']})." if mat.get("next_level") else ".")]
    if str(report.get("summary") or "").strip():
        body += ["", report["summary"].strip()]
    body += ["", "**Gates**", ""]
    body += [f"- {g['benchmark_id']}: {dash(g['score'])} — {g['status']}" for g in roll["gates"]]
    blockers = "; ".join(blocker_text(x) for x in mat.get("blockers", []))
    if mat.get("next_level"):
        body += ["", f"Blocking {mat['next_level']}: {blockers or 'nothing'}"]
    pending = roll_pending(roll)
    body += ["", "**Decisions needed**", ""] + decisions_block(roll, decline_boxes=pending)
    if pending:
        body += ["", "Tick a question's first box to approve it, or its *Decline* box to decline. The grading CI's decide job "
                 "records each answer in `decisions.json` on this branch, under your name; without it, run "
                 f"`gradekit decide --project {project} --from-checklist FILE --by NAME` on this description."]
    link = review_link(site, grading_repo, project, branch, folder, "tab=decisions" if pending else None)
    if link:
        body += ["", f"[Review this report and answer the decisions]({link})"]
    body += ["", f"Files: `projects/{project}/reports/{folder}/` (report.json, report.md).", "", f"<!-- gradekit:project={project} -->"]
    return {"title": title, "body": "\n".join(body) + "\n", "branch": branch}


def render_check_comment(diff: dict, new: dict, cfg: dict) -> str:
    """The PR-check comment (pr-review.md step 4). Sensitive findings are always withheld: PR comments are often public."""
    sens = sensitive_ids(new)
    names = {b["id"]: b["name"] for b in load_catalog()["benchmarks"]}

    def title(f):
        return f"{names.get(f['id'].split('-')[0], '')} issue (details withheld)" if f["id"] in sens else f["title"]

    applicable = [b for b in new.get("benchmarks", []) if b.get("applicability") != "not_applicable"]
    regraded = [b["id"] for b in applicable if not b.get("carried_forward")]
    fixed_by = {}
    for f in diff["findings"]["fixed"]:
        fixed_by.setdefault(f["id"].split("-")[0], []).append(f["id"])
    changes = [f"{c['id']} {dash(c['old'])} → {dash(c['new'])}" + (f" ({', '.join(fixed_by[c['id']])} fixed)" if c["id"] in fixed_by else "")
               for c in diff["score_changes"]]
    fresh = [f for f in diff["findings"]["new"] if not f.get("pre_existing")]
    pre = [f for f in diff["findings"]["new"] if f.get("pre_existing")]
    roll = compute_rollup(new, cfg)
    pending = [p for p in roll["priorities"] if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
    lines = [f"**PR check: {diff['verdict']}**",
             ("Re-graded: every applicable benchmark (full report)" if len(regraded) == len(applicable) else
              f"Re-graded: {', '.join(regraded) or 'none'} (others carried forward)"),
             f"Changes: {' · '.join(changes) or 'none'}",
             f"Overall: {dash(diff['overall']['old'])} → {dash(diff['overall']['new'])} · Maturity: {diff['maturity']['old']} → {diff['maturity']['new']}",
             "New findings: " + ("; ".join(f"{f['id']}: {title(f)}, {f['effective_severity']}, {f['zone']} zone" for f in fresh) or "none"),
             "Regressions: " + ("; ".join(r if not any(i in r for i in sens) else r.split(":")[0] + ": details withheld" for r in diff["regressions"]) or "none")]
    if pre:
        lines.append("Already there before this change: " + "; ".join(f"{f['id']}: {title(f)}" for f in pre))
    if diff["findings"].get("accepted"):
        lines.append("Accepted: " + "; ".join(f"{f['id']}: {title(f)} ({'by ' + f['decided_by'] if f.get('decided_by') else 'no entry in dispositions.json'})"
                                              for f in diff["findings"]["accepted"]))
    if diff.get("holdout"):
        lines.append(f"Hidden checks: {diff['holdout']['old']:.0%} → {diff['holdout']['new']:.0%}")
    lines.append("Decisions needed: " + ("; ".join(f"{p['action_id']}: {p.get('decision_question')}" for p in pending) or "none"))
    lines += [f"Note: {n}" for n in diff["notes"] if not any(i in n for i in sens)]
    return "\n".join(lines) + "\n"


LOG_KEYS = {"done": ("action_id", "commit", "resolves", "check"), "blocked": ("action_id", "question"),
            "skipped": ("action_id", "reason"), "behavior_changes": None, "new_issues": None}


def log_commits(commit) -> str:
    """An action's commit(s) in the improvement log: one SHA, several (a list, or separated by spaces or commas), or none."""
    shas = commit if isinstance(commit, list) else re.split(r"[\s,]+", str(commit or "").strip())
    shas = [str(s).strip()[:10] for s in shas if str(s).strip()]
    return ", ".join(f"`{s}`" for s in shas) if shas else "`?`"


def render_improve_log(log: dict, report: dict | None = None, cfg: dict | None = None, guard: dict | None = None) -> str:
    for key in log:
        if key not in LOG_KEYS and key != "notes":
            die(f"improvement log: unknown section '{key}' (known: {', '.join(LOG_KEYS)}, notes)")
    blocked = list(log.get("blocked") or [])
    skipped = list(log.get("skipped") or [])
    if report is not None and cfg is not None:
        listed = {x.get("action_id") for x in (log.get("done") or []) + blocked + skipped}
        for p in compute_rollup(report, cfg)["priorities"]:
            st = (p.get("decision") or {}).get("status")
            if p.get("requires_human_decision") and p["action_id"] not in listed:
                if st == "pending":
                    blocked.append({"action_id": p["action_id"], "question": p.get("decision_question")})
                elif st == "declined":
                    skipped.append({"action_id": p["action_id"], "reason": "decision declined"})
    out = ["## Improvement log", ""]
    if log.get("notes"):
        out += [str(log["notes"]).strip(), ""]
    if guard is not None:
        out += render_guard(guard) + [""]
    out += ["**Done** (claims; the next independent grading verifies them)", ""]
    out += [f"- **{d.get('action_id')}** in {log_commits(d.get('commit'))}" + (f", resolves {', '.join(d.get('resolves') or [])}" if d.get("resolves") else "")
            + (f". Checked with: {d['check']}" if d.get("check") else "") for d in log.get("done") or []] or ["- Nothing yet."]
    out += ["", "**Blocked** (waiting on a decision)", ""]
    out += [f"- **{b.get('action_id')}:** {b.get('question')}" for b in blocked] or ["- None."]
    out += ["", "**Skipped**", ""]
    out += [f"- **{s.get('action_id')}:** {s.get('reason')}" for s in skipped] or ["- None."]
    for key, label in (("behavior_changes", "Behavior changes"), ("new_issues", "New issues noticed")):
        out += ["", f"**{label}**", ""] + ([f"- {x}" for x in log.get(key) or []] or ["- None."])
    return "\n".join(out) + "\n"


def render_out(args, text: str, default_path: Path | None) -> None:
    dest = args.out or (str(default_path) if default_path and not args.stdout else None)
    if dest and dest != "-":
        Path(dest).write_text(text, encoding="utf-8")
        args._result = {"written": dest, "markdown": text}
        print(f"wrote {dest}")
    else:
        args._result = {"written": None, "markdown": text}
        print(text, end="")


def cmd_render_report(args) -> int:
    report = load_report(args.report)
    cfg = authoring_config(args, report)
    text = render_report_md(report, cfg)
    render_out(args, text, Path(re.sub(r"\.json$", "", args.report) + ".md"))
    return 0


def cmd_render_pr(args) -> int:
    report = load_report(args.report)
    cfg = authoring_config(args, report)
    folder = Path(args.report).resolve().parent.name if Path(args.report).name == "report.json" else None
    pr = render_report_pr(report, cfg, args.site, args.grading_repo_url, args.branch, folder)
    args._result = pr
    print(f"{pr['title']}\n\n{pr['body']}", end="")
    return 0


def cmd_render_check(args) -> int:
    old, new = load_report(args.old), load_report(args.new)
    args.report = args.new
    cfg = authoring_config(args, new)
    text = render_check_comment(compute_diff(old, new, cfg, cfg), new, cfg)
    render_out(args, text, None)
    return 0


def cmd_render_log(args) -> int:
    log = load_json(args.log)
    report, cfg = None, None
    if args.report:
        report = load_report(args.report)
        cfg = authoring_config(args, report)
    guard = None
    if args.guard:
        guard = load_json(args.guard)
        if "verdict" not in guard or "items" not in guard:
            die(f"{args.guard} isn't a `guard compare` result (it writes .git/gradekit/guard-compare.json, or --out)")
    render_out(args, render_improve_log(log, report, cfg, guard), None)
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_decisions(sub):
    p = sub.add_parser("decisions", help="the newest report's decision questions and their answers")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--approved", action="store_true", help="only the approved ones: exactly what may be acted on")
    p.set_defaults(fn=cmd_decisions)


def add_decide(sub):
    p = sub.add_parser("decide", help="record answers to decision questions in decisions.json (by ID, or from a PR checklist)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--approve", nargs="+", metavar="ACTION_ID")
    p.add_argument("--decline", nargs="+", metavar="ACTION_ID")
    p.add_argument("--from-checklist", metavar="FILE", help="a report PR's description ('-' for stdin): each ticked box approves its action")
    p.add_argument("--by", required=True, help="who decided (a name, email or code-host login)")
    p.add_argument("--answer", help="an answer or conditions, recorded with each decision")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="default: today (UTC)")
    p.set_defaults(fn=cmd_decide)


def add_render(sub):
    p = sub.add_parser("render", help="markdown from report data: report.md, PR title/body, PR-check comment, improvement log")
    rsub = p.add_subparsers(dest="render_cmd", required=True, metavar="WHAT")
    def render_dest(q, default_note):
        q.add_argument("--out", metavar="FILE", help=f"where to write ('-' for stdout; default: {default_note})")
        q.add_argument("--stdout", action="store_true", help="print instead of writing the default file")
    q = rsub.add_parser("report", help="report.md from report.json (sensitive findings withheld in public grading repos)")
    q.add_argument("report")
    render_dest(q, "beside the report, e.g. report.md")
    with_config(q)
    q.set_defaults(fn=cmd_render_report)
    q = rsub.add_parser("pr", help="the grading pull request: branch, title and body (title on the first line)")
    q.add_argument("report")
    q.add_argument("--site", metavar="URL", help="the suite website, for a link to its Review page")
    q.add_argument("--grading-repo-url", metavar="URL", help="the grading repo (e.g. https://github.com/acme/grading), for that link")
    q.add_argument("--branch", help="default: report/<project>/<date>-<commit>")
    with_config(q)
    q.set_defaults(fn=cmd_render_pr)
    q = rsub.add_parser("check", help="the PR-check comment, comparing the baseline report with the PR report")
    q.add_argument("old", help="baseline report (newest merged report)")
    q.add_argument("new", help="the PR report (mode pr)")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_check)
    q = rsub.add_parser("log", help="the improver's log, from a small JSON file (see prompts/improver.md)")
    q.add_argument("log", help="improve-log.json")
    q.add_argument("--report", help="the report worked from: adds pending decisions as blocked and declined ones as skipped")
    q.add_argument("--guard", metavar="FILE", help="the `guard compare` result: adds the before → after table of the code's checks")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_log)
