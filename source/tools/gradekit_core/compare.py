"""Comparing and combining reports: stability, diff, calibrate, redact, rollup-repo."""
from __future__ import annotations

import argparse
import copy
import statistics

from .common import (
    benchmarks_by_id, die, expected_weight, level_num, load_catalog, load_json, load_report, major, OPEN_STATUSES,
    scoring_version_of, write_json,
)
from .config import load_config
from .records import disposition_entry
from .rollup import apply_rollup, compute_rollup


def compute_consensus(runs: list[dict], cfg: dict) -> dict:
    if len(runs) < 2:
        die("need at least two runs")
    notes = []
    commits = {r.get("run", {}).get("commit") for r in runs}
    if len(commits) > 1:
        notes.append(f"runs graded different commits: {sorted(map(str, commits))}")
    hashes = {(r.get("config") or {}).get("hash") for r in runs}
    if len(hashes) > 1:
        notes.append(f"runs used different configs: {sorted(map(str, hashes))}")
    ids = [b["id"] for b in load_catalog()["benchmarks"]]
    medians, unstable, rows = {}, [], []
    for bid in ids:
        entries = [benchmarks_by_id(r).get(bid, {}) for r in runs]
        apps = [e.get("applicability", "not_applicable") for e in entries]
        scores = [e.get("score") for e in entries]
        majority_na = apps.count("not_applicable") > len(runs) / 2
        nums = [x for x in scores if isinstance(x, int)]
        med = None if majority_na or not nums else statistics.median_low(nums)
        spread = (max(nums) - min(nums)) if nums else 0
        split = len(set(apps)) > 1
        flag = spread > 1 or split
        if flag:
            unstable.append(bid)
        applicable = [a for a in apps if a != "not_applicable"]
        maj_app = "not_applicable" if majority_na else statistics.mode(applicable)
        medians[bid] = {"median": med, "applicability": maj_app, "scores": scores,
                        "applicability_votes": apps, "spread": spread, "unstable": flag}
        rows.append({"id": bid, "scores": scores, "median": med, "spread": spread, "unstable": flag, "split": split})

    def distance(r):
        bb = benchmarks_by_id(r)
        return sum(abs(bb.get(b, {}).get("score") - m["median"]) for b, m in medians.items()
                   if isinstance(bb.get(b, {}).get("score"), int) and m["median"] is not None)

    base_idx = min(range(len(runs)), key=lambda i: distance(runs[i]))
    consensus = copy.deepcopy(runs[base_idx])
    for b in consensus.get("benchmarks", []):
        m = medians.get(b.get("id"))
        if not m:
            continue
        if m["applicability"] == "not_applicable":
            b.update(applicability="not_applicable", score=None, confidence=None)
            b["applicability_reason"] = b.get("applicability_reason") or "majority of runs judged not applicable"
        else:
            if b.get("applicability") == "not_applicable":
                b["applicability"] = m["applicability"]
                b["applicability_reason"] = b.get("applicability_reason") or "consensus of other runs"
                b["confidence"] = "low"
            b["score"] = m["median"]
            b["config_weight"] = cfg["weights"][b["id"]]["weight"]
            b["weight"] = expected_weight(b["applicability"], b["config_weight"])
    overall_by_run = [compute_rollup(r, cfg)["overall_score"] for r in runs]
    consensus["stability"] = {"runs": len(runs), "base_run_index": base_idx + 1,
                              "method": "median_low of integer scores; majority vote on applicability",
                              "overall_by_run": overall_by_run, "unstable_benchmarks": unstable, "per_benchmark": medians}
    roll = apply_rollup(consensus, cfg)
    return {"report": consensus, "rows": rows, "unstable": unstable, "overall_by_run": overall_by_run,
            "notes": notes, "rollup": roll}


