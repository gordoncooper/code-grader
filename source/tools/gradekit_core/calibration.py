"""The calibration program: golden repos, independent runs and drift."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .common import (
    DEFAULTS_PATH, die, emit, load_json, load_report, load_toml, scoring_version_of, SUITE_DIR, write_json,
)
from .rollup import AUTO_CAPS, CAP_SEVERITIES, CRITICAL_MAX, NO_ENFORCEMENT_MAX, NO_STRENGTH_MAX
from .rubric import parse_rubric


# Golden repos, frozen at a commit, with expected scores a person set; several independent grader runs each.
# `gradekit calibration run` scores every run against its golden's expected scores, measures the spread across
# runs, and writes calibration/results.json and RESULTS.md. The results carry a fingerprint of the scoring rules,
# and a kit test fails when the rules change without the results being regenerated: no scoring change ships
# unmeasured.

GOLDEN_DIR = SUITE_DIR / "calibration" / "golden"
CANDIDATE_DIR = SUITE_DIR / "calibration" / "candidates"   # golden repos still waiting for a review and their runs
CALIBRATION_RESULTS = SUITE_DIR / "calibration" / "results.json"
CALIBRATION_MD = SUITE_DIR / "calibration" / "RESULTS.md"


def calibrate_scores(scores: dict, exp: dict) -> dict:
    """One run's {benchmark: {score, applicability}} against a golden's expected scores."""
    crit = {"within_tolerance_pct": 90, "mae_max": 0.75, **exp.get("criteria", {})}
    total = within = 0
    errs, mism, deltas, rows = [], [], [], []
    for bid, e in sorted(exp.get("expected", {}).items()):
        b = scores.get(bid) or {}
        actual = b.get("score")
        if e.get("applicability") and e["applicability"] != b.get("applicability"):
            mism.append(f"{bid}: expected {e['applicability']}, got {b.get('applicability')}")
        if e.get("score") is None or actual is None:
            continue
        tol = e.get("tolerance", 1)
        d = actual - e["score"]
        total += 1
        within += abs(d) <= tol
        errs.append(abs(d))
        deltas.append(d)
        rows.append({"benchmark": bid, "expected": e["score"], "actual": actual, "delta": d, "within": abs(d) <= tol})
    if not total:
        die("no comparable benchmarks")
    pct, mae, bias = 100 * within / total, sum(errs) / total, sum(deltas) / total
    ok = pct >= crit["within_tolerance_pct"] and mae <= crit["mae_max"] and not mism
    return {"pass": ok, "within_tolerance_pct": round(pct, 1), "mae": round(mae, 3), "bias": round(bias, 3), "compared": total,
            "applicability_mismatches": mism, "criteria": crit, "rows": rows}


def run_scores(report: dict) -> dict:
    return {b["id"]: {"score": b.get("score"), "applicability": b.get("applicability")} for b in report.get("benchmarks", [])}


def run_findings(report: dict) -> list[dict]:
    """What `calibration analyze` compares across runs: each finding's benchmark, severity and the code it cites."""
    out = []
    for f in report.get("findings", []):
        if f.get("status") == "withdrawn":
            continue
        places = [f"{e['file']}:{e['lines']}" if e.get("lines") else e["file"]
                  for e in f.get("evidence", []) if e.get("type") == "code" and e.get("file")]
        out.append({"benchmark": f.get("benchmark_id"), "severity": f.get("severity"), "title": f.get("title"), "places": places})
    return out


