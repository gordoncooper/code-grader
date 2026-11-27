"""Publishing: sensitive findings, private and public copies of a report, redaction."""
from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

from .common import (
    all_text, die, emit, level_num, load_catalog, load_json, load_report, norm, repo_relative, write_json,
)
from .config import folder_reports, load_config, project_dir_for_report
from .rollup import weighted


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("private_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


# A grading repo may be public. Findings marked "sensitive": true (usually security issues) keep
# everything scoring needs (id, benchmark, severity, status and the files they concern, so zones,
# gates, scores and priorities come out the same) and lose what would help an attacker: the title,
# quotes, commands and the wording of the actions that fix them. The full report is kept privately.

WITHHELD_NOTE = "Details withheld from the public report; whoever ran the grade has the private copy."
FINDING_KEEP = ("id", "benchmark_id", "severity", "status", "first_seen_commit", "disposition", "fingerprint")
LEAK_MIN = 12        # shortest withheld string worth searching for
LEAK_LINE_MIN = 24   # lines of a withheld quote searched for on their own


def sensitive_ids(report: dict) -> set[str]:
    return {f.get("id") for f in report.get("findings", []) if f.get("sensitive") is True}


def _withheld_text(f: dict) -> list[tuple[str, bool]]:
    """(text, is_quoted_code) pairs worth searching for. Quoted code is only a leak outside other
    findings' own quotes: another finding may cite the same public line for an unrelated reason."""
    out = [(f.get("title"), False), (f.get("disposition_concern"), False)]
    for ev in f.get("evidence", []):
        for key in ("quote", "excerpt", "command", "note", "searched"):
            val = ev.get(key)
            quoted = key in ("quote", "excerpt")
            out.append((val, quoted))
            if quoted and isinstance(val, str):
                out += [(ln, True) for ln in val.splitlines() if len(norm(ln)) >= LEAK_LINE_MIN]
    return [(norm(t), q) for t, q in out if isinstance(t, str) and len(norm(t)) >= LEAK_MIN and t != WITHHELD_NOTE]


def _without_quotes(obj):
    if isinstance(obj, dict):
        return {k: _without_quotes(v) for k, v in obj.items() if k not in ("quote", "excerpt")}
    if isinstance(obj, list):
        return [_without_quotes(v) for v in obj]
    return obj


def _ids_text(ids) -> str:
    ids = sorted(ids)
    return ("issue " if len(ids) == 1 else "issues ") + ", ".join(ids)


def redact_report(report: dict, catalog: dict | None = None) -> tuple[dict, list[str]]:
    """The copy of a report that is safe to publish, and any places where withheld text still shows."""
    names = {b["id"]: b["name"] for b in (catalog or load_catalog())["benchmarks"]}
    public = strip_private(copy.deepcopy(report))
    if "holdout" in public:
        public["holdout"]["private_details"] = "[redacted]"
    ids = sensitive_ids(report)
    secrets: list[tuple[str, str, bool]] = []
    findings = []
    for f in public.get("findings", []):
        if f.get("id") not in ids:
            findings.append(f)
            continue
        secrets += [(f["id"], t, q) for t, q in _withheld_text(f)]
        files = [repo_relative(ev["file"]) for ev in f.get("evidence", []) if ev.get("type") == "code" and ev.get("file")]
        paths = list(dict.fromkeys(list(f.get("paths", []) or []) + files))
        swap = {"title": f"{names.get(f.get('benchmark_id'), f.get('benchmark_id'))} issue (details withheld)",
                "evidence": [{"type": "withheld", "note": WITHHELD_NOTE}], "sensitive": True}
        if paths:
            swap["paths"] = paths
        g = {k: swap.get(k, v) for k, v in f.items() if k in FINDING_KEEP or k in swap}
        g.update({k: v for k, v in swap.items() if k not in g})
        findings.append(g)
    if "findings" in public:
        public["findings"] = findings

    reworded: dict[str, dict] = {}
    for b in public.get("benchmarks", []):
        for act in b.get("path_to_target", []) or []:
            hit = ids.intersection(act.get("resolves", []) or [])
            if not hit:
                continue
            for key in ("action", "decision_question"):
                if isinstance(act.get(key), str):
                    secrets.append((f"action {act.get('id')}", norm(act[key]), False))
            act["action"] = f"Fix withheld {_ids_text(hit)}. The private copy has the details."
            if act.get("decision_question"):
                act["decision_question"] = f"Approve the planned fix for withheld {_ids_text(hit)}? The private copy has the details."
            reworded[act.get("id")] = {"action": act["action"], "decision_question": act.get("decision_question"),
                                       "why_first": f"Fixes withheld {_ids_text(hit)}."}

    def patch(obj):
        if isinstance(obj, dict):
            new = reworded.get(obj.get("action_id")) if isinstance(obj.get("action_id"), str) else None
            for k, v in obj.items():
                obj[k] = new[k] if new and k in new and k in ("action", "decision_question", "why_first") else patch(v)
            return obj
        if isinstance(obj, list):
            return [patch(v) for v in obj]
        return obj
    for key in ("top_priorities", "rollup"):
        if public.get(key):
            public[key] = patch(public[key])
    public["publishing"] = {"redacted": True, "withheld": sorted(ids)}

    leaks: list[str] = []
    if secrets:
        places = [(f"benchmark {b.get('id')}", b) for b in public.get("benchmarks", [])]
        places += [(f"finding {f.get('id')}", f) for f in public.get("findings", []) if f.get("id") not in ids]
        places += [(k, v) for k, v in public.items() if k not in ("benchmarks", "findings")]
        texts = [(where, norm(all_text(v)), norm(all_text(_without_quotes(v)))) for where, v in places]
        for owner, secret, quoted in dict.fromkeys(secrets):
            for where, text, prose in texts:
                if secret in (prose if quoted else text):
                    leaks.append(f"{owner}: withheld text still appears in {where}: \"{secret[:60]}{'…' if len(secret) > 60 else ''}\"")
    return public, leaks


def publish_problems(report: dict, require_redacted: bool = True) -> list[str]:
    """Reasons a report is not yet safe to commit to a public grading repo."""
    errors = []
    if require_redacted and not (report.get("publishing") or {}).get("redacted"):
        errors.append("not redacted: run `gradekit redact --in-place` on it first")
    for f in report.get("findings", []):
        if f.get("sensitive") is True and any(ev.get("type") != "withheld" for ev in f.get("evidence", [])):
            errors.append(f"finding {f.get('id')} is sensitive but still carries its evidence")
    private = (report.get("holdout") or {}).get("private_details")
    if isinstance(private, list) and private:
        errors.append("holdout.private_details still lists hidden-check results")
    rest = copy.deepcopy(report)
    (rest.get("holdout") or {}).pop("private_details", None)
    if strip_private(rest) != rest:
        errors.append("report still has private_* fields")
    return errors


def private_path(path: str) -> str:
    return re.sub(r"\.json$", "", path) + ".private.json"


def same_but_marked(public: dict, report: dict) -> bool:
    """True when redact withheld and stripped nothing: the public copy only says it was redacted."""
    pub = {k: v for k, v in public.items() if k != "publishing"}
    if "holdout" in pub and not (report.get("holdout") or {}).get("private_details"):
        pub["holdout"] = {**pub["holdout"], "private_details": report["holdout"].get("private_details")}
    return pub == report


def cmd_redact(args) -> int:
    report = load_report(args.report)
    if (report.get("publishing") or {}).get("redacted"):
        if not (report["publishing"].get("withheld") or []) and not Path(private_path(args.report)).exists():
            emit(args, {"leaks": [], "withheld": [], "written": {}}, f"{args.report} is already redacted, and withholds nothing: nothing to do")
            return 0
        die(f"{args.report} is already redacted" + (f"; the full report is {private_path(args.report)}" if args.in_place else ""))
    public, leaks = redact_report(report)
    if leaks:
        for leak in leaks:
            print(f"LEAK: {leak}")
        print("\nnothing written. Reword those places generically (or name only the finding ID) and run redact again.")
        args._result = {"leaks": leaks, "written": []}
        return 1
    withheld = public["publishing"]["withheld"]
    if args.in_place and same_but_marked(public, report):
        write_json(args.report, public)   # nothing withheld or stripped: no private copy to keep or hand over
        written = {"public": args.report}
        print(f"nothing to withhold: marked {args.report} redacted, and no {Path(private_path(args.report)).name} is needed")
    elif args.in_place:
        priv = private_path(args.report)
        write_json(priv, report)
        write_json(args.report, public)
        written = {"public": args.report, "private": priv}
        print(f"wrote the full report to {priv}\nwrote the public report to {args.report}")
        print(f"keep {Path(priv).name} out of the repo (grading repos ignore *.private.json); hand it to whoever fixes the code.")
    else:
        out = args.out or re.sub(r"\.json$", "", args.report) + ".shared.json"
        write_json(out, public)
        print(f"wrote redacted report to {out}")
        written = {"public": out}
    args._result = {"leaks": [], "withheld": withheld, "written": written}
    print(f"withheld {len(withheld)} sensitive finding(s)" + (f": {', '.join(withheld)}" if withheld else ""))
    return 0


def repo_rollup(paths: list, weights: dict | None = None) -> dict:
    """The repo-wide result of a monorepo's reports: overall weighted by component weight, maturity the lowest. With
    `weights` (the config's), each component's weight comes from there, never from its report."""
    rows = []
    for path in paths:
        r = load_report(path)
        roll = r.get("rollup")
        if not roll:
            die(f"{path} has no rollup; run `gradekit report check --write` (or `rollup --write`) on it first")
        comp = r.get("component") or {}
        if comp.get("name") == "repo":
            continue
        name = comp.get("name") or Path(path).stem
        if weights is not None and name not in weights:
            die(f"{path} is component '{name}', which project.toml doesn't define ([[components]]: {', '.join(weights) or 'none'})")
        weight = weights[name] if weights is not None else comp.get("weight", 1) or 1
        rows.append({"component": name, "weight": weight,
                     "preset": (r.get("config") or {}).get("preset"), "overall": roll["overall_score"],
                     "level": roll["maturity"]["current_level"], "failed_gates": [g["benchmark_id"] for g in roll["gates"] if g["status"] == "failed"]})
    if not rows:
        die("no component reports (components/NAME.json) to combine")
    scored = [(x["overall"], x["weight"]) for x in rows if x["overall"] is not None]
    tw = sum(w for _, w in scored)
    overall = weighted(scored) if tw else None
    lowest = min(rows, key=lambda x: level_num(x["level"]))
    return {"computed_by": "gradekit.py rollup-repo", "overall_score": overall, "maturity": lowest["level"],
            "limited_by": lowest["component"], "components": rows}


def cmd_rollup_repo(args) -> int:
    if len(args.reports) == 1 and Path(args.reports[0]).is_dir():
        folder = Path(args.reports[0])
        if not (folder / "components").is_dir():
            die(f"{folder} has no components/ folder")
        pdir = project_dir_for_report(folder / "report.json")
        weights = (load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), load_json(folder / "report.json"),
                               quiet=True)["components"] if pdir else None)
        summary = repo_rollup(folder_reports(folder)[1:], weights or None)
        if args.write:
            main_path = folder / "report.json"
            r = load_report(main_path)
            r["repo_rollup"] = summary
            write_json(main_path, r)
            print(f"stored the repo-wide result in {main_path} (repo_rollup)")
        for x in summary["components"]:
            print(f"{x['component']:<20} {x['weight']:>6} {str(x['overall']):>7} {x['level']}")
        print(f"\nrepo overall (component-weighted): {summary['overall_score']}; maturity (lowest component): {summary['maturity']}")
        args._result = {**summary, "written": str(folder / "report.json") if args.write else None}
        return 0
    rows = []
    for path in args.reports:
        r = load_report(path)
        roll = r.get("rollup")
        if not roll:
            die(f"{path} has no rollup; run `gradekit rollup --write` on it first (with its component's config)")
        comp = r.get("component") or {}
        rows.append({"component": comp.get("name") or Path(path).stem, "weight": comp.get("weight", 1),
                     "preset": (r.get("config") or {}).get("preset"), "overall": roll["overall_score"],
                     "level": roll["maturity"]["current_level"], "failed_gates": [g["benchmark_id"] for g in roll["gates"] if g["status"] == "failed"]})
    scored = [(x["overall"], x["weight"]) for x in rows if x["overall"] is not None]
    tw = sum(w for _, w in scored)
    overall = weighted(scored) if tw else None
    lowest = min(rows, key=lambda x: level_num(x["level"]))
    print(f"{'component':<20} {'preset':<14} {'weight':>6} {'overall':>7} level")
    for x in rows:
        fg = f"  failed gates: {', '.join(x['failed_gates'])}" if x["failed_gates"] else ""
        print(f"{x['component']:<20} {str(x['preset']):<14} {x['weight']:>6} {str(x['overall']):>7} {x['level']}{fg}")
    print(f"\nrepo overall (component-weighted): {overall}")
    print(f"repo maturity (lowest component): {lowest['level']}  ← limited by '{lowest['component']}'")
    summary = {"computed_by": "gradekit.py rollup-repo", "overall_score": overall,
               "maturity": lowest["level"], "limited_by": lowest["component"], "components": rows}
    if args.out:
        write_json(args.out, summary)
        print(f"wrote {args.out}")
    args._result = {**summary, "written": args.out}
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_redact(sub):
    p = sub.add_parser("redact", help="make a copy safe to publish: no hidden-check details, sensitive findings withheld")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--out", help="where to write the public copy (default: REPORT.shared.json)")
    g.add_argument("--in-place", action="store_true",
                   help="for grading repos: move the full report to REPORT.private.json and write the public one in its place")
    p.set_defaults(fn=cmd_redact)


def add_rollup_repo(sub):
    p = sub.add_parser("rollup-repo", help="combine per-component reports (each must already have a rollup)")
    p.add_argument("reports", nargs="+", help="the component reports, or one report folder (with components/)")
    p.add_argument("--out")
    p.add_argument("--write", action="store_true", help="with a folder: store the result in its report.json as repo_rollup")
    p.set_defaults(fn=cmd_rollup_repo)
