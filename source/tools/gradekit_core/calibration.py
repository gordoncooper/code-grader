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


def scoring_fingerprint() -> str:
    """What calibration measures: the scoring version, every benchmark's rubric (measures, boundaries, anchors,
    caps) and the computed limits. A change to any of them needs calibration to be run again."""
    rub = parse_rubric()
    body = {"scoring_version": load_toml(DEFAULTS_PATH).get("suite_version"),
            "benchmarks": [{k: b.get(k) for k in ("id", "measures", "not_this", "assess", "anchors", "caps")} for b in rub["benchmarks"]],
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
            "session": run.get("session"), "note": args.note, "rules_fingerprint": scoring_fingerprint(), "scores": run_scores(report)}
    out = runs / f"run-{n}.json"
    write_json(out, {k: v for k, v in data.items() if v is not None})
    emit(args, {"written": str(out)}, f"wrote {out}; then `gradekit calibration run` to update the results")
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
