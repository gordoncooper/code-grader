"""carry: the next report from the last one (IDs kept, citations moved to the new code), and report match."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from .common import (
    die, emit, finding_similarity, iter_evidence, kit_scoring_version, load_catalog, load_report, major, norm,
    pin_problem, repo_relative, REPORT_FORMAT, scoring_version_of, started_arg, utc_now, write_json,
)
from .config import project_dir_for_report, project_dir_from_args, with_config
from .zones import glob_to_regex, zone_for_path
from .publishing import private_path
from .authoring import authoring_config, load_for_edit, normalize_report, provenance, repo_reader, report_arg, save_edit


# The next report starts from the last one: findings keep their IDs, and every code citation is
# moved to where the same code is now. Benchmarks the change touches are cleared for re-grading.

# Graded again on any source change (pr-review.md): the rubric's `Re-grade: any source change` benchmarks.
ALWAYS_REGRADE = tuple(b["id"] for b in load_catalog()["benchmarks"] if b.get("regrade") == "any source change")


def _stripped(lines: list[str]) -> list[str]:
    return [ln.strip() for ln in lines]


def relocate_evidence(ev: dict, read_lines) -> tuple[dict, str]:
    """Move a code citation to the same code in another version of the repo.
    Returns (evidence, outcome): unchanged | moved | changed (the cited line itself changed) | lost.
    Quotes may be part of a line, as graders write them; they're kept unless the code changed."""
    if ev.get("type") != "code":
        return ev, "unchanged"
    lines = read_lines(str(ev.get("file", "")))
    if isinstance(lines, str):
        return ev, "lost"
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(ev.get("lines", "")))
    quote = norm(str(ev.get("quote", "")))
    if not m or not quote:
        return ev, "lost"
    start, end = int(m.group(1)), int(m.group(2) or m.group(1))
    span = end - start
    if end <= len(lines) and quote in norm("\n".join(lines[start - 1:end])):
        return ev, "unchanged"

    def label(n):
        return str(n) if span == 0 else f"{n}-{n + span}"

    hits = [i for i in range(max(1, len(lines) - span)) if quote in norm("\n".join(lines[i:i + span + 1]))]
    if hits:
        n = min(hits, key=lambda i: (abs(i + 1 - start), i)) + 1
        return dict(ev, lines=label(n)), "moved"
    first = next((norm(x) for x in str(ev.get("quote", "")).splitlines() if norm(x)), "")
    key = first.split("(")[0] + "(" if "(" in first else first[:24]
    if len(key.strip()) >= 8:
        hits = [i for i in range(len(lines)) if key in norm(lines[i])]
        if hits:
            n = min(hits, key=lambda i: (abs(i + 1 - start), i)) + 1
            e = min(len(lines), n + span)
            return dict(ev, lines=str(n) if e == n else f"{n}-{e}", quote="\n".join(lines[n - 1:e]).strip("\n")), "changed"
    return ev, "lost"


def benchmark_files(report: dict) -> dict[str, set[str]]:
    files: dict[str, set[str]] = {}
    for loc, ev, bid in iter_evidence(report):
        if bid and ev.get("type") == "code" and ev.get("file"):
            files.setdefault(bid, set()).add(repo_relative(ev["file"]))
    for f in report.get("findings", []):
        for p in f.get("paths", []) or []:
            files.setdefault(f.get("benchmark_id"), set()).add(repo_relative(p))
    return files


def suggest_touched(baseline: dict, changed: list[str], cfg: dict) -> tuple[list[str], list[str]]:
    """Benchmarks to re-grade for a change (pr-review.md step 1, the parts a tool can see), with reasons."""
    if not changed:
        return [], []
    changed = [repo_relative(c) for c in changed]
    touched, why = set(ALWAYS_REGRADE), [f"{', '.join(ALWAYS_REGRADE)}: any change to the code"]
    for bid, files in benchmark_files(baseline).items():
        hit = sorted(c for c in changed for f in files if c == f or glob_to_regex(f).match(c))
        if hit:
            touched.add(bid)
            why.append(f"{bid}: cites {', '.join(dict.fromkeys(hit))}")
    hot = sorted(c for c in changed if zone_for_path(c, cfg)[1] == "hot")
    if hot:
        touched.update(cfg["gates"]["benchmarks"])
        why.append(f"gates ({', '.join(cfg['gates']['benchmarks'])}): hot-zone files changed ({', '.join(hot)})")
    order = [b["id"] for b in load_catalog()["benchmarks"]]
    cites = sorted(why[1:], key=lambda w: order.index(w.split(":")[0]) if w.split(":")[0] in order else 99)
    return [b for b in order if b in touched], why[:1] + cites