def scoring_fingerprint() -> str:
    """What calibration measures: the scoring version, every benchmark's rubric (measures, boundaries, anchors,
    caps) and the computed limits. A change to any of them needs calibration to be run again."""
    rub = parse_rubric()
    body = {"scoring_version": load_toml(DEFAULTS_PATH).get("suite_version"),
            "benchmarks": [{**{k: b.get(k) for k in ("id", "measures", "not_this", "assess", "anchors")},
                            "caps": None if b.get("caps") is None else [{k: c[k] for k in ("id", "when", "max")} for c in b["caps"]]}
                           for b in rub["benchmarks"]],
            "limits": [CRITICAL_MAX, NO_STRENGTH_MAX, NO_ENFORCEMENT_MAX, sorted(AUTO_CAPS), list(CAP_SEVERITIES)]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def calibration_results(golden_dir: Path, min_runs: int = 3) -> dict:
    goldens = []
    rules = scoring_fingerprint()
    for d in sorted(p for p in golden_dir.iterdir() if (p / "expected.json").exists()) if golden_dir.is_dir() else []:
        exp = load_json(d / "expected.json")
        runs, earlier, counted = [], [], []
        for f in sorted((d / "runs").glob("*.json"), key=lambda p: (len(p.name), p.name)) if (d / "runs").is_dir() else []:
            run = load_json(f)
            if run.get("rules_fingerprint") != rules:   # graded under other scoring rules: listed, not counted
                earlier.append({"run": f.stem, "graded": run.get("graded"), "rules_fingerprint": run.get("rules_fingerprint")})
                continue
            counted.append(run)
            res = calibrate_scores(run.get("scores") or {}, exp)
            runs.append({"run": f.stem, "model": run.get("model"), "graded": run.get("graded"),
                         **{k: res[k] for k in ("pass", "within_tolerance_pct", "mae", "bias", "applicability_mismatches")}})
        max_spread = exp.get("criteria", {}).get("max_spread", 1)
        spread, unstable = {}, []
        for bid in sorted(exp.get("expected", {})):
            vals = [((run.get("scores") or {}).get(bid) or {}).get("score") for run in counted]
            vals = [v for v in vals if isinstance(v, int)]
            if len(vals) >= 2:
                spread[bid] = max(vals) - min(vals)
                if spread[bid] > max_spread:
                    unstable.append(bid)
        enough = len(runs) >= min_runs
        goldens.append({"name": d.name, "reference": exp.get("reference"), "set_by": exp.get("set_by"), "runs": runs, "earlier_runs": earlier,
                        "runs_needed": min_runs, "max_spread": max_spread,
                        "spread": {"largest": max(spread.values()) if spread else None,
                                   "mean": round(sum(spread.values()) / len(spread), 2) if spread else None, "unstable": unstable},
                        "pass": enough and bool(runs) and all(r["pass"] for r in runs) and not unstable,
                        "status": "pass" if enough and all(r["pass"] for r in runs) and not unstable
                                  else ("needs more runs" if not enough else "fail")})
    return {"_about": "Written by `gradekit calibration run`. Don't edit: a kit test checks it matches the golden runs and the "
                      "current scoring rules.", "scoring_version": load_toml(DEFAULTS_PATH).get("suite_version"),
            "scoring_fingerprint": scoring_fingerprint(), "min_runs": min_runs,
            "pass": bool(goldens) and all(g["pass"] for g in goldens), "goldens": goldens}


def calibration_markdown(res: dict) -> str:
    out = ["# Calibration results", "",
           f"Generated by `gradekit calibration run` (scoring version {res['scoring_version']}, "
           f"rules fingerprint `{res['scoring_fingerprint']}`). Don't edit.", "",
           f"**Overall: {'PASS' if res['pass'] else 'not passed yet'}.** Each golden repo needs at least {res['min_runs']} independent runs; "
           "every run must be within tolerance of the expected scores, and no benchmark may spread more than its golden allows across runs. "
           "Only runs graded under the current scoring rules count (`add-run` records the rules' fingerprint).", ""]
    for g in res["goldens"]:
        out += [f"## {g['name']}: {g['status']}", "", f"{g['reference'] or ''}" + (f". Expected scores set by {g['set_by']}." if g.get("set_by") else ""), "",
                "| Run | Model | Within tolerance | MAE | Bias | Result |", "|---|---|:-:|:-:|:-:|---|"]
        out += [f"| {r['run']} | {r['model'] or '?'} | {r['within_tolerance_pct']:g}% | {r['mae']:g} | {r['bias']:+g} | "
                f"{'pass' if r['pass'] else 'fail'}{' (' + '; '.join(r['applicability_mismatches']) + ')' if r['applicability_mismatches'] else ''} |"
                for r in g["runs"]] or ["| none yet | | | | | |"]
        sp = g["spread"]
        out += ["", f"Runs: {len(g['runs'])} of {g['runs_needed']}. Spread across runs: "
                + (f"largest {sp['largest']}, mean {sp['mean']}" if sp["largest"] is not None else "needs at least two runs")
                + (f"; above {g['max_spread']} on {', '.join(sp['unstable'])}" if sp["unstable"] else "") + ".", ""]
        if g.get("earlier_runs"):
            out += [f"Not counted, because they were graded under earlier scoring rules: {', '.join(r['run'] for r in g['earlier_runs'])}.", ""]
    if not res["goldens"]:
        out += ["No golden repos yet: see README.md.", ""]
    return "\n".join(out)


def cmd_calibration_add_run(args) -> int:
    golden = Path(args.golden)
    exp = load_json(golden / "expected.json")
    report = load_report(args.report)
    commit, want = str((report.get("run") or {}).get("commit") or ""), str(exp.get("commit") or "")
    if want and not (commit.startswith(want) or want.startswith(commit)):
        die(f"{args.report} grades {commit[:7]}, but this golden repo is frozen at {want[:7]}")
    runs = golden / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(m.group(1)) for f in runs.glob("run-*.json") if (m := re.fullmatch(r"run-(\d+)\.json", f.name))] or [0])
    run = report.get("run") or {}
    data = {"graded": run.get("date"), "commit": commit, "suite_version": report.get("suite_version"),
            "scoring_version": scoring_version_of(report), "grader": run.get("grader"), "model": run.get("model"),
            "session": run.get("session"), "note": args.note, "rules_fingerprint": scoring_fingerprint(),
            "minutes": (run.get("usage") or {}).get("minutes"), "scores": run_scores(report), "findings": run_findings(report)}
    out = runs / f"run-{n}.json"
    write_json(out, {k: v for k, v in data.items() if v is not None})
    emit(args, {"written": str(out)}, f"wrote {out}; then `gradekit calibration run` to update the results")
    return 0