def cmd_stability(args) -> int:
    runs = [load_report(p) for p in args.reports]
    cfg = load_config(args, runs[0])
    res = compute_consensus(runs, cfg)
    for n in res["notes"]:
        print(f"warning: {n}")
    print(f"{'ID':<4} {'scores':<20} {'median':>6} {'spread':>6}")
    for r in res["rows"]:
        sc = ",".join("–" if x is None else str(x) for x in r["scores"])
        mark = ("  ← unstable" + (" (applicability split)" if r["split"] else "")) if r["unstable"] else ""
        print(f"{r['id']:<4} {sc:<20} {('–' if r['median'] is None else r['median']):>6} {r['spread']:>6}{mark}")
    roll = res["rollup"]
    print(f"\noverall by run: {res['overall_by_run']}  → consensus {roll['overall_score']} ({roll['maturity']['current_level']})")
    print(f"unstable benchmarks: {', '.join(res['unstable']) or 'none'}  (spread > 1 or applicability split: tighten their rubric wording)")
    if args.out:
        write_json(args.out, res["report"])
        print(f"wrote consensus report to {args.out}")
    args._result = {"rows": res["rows"], "unstable": res["unstable"], "overall_by_run": res["overall_by_run"], "notes": res["notes"],
                    "consensus_overall": roll["overall_score"], "consensus_level": roll["maturity"]["current_level"], "written": args.out}
    return 3 if (args.strict and res["unstable"]) else 0


# =========================================================================== diff