def git_changed_files(repo: str, base: str, head: str) -> list[str] | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", repo, "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None


def carry_report(baseline: dict, read_lines, cfg: dict, commit: str, mode: str, base_commit: str | None,
                 touched: list[str] | None) -> tuple[dict, dict]:
    """The next report, started from `baseline`. touched=None means a full re-grade (every benchmark)."""
    r = copy.deepcopy(baseline)
    for key in ("rollup", "publishing"):   # a carried report is a new one, graded with this kit
        r.pop(key, None)
    r["suite_version"] = load_catalog()["suite_version"]
    r["mode"] = mode
    r["run"] = {**(baseline.get("run") or {}), "commit": commit, "base_commit": base_commit, "date": utc_now()}
    r["config"] = {**(baseline.get("config") or {}), "hash": cfg["hash"], "preset": cfg["preset"], "scoring_version": cfg["suite_version"]}
    r["top_priorities"] = []
    r["commands_run"] = []
    r["integrity_flags"] = []
    regrade = set(touched) if touched is not None else {b["id"] for b in r.get("benchmarks", [])}
    if mode == "pr":
        r["limitations"] = ["PR quick mode: benchmarks marked carried_forward were not re-graded."]
    else:
        r["limitations"], r["metrics"], r["metrics_notes"] = [], {}, {}
        r["scope_examined"] = ""
    r.pop("summary", None)
    stats = {"unchanged": 0, "moved": 0, "changed": [], "lost": []}

    def move(loc, items):
        out = []
        for ev in items:
            new, outcome = relocate_evidence(ev, read_lines)
            if outcome in ("unchanged", "moved"):
                stats[outcome] += 1
            else:
                stats[outcome].append(f"{loc}: {ev.get('file')}:{ev.get('lines')}")
            out.append(new)
        return out

    for f in r.get("findings", []):
        f["evidence"] = move(f"finding {f.get('id')}", f.get("evidence", []))
        if f.get("status") == "new":
            f["status"] = "open"
    for b in r.get("benchmarks", []):
        b["previous_score"] = b.get("score")
        b["change_explanation"] = None
        for i, s in enumerate(b.get("strengths", [])):
            s["evidence"] = move(f"{b['id']} strength #{i + 1}", s.get("evidence", []))
        for i, e in enumerate(b.get("enforcement", [])):
            e["evidence"] = move(f"{b['id']} enforcement #{i + 1}", e.get("evidence", []))
        if b["id"] in regrade:
            b["carried_forward"] = False
            if b.get("applicability") != "not_applicable":
                b["score"], b["confidence"] = None, None
            b["gaming_flags"] = []
        else:
            b["carried_forward"] = True
    for feat in r.get("feature_inventory", []):
        feat["evidence"] = move(f"feature '{feat.get('feature')}'", feat.get("evidence", []) or [])
    normalize_report(r, cfg)
    return r, stats