def counted_runs(golden_dir: Path, all_rules: bool = False) -> dict:
    """Each golden repo's runs graded under the current scoring rules (or every run, with all_rules)."""
    rules, out = scoring_fingerprint(), {}
    for d in sorted(p for p in golden_dir.iterdir() if (p / "expected.json").exists()) if golden_dir.is_dir() else []:
        runs = [load_json(f) for f in sorted((d / "runs").glob("*.json"), key=lambda p: (len(p.name), p.name))] if (d / "runs").is_dir() else []
        out[d.name] = [r for r in runs if all_rules or r.get("rules_fingerprint") == rules]
    return out


def _place(text: str) -> tuple[str, int, int] | None:
    """file:12-20 → (file, 12, 20); a place without lines can't be compared precisely."""
    m = re.fullmatch(r"(.+?):(\d+)(?:[-–](\d+))?", text)
    return (m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))) if m else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx, sy = sum((x - mx) ** 2 for x in xs) ** 0.5, sum((y - my) ** 2 for y in ys) ** 0.5
    return None if not sx or not sy else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def calibration_analysis(golden_dir: Path | list[Path], all_rules: bool = False) -> dict:
    """What the runs say about the rubric's shape: where graders disagree (spread), which benchmarks rarely apply,
    which ones move together across repos once each repo's overall level is taken out, and the same code filed
    under different benchmarks by different graders."""
    goldens: dict = {}
    for d in (golden_dir if isinstance(golden_dir, list) else [golden_dir]):   # golden repos, then candidates
        goldens.update(counted_runs(Path(d), all_rules))
    ids = list(dict.fromkeys(bid for runs in goldens.values() for r in runs for bid in (r.get("scores") or {})))
    spread, not_full, means = {}, {}, {}
    for name, runs in goldens.items():
        for bid in ids:
            vals = [((r.get("scores") or {}).get(bid) or {}).get("score") for r in runs]
            vals = [v for v in vals if isinstance(v, int)]
            if len(vals) >= 2:
                spread.setdefault(bid, {})[name] = max(vals) - min(vals)
            if vals:
                means.setdefault(name, {})[bid] = sum(vals) / len(vals)
            apps = [((r.get("scores") or {}).get(bid) or {}).get("applicability") for r in runs]
            not_full.setdefault(bid, []).extend(a != "full" for a in apps if a)
    spread_rows = sorted(({"benchmark": b, "largest": max(s.values()), "mean": round(sum(s.values()) / len(s), 2),
                           "by_golden": s} for b, s in spread.items()), key=lambda r: (-r["largest"], -r["mean"], r["benchmark"]))
    rarely = sorted(({"benchmark": b, "not_full_pct": round(100 * sum(v) / len(v)), "runs": len(v)}
                     for b, v in not_full.items() if v and sum(v) / len(v) >= 0.8), key=lambda r: (-r["not_full_pct"], r["benchmark"]))
    centred = {g: {b: v - sum(m.values()) / len(m) for b, v in m.items()} for g, m in means.items() if m}
    together = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            both = [g for g in centred if a in centred[g] and b in centred[g]]
            if len(both) >= 3:
                r = _pearson([centred[g][a] for g in both], [centred[g][b] for g in both])
                if r is not None and r >= 0.8:
                    together.append({"pair": [a, b], "r": round(r, 2), "goldens": len(both)})
    together.sort(key=lambda x: (-x["r"], x["pair"]))
    confusion = {}
    for name, runs in goldens.items():
        cited = [[(f["benchmark"], p) for f in r.get("findings") or [] for p in map(_place, f.get("places") or []) if p] for r in runs]
        for i in range(len(cited)):
            for j in range(i + 1, len(cited)):
                seen = set()
                for ba, pa in cited[i]:
                    for bb, pb in cited[j]:
                        if ba != bb and pa[0] == pb[0] and pa[1] <= pb[2] and pb[1] <= pa[2] and (ba, bb, pa) not in seen:
                            seen.add((ba, bb, pa))
                            key = tuple(sorted((ba, bb)))
                            confusion.setdefault(key, {"pair": list(key), "times": 0, "goldens": set()})
                            confusion[key]["times"] += 1
                            confusion[key]["goldens"].add(name)
    filed = sorted(({**c, "goldens": sorted(c["goldens"])} for c in confusion.values()), key=lambda c: (-c["times"], c["pair"]))
    return {"rules": "all" if all_rules else scoring_fingerprint(),
            "goldens": {g: len(r) for g, r in goldens.items()}, "spread": spread_rows, "rarely_full": rarely,
            "move_together": together, "filed_differently": filed}