def compute_diff(old: dict, new: dict, cfg_old: dict, cfg_new: dict) -> dict:
    regressions, notes = [], []
    same_major = major(scoring_version_of(old)) == major(scoring_version_of(new))
    oh, nh = (old.get("config") or {}).get("hash"), (new.get("config") or {}).get("hash")
    if oh != nh:
        notes.append(f"reports used different configs ({oh} → {nh}); weights may differ, so overall and maturity "
                     "changes can come from re-weighting, not code changes")
    r_old, r_new = compute_rollup(old, cfg_old), compute_rollup(new, cfg_new)
    if not same_major:
        notes.append(f"scoring versions differ ({scoring_version_of(old)} → {scoring_version_of(new)}); score deltas are not "
                     "comparable and are not used for regressions")
    ob, nb = benchmarks_by_id(old), benchmarks_by_id(new)
    # A gate that stops being scored leaves the gate check, which lifts the overall cap: that's never an improvement.
    gates_unscored = {g["benchmark_id"] for g in r_new["gates"] if g["status"] == "not scored"} & \
                     {g["benchmark_id"] for g in r_old["gates"] if g["status"] in ("passed", "failed")}
    changes = []
    for bid in [b["id"] for b in load_catalog()["benchmarks"]]:
        so, sn = ob.get(bid, {}).get("score"), nb.get(bid, {}).get("score")
        if so != sn:
            changes.append({"id": bid, "old": so, "new": sn})
            if same_major and isinstance(so, int) and isinstance(sn, int) and sn < so:
                regressions.append(f"{bid} dropped {so} → {sn}")
            if same_major and isinstance(so, int) and sn is None:
                if bid in gates_unscored:
                    regressions.append(f"gate {bid} is no longer scored (it was {so}): a gate can't be not_applicable")
                else:
                    notes.append(f"{bid} went from {so} to N/A; check the applicability reason")
        go = set(ob.get(bid, {}).get("gaming_flags", []) or [])
        for gflag in sorted(set(nb.get(bid, {}).get("gaming_flags", []) or []) - go):
            regressions.append(f"{bid} new gaming flag: {gflag}")
    lo, ln = r_old["maturity"]["current_level"], r_new["maturity"]["current_level"]
    if level_num(ln) < level_num(lo):
        regressions.append(f"maturity dropped {lo} → {ln}")
    newly_failed = {g["benchmark_id"] for g in r_new["gates"] if g["status"] == "failed"} - \
                   {g["benchmark_id"] for g in r_old["gates"] if g["status"] == "failed"}
    for bid in sorted(newly_failed):
        regressions.append(f"gate {bid} newly failed")
    of = {f["id"]: f for f in old.get("findings", [])}
    nf = {f["id"]: f for f in new.get("findings", [])}
    nz = r_new["finding_zones"]

    def brief(i):
        return {"id": i, "title": nf[i].get("title"), "severity": nf[i].get("severity"),
                "effective_severity": nz.get(i, {}).get("effective_severity", nf[i].get("severity")),
                "zone": nz.get(i, {}).get("criticality", "normal")}
    # New means not in the baseline. A finding carried over unchanged keeps whatever status it had
    # (PR checks copy untouched findings as-is), so status "new" alone doesn't make it new.
    new_ids = [brief(i) for i in nf if i not in of]
    fixed = [brief(i) for i, f in nf.items() if f.get("status") == "fixed" and of.get(i, {}).get("status") != "fixed"]
    regressed = [brief(i) for i, f in nf.items() if f.get("status") == "regressed"]
    # Accepting a finding stops it counting (the open-critical limit, caps, maturity), so who accepted it matters.
    accepted = [brief(i) for i, f in nf.items() if f.get("status") == "accepted" and of.get(i, {}).get("status") != "accepted"]
    for f in accepted:
        entry = disposition_entry(nf[f["id"]], cfg_new)
        f["decided_by"] = entry[1].get("decided_by") if entry else None
        if entry:
            notes.append(f"accepted by people: {f['id']} ({entry[1].get('decided_by') or 'dispositions.json'}): {f['title']}")
        else:
            regressions.append(f"finding {f['id']} was accepted without an entry in dispositions.json (only people accept findings): {f['title']}")
    # A problem first seen at the baseline's commit (or a PR's base commit) existed before this change:
    # report it, but don't count it against the change.
    before = [c for c in (old.get("run", {}).get("commit"), new.get("run", {}).get("base_commit")) if c]

    def pre_existing(i):
        if nf[i].get("status") == "noticed":   # format 5 says so directly
            return True
        seen = str(nf[i].get("first_seen_commit") or "")
        return bool(seen) and any(seen.startswith(c) or c.startswith(seen) for c in before)

    for f in new_ids:
        f["pre_existing"] = pre_existing(f["id"])
        if f["pre_existing"]:
            notes.append(f"pre-existing problem first recorded now (not caused by this change): {f['id']} "
                         f"({f['effective_severity']}, {f['zone']} zone): {f['title']}")
        elif f["effective_severity"] in ("critical", "major"):
            regressions.append(f"new {f['effective_severity']} finding {f['id']} ({f['zone']} zone): {f['title']}")
    for f in regressed:
        regressions.append(f"finding regressed {f['id']}: {f['title']}")
    for i, f in nf.items():
        if f.get("status") == "withdrawn" and of.get(i, {}).get("status") != "withdrawn":
            notes.append(f"withdrawn after a dispute: {i} ({(f.get('dispute') or {}).get('note') or 'no note'})")
    for i, f in of.items():
        if i not in nf and f.get("status") in OPEN_STATUSES:
            notes.append(f"open finding {i} disappeared without a 'fixed' status (finding IDs must be stable)")
    if new.get("integrity_flags"):
        regressions.append(f"{len(new['integrity_flags'])} integrity flag(s) in the new report")
    ho, hn = old.get("holdout", {}) or {}, new.get("holdout", {}) or {}
    hold = None
    if ho.get("run") and hn.get("run") and ho.get("pass_rate") is not None and hn.get("pass_rate") is not None:
        hold = {"old": ho["pass_rate"], "new": hn["pass_rate"]}
        if hn["pass_rate"] < ho["pass_rate"]:
            regressions.append(f"hidden-check pass rate dropped {ho['pass_rate']:.0%} → {hn['pass_rate']:.0%}")
            if (r_new["overall_score"] or 0) - (r_old["overall_score"] or 0) >= 0.5:
                notes.append("DIVERGENCE: visible scores rose while hidden checks fell; suspect the code is being "
                             "tuned to the rubric. Review the changes by hand before trusting these scores.")
    return {"from_commit": old.get("run", {}).get("commit"), "to_commit": new.get("run", {}).get("commit"),
            "mode": new.get("mode"), "score_changes": changes,
            "overall": {"old": r_old["overall_score"], "new": r_new["overall_score"]},
            "maturity": {"old": lo, "new": ln},
            "findings": {"new": new_ids, "fixed": fixed, "regressed": regressed, "accepted": accepted},
            "holdout": hold, "regressions": regressions, "notes": notes,
            "verdict": "FAIL" if regressions else "PASS"}