def cmd_carry(args) -> int:
    baseline = load_report(args.baseline)
    if (baseline.get("publishing") or {}).get("withheld") and not args.allow_withheld:
        die(f"{args.baseline} is a public copy: {', '.join(baseline['publishing']['withheld'])} have their evidence withheld. "
            f"Carry from the full report ({private_path(args.baseline)}), or pass --allow-withheld to keep them as they are.")
    if args.mode == "pr" and not args.base_commit:
        die("--mode pr needs --base-commit (the pull request's base)")
    args.report = args.baseline
    if major(scoring_version_of(baseline)) != major(kit_scoring_version()):
        die(f"{args.baseline} was graded under scoring {scoring_version_of(baseline)}, and this kit grades under scoring "
            f"{kit_scoring_version()} only. The two don't compare, so don't carry it: grade in full with `report new`")
    cfg = authoring_config(args, baseline)
    if pin_problem(cfg):
        die(pin_problem(cfg))
    read = repo_reader(args.repo)
    changed = list(args.changed or [])
    notes = []
    if args.mode == "pr" and not changed and args.base_commit:
        found = git_changed_files(args.repo, args.base_commit, args.commit)
        if found is None:
            notes.append("couldn't list the changed files with git; pass --changed FILE… or --touched ID…")
        changed = found or []
    if args.mode == "full":
        touched, why = None, ["full mode: every benchmark is re-graded"]
    else:
        touched, why = suggest_touched(baseline, changed, cfg)
        extra = [t.upper() for t in args.touched or [] if t.upper() not in touched]
        for t in extra:
            if t not in {b["id"] for b in load_catalog()["benchmarks"]}:
                die(f"--touched: unknown benchmark '{t}'")
        if extra:
            touched += extra
            why.append(f"--touched: {', '.join(extra)}")
    report, stats = carry_report(baseline, read, cfg, args.commit, args.mode, args.base_commit, touched)
    report = {"schema_version": REPORT_FORMAT, **{k: v for k, v in report.items() if k != "schema_version"}}
    report["run"].update({"started": started_arg(args, report["run"]["date"]), "grader": args.grader or report["run"].get("grader"),
                          "model": args.model, "session": args.session, "work_order": args.work_order})
    report["run"].pop("usage", None)
    pdir = project_dir_for_report(args.baseline) or project_dir_from_args(args)
    if args.out:
        out = Path(args.out)
    elif args.mode == "full" and pdir:
        out = pdir / "reports" / f"{report['run']['date'][:10]}-{args.commit[:7]}" / "report.json"
    else:
        die("give --out FILE (PR reports are written outside the grading repo)")
    if out.exists() and not args.force:
        die(f"{out} exists (use --force to replace it)")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    regrade = [b["id"] for b in report["benchmarks"] if not b.get("carried_forward")]
    result = {"report": str(out), "regrade": regrade, "why": why, "changed_files": changed, "notes": notes,
              "evidence": {"unchanged": stats["unchanged"], "moved": stats["moved"], "changed": stats["changed"], "lost": stats["lost"]}}
    lines = [f"wrote {out}", f"re-grade: {', '.join(regrade) or 'nothing'}"] + [f"  {w}" for w in why]
    lines.append(f"citations: {stats['unchanged']} unchanged, {stats['moved']} moved, {len(stats['changed'])} on lines that changed, "
                 f"{len(stats['lost'])} not found")
    lines += [f"  changed: {c} (check the finding still applies)" for c in stats["changed"]]
    lines += [f"  not found: {c} (fixed, moved elsewhere, or needs new evidence)" for c in stats["lost"]]
    lines += [f"note: {n}" for n in notes]
    lines.append(f"next: grade the benchmarks listed, update finding statuses, then `gradekit report check {out} --repo {args.repo}`")
    emit(args, result, "\n".join(lines))
    return 0


def match_findings(report: dict, baseline: dict, threshold: float = 0.35) -> list[dict]:
    """Pairs of (finding written fresh in this report, earlier finding it probably is)."""
    old_by_id = {f.get("id"): f for f in baseline.get("findings", [])}
    fresh = [f for f in report.get("findings", []) if f.get("id") not in old_by_id]
    have = {f.get("id") for f in report.get("findings", [])}
    missing = [f for f in baseline.get("findings", []) if f.get("id") not in have and f.get("status") != "fixed"]
    pairs = []
    for f in fresh:
        scored = sorted(((finding_similarity(f, o), o) for o in missing), key=lambda x: -x[0])
        scored = [(s, o) for s, o in scored if s >= threshold]
        if scored:
            best, o = scored[0]
            pairs.append({"new": f["id"], "old": o["id"], "similarity": best, "old_title": o.get("title"), "new_title": f.get("title"),
                          "ambiguous": len(scored) > 1 and scored[1][0] >= best - 0.1})
    claimed: dict[str, dict] = {}
    for p in sorted(pairs, key=lambda p: -p["similarity"]):
        if p["old"] in claimed:
            p["ambiguous"] = True
        else:
            claimed[p["old"]] = p
    return pairs