def analysis_text(res: dict) -> str:
    if not any(res["goldens"].values()):
        return "no runs to analyze" + ("" if res["rules"] == "all" else " under the current scoring rules (`--all-rules` includes earlier ones)")
    out = ["Runs: " + ", ".join(f"{g} {n}" for g, n in res["goldens"].items()), "",
           "Spread across runs of the same repo (largest first; above 1 means graders disagree):"]
    out += [f"  {r['benchmark']}: largest {r['largest']}, mean {r['mean']}" for r in res["spread"][:12] if r["largest"] > 0] or ["  none"]
    out += ["", "Almost always limited or not_applicable (could be conditional, or go):"]
    out += [f"  {r['benchmark']}: {r['not_full_pct']}% of {r['runs']} runs" for r in res["rarely_full"]] or ["  none"]
    out += ["", "Move together across repos, after each repo's overall level is taken out (merge candidates; needs 3+ repos):"]
    out += [f"  {'/'.join(x['pair'])}: r {x['r']} over {x['goldens']} repos" for x in res["move_together"][:12]] or ["  none"]
    out += ["", "The same code filed under different benchmarks by different graders (unclear boundaries):"]
    out += [f"  {'/'.join(c['pair'])}: {c['times']} times ({', '.join(c['goldens'])})" for c in res["filed_differently"][:12]] or ["  none"]
    return "\n".join(out)


def cmd_calibration_analyze(args) -> int:
    res = calibration_analysis([Path(d) for d in args.golden_dir or [GOLDEN_DIR, CANDIDATE_DIR]], args.all_rules)
    emit(args, res, analysis_text(res))
    return 0


def cmd_calibration_run(args) -> int:
    res = calibration_results(Path(args.golden_dir), args.min_runs)
    text = json.dumps(res, indent=2, ensure_ascii=False) + "\n"
    md = calibration_markdown(res) + "\n"
    out, mdo = Path(args.out), Path(args.markdown)
    if args.check:
        stale = [str(p) for p, want in ((out, text), (mdo, md)) if not p.exists() or p.read_text(encoding="utf-8") != want]
        emit(args, {"up_to_date": not stale, "stale": stale, "results": res},
             "calibration results are up to date" if not stale else
             f"out of date: {', '.join(stale)}. The scoring rules or the golden runs changed: run `gradekit calibration run`")
        return 0 if not stale else 1
    out.write_text(text, encoding="utf-8")
    mdo.write_text(md, encoding="utf-8")
    lines = [f"{g['name']}: {g['status']} ({len(g['runs'])} of {g['runs_needed']} runs)" for g in res["goldens"]]
    emit(args, {"results": res, "written": [str(out), str(mdo)]},
         "\n".join(lines + [f"\ncalibration: {'PASS' if res['pass'] else 'not passed yet'}; wrote {out} and {mdo}"]))
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_calibration(sub):
    p = sub.add_parser("calibration", help="the calibration program: golden repos, repeated runs, published results")
    csub = p.add_subparsers(dest="calibration_cmd", required=True, metavar="STEP")
    q = csub.add_parser("add-run", help="save a grader's scores for a golden repo as runs/run-N.json")
    q.add_argument("golden", help="the golden repo's folder, e.g. calibration/golden/schedule")
    q.add_argument("report", help="the grader's report.json for the golden commit")
    q.add_argument("--note", help="e.g. which model or session, anything unusual")
    q.set_defaults(fn=cmd_calibration_add_run)
    q = csub.add_parser("run", help="score every run against its golden repo; write results.json and RESULTS.md")
    q.add_argument("--golden-dir", default=str(GOLDEN_DIR))
    q.add_argument("--min-runs", type=int, default=3, help="independent runs each golden repo needs (default 3)")
    q.add_argument("--out", default=str(CALIBRATION_RESULTS))
    q.add_argument("--markdown", default=str(CALIBRATION_MD))
    q.add_argument("--check", action="store_true", help="only check the written results are up to date (exit 1 if not)")
    q.set_defaults(fn=cmd_calibration_run)
    q = csub.add_parser("analyze", help="what the runs say about the rubric: spread, rarely applies, move together, filed differently")
    q.add_argument("--golden-dir", action="append",
                   help="a folder of golden repos (repeatable; default: calibration/golden and calibration/candidates)")
    q.add_argument("--all-rules", action="store_true", help="include runs graded under earlier scoring rules (benchmarks matched by ID)")
    q.set_defaults(fn=cmd_calibration_analyze)