def cmd_diff(args) -> int:
    old, new = load_report(args.old), load_report(args.new)
    cfg_new = load_config(args, new)
    if args.old_config:
        ns = argparse.Namespace(config=args.old_config, component=getattr(args, "component", None))
        cfg_old = load_config(ns, old, quiet=True)
    elif major(scoring_version_of(old)) != major(scoring_version_of(new)):
        cfg_old = load_config(args, old, quiet=True)   # each report under the rules it was graded with
    else:
        cfg_old = cfg_new
    d = compute_diff(old, new, cfg_old, cfg_new)
    print(f"{d['from_commit']} → {d['to_commit']}  (mode: {d['mode']})")
    print("\nScore changes:" if d["score_changes"] else "\nScore changes: none")
    for c in d["score_changes"]:
        print(f"  {c['id']}: {'–' if c['old'] is None else c['old']} → {'–' if c['new'] is None else c['new']}")
    print(f"Overall: {d['overall']['old']} → {d['overall']['new']}   Maturity: {d['maturity']['old']} → {d['maturity']['new']}")
    fs = d["findings"]
    print(f"\nFindings: {len(fs['new'])} new, {len(fs['fixed'])} fixed, {len(fs['regressed'])} regressed"
          + (f", {len(fs['accepted'])} accepted" if fs["accepted"] else ""))
    for f in fs["new"]:
        print(f"  new       {f['id']} [{f['effective_severity']}, {f['zone']}] {f['title']}")
    for f in fs["fixed"]:
        print(f"  fixed     {f['id']} {f['title']}")
    for f in fs["regressed"]:
        print(f"  regressed {f['id']} {f['title']}")
    for f in fs["accepted"]:
        print(f"  accepted  {f['id']} {f['title']} ({'by ' + f['decided_by'] if f['decided_by'] else 'no entry in dispositions.json'})")
    if d["holdout"]:
        print(f"Hidden checks: {d['holdout']['old']:.0%} → {d['holdout']['new']:.0%}")
    for n in d["notes"]:
        print(f"note: {n}")
    if d["regressions"]:
        print("\nREGRESSIONS:")
        for r in d["regressions"]:
            print(f"  - {r}")
    print(f"\nverdict: {d['verdict']}")
    args._result = d
    return 2 if (args.fail_on_regression and d["regressions"]) else 0


# =========================================================================== calibrate / redact / rollup-repo

def cmd_calibrate(args) -> int:
    report, exp = load_report(args.report), load_json(args.expected)
    crit = {"within_tolerance_pct": 90, "mae_max": 0.75, **exp.get("criteria", {})}
    bb = benchmarks_by_id(report)
    total = within = 0
    errs, mism, deltas = [], [], []
    print(f"{'ID':<4} {'expected':>8} {'actual':>6} {'Δ':>4}")
    for bid, e in sorted(exp.get("expected", {}).items()):
        b = bb.get(bid, {})
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
        print(f"{bid:<4} {e['score']:>8} {actual:>6} {d:>+4}" + ("" if abs(d) <= tol else "  ← outside tolerance"))
    if not total:
        die("no comparable benchmarks")
    pct, mae, bias = 100 * within / total, sum(errs) / total, sum(deltas) / total
    for m in mism:
        print(f"applicability mismatch: {m}")
    ok = pct >= crit["within_tolerance_pct"] and mae <= crit["mae_max"] and not mism
    print(f"\nwithin tolerance: {pct:.0f}% (need ≥ {crit['within_tolerance_pct']}%)  MAE: {mae:.2f} (need ≤ {crit['mae_max']})  "
          f"bias: {bias:+.2f} ({'grader runs generous' if bias > 0.25 else 'grader runs harsh' if bias < -0.25 else 'no clear bias'})")
    print("calibration: PASS" if ok else "calibration: FAIL")
    args._result = {"pass": ok, "within_tolerance_pct": round(pct, 1), "mae": round(mae, 3), "bias": round(bias, 3),
                    "compared": total, "applicability_mismatches": mism, "criteria": crit}
    return 0 if ok else 4