def rename_finding(report: dict, old_id: str, new_id: str, first_seen: str | None) -> None:
    for f in report.get("findings", []):
        if f.get("id") == old_id:
            f["id"] = new_id
            if first_seen:
                f["first_seen_commit"] = first_seen
            if f.get("status") == "new":
                f["status"] = "open"
    for b in report.get("benchmarks", []):
        b["finding_ids"] = [new_id if i == old_id else i for i in b.get("finding_ids", [])]
        for a in b.get("path_to_target", []):
            a["resolves"] = [new_id if i == old_id else i for i in a.get("resolves", [])]


def cmd_report_match(args) -> int:
    report, cfg = load_for_edit(args)
    baseline = load_report(args.baseline)
    pairs = match_findings(report, baseline, args.threshold)
    applied = []
    if args.apply:
        old = {f.get("id"): f for f in baseline.get("findings", [])}
        for p in pairs:
            if p["similarity"] >= args.apply_at and not p["ambiguous"]:
                rename_finding(report, p["new"], p["old"], old[p["old"]].get("first_seen_commit"))
                applied.append(p)
        if applied:
            save_edit(args, report, cfg)
    lines = [f"{p['new']} looks like {p['old']} ({p['similarity']:.2f}{', ambiguous' if p['ambiguous'] else ''}): "
             f"\"{p['new_title']}\" ~ \"{p['old_title']}\"" for p in pairs] or ["no likely matches"]
    if args.apply:
        lines.append(f"renamed {len(applied)}: " + (", ".join(f"{p['new']} → {p['old']}" for p in applied) or "none")
                     + f" (only unambiguous matches ≥ {args.apply_at})")
    else:
        lines.append("to keep an earlier ID: `report match … --apply`, or re-add the finding with `finding add --id OLD-ID`")
    emit(args, {"matches": pairs, "applied": [{"from": p["new"], "to": p["old"]} for p in applied]}, "\n".join(lines))
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_report_match(rsub):
    q = rsub.add_parser("match", help="suggest which earlier finding each newly written finding is, to keep its ID")
    report_arg(q)
    q.add_argument("--baseline", required=True, help="the previous report")
    q.add_argument("--threshold", type=float, default=0.35, help="lowest similarity to suggest (0–1)")
    q.add_argument("--apply", action="store_true", help="rename unambiguous matches to their earlier IDs")
    q.add_argument("--apply-at", type=float, default=0.6, help="lowest similarity --apply acts on")
    q.set_defaults(fn=cmd_report_match)


def add_carry(sub):
    p = sub.add_parser("carry", help="start the next report from the last one, with citations moved to the new code")
    p.add_argument("baseline", help="the last report (the full one, not the public copy, if it withholds findings)")
    p.add_argument("--repo", required=True, metavar="DIR_OR_ZIP", help="the code at the new commit")
    p.add_argument("--commit", required=True, help="the new commit")
    p.add_argument("--mode", choices=["pr", "full"], default="pr")
    p.add_argument("--base-commit", help="pr mode: the pull request's base commit")
    p.add_argument("--changed", nargs="+", metavar="FILE", help="files the change touched (default: from git, if --repo is a checkout)")
    p.add_argument("--touched", nargs="+", metavar="ID", help="more benchmarks to re-grade, on top of those suggested from the changed files")
    p.add_argument("--out", metavar="FILE", help="where to write (required in pr mode; full mode defaults to a new report folder)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-withheld", action="store_true", help="carry from a public copy anyway")
    p.add_argument("--grader", help="the agent or person grading now (default: the baseline's)")
    provenance(p)
    with_config(p)
    p.set_defaults(fn=cmd_carry)
