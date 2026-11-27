"""Limits and gates, the rollup, targets, maturity and ranked priorities."""
from __future__ import annotations

import re

from .common import (
    die, expected_weight, HEAT, level_num, load_report, norm, OPEN_STATUSES, PILLARS, refresh_fingerprint,
    REPO_LEVEL, RUBRIC, SEVERITIES, write_json,
)
from .config import load_config, with_config
from .zones import analyze_findings


def level_defs(cfg: dict) -> list[dict]:
    return cfg["maturity"].get("levels", [])


def compute_targets(report: dict, cfg: dict) -> dict:
    t = cfg["targets"]
    mode = t.get("mode", "proportional")
    overrides = t.get("overrides", {}) or {}
    gates = set(cfg["gates"]["benchmarks"])
    level_req = None
    if str(mode).startswith("level:"):
        lvl = mode.split(":", 1)[1]
        level_req = next((l for l in level_defs(cfg) if l["level"] == lvl), None)
        if level_req is None:
            die(f"targets.mode refers to unknown level '{lvl}'")
    out = {}
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if b.get("applicability") == "not_applicable" or b.get("score") is None:
            out[bid] = None
            continue
        if mode == "maximal":
            tv = 10
        elif level_req is not None:
            tv = level_req.get("gate_min", level_req.get("any_min", 1)) if bid in gates else level_req.get("any_min", 1)
        else:
            tv = int(t.get("by_weight", {}).get(str(b.get("weight", 1)), 8))
        if b.get("applicability") == "limited":
            tv = min(tv, int(t.get("limited_cap", 8)))
        if bid in overrides:
            tv = int(overrides[bid])
        out[bid] = tv
    return out


def weighted(items) -> float | None:
    """The weighted mean to one decimal, rounded half-up on the exact values: Python's round() rounds halves to even
    and works on floats, so 6.25 would become 6.2 and a mean of 7.95 could show 7.9. Maturity levels use this value,
    the one people see."""
    from decimal import ROUND_HALF_UP, Decimal
    pairs = [(Decimal(str(sc)), Decimal(str(w))) for sc, w in items]
    tw = sum((w for _, w in pairs), Decimal(0))
    if not tw:
        return None
    return float((sum((sc * w for sc, w in pairs), Decimal(0)) / tw).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------- score limits
# Each benchmark's highest allowed score, and why. In format-5 reports a score above it is an error.

CRITICAL_MAX, NO_STRENGTH_MAX, NO_ENFORCEMENT_MAX = 5, 8, 9
CAP_SEVERITIES = ("major", "critical")   # a rubric cap on a finding holds only while the finding is at least major
# Caps whose condition is in the report's own data, so they hold without a finding: the rubric's `automatic:` caps.
AUTO_CAPS = RUBRIC.automatic_caps


def catalog_caps(catalog: dict | None = None) -> dict:
    """{cap ID: {id, when, max, benchmark}} from the catalog (the rubric's "Caps:" lines)."""
    catalog = catalog or RUBRIC.catalog
    return {c["id"]: {**c, "benchmark": b["id"]} for b in catalog["benchmarks"] for c in b.get("caps", [])}


def resolve_cap(entry, benchmark: str, caps: dict) -> dict | None:
    """A caps_applied entry, by ID ("E1-cap-1"), by its rubric wording, or (4.x reports) as free text ending "max N"."""
    s = str(entry or "").strip()
    if s in caps:
        return caps[s]
    low = s.lower()
    for c in caps.values():
        if c["benchmark"] == benchmark and c["when"].lower() in low:
            return c
    m = re.search(r"max\s+(\d+)", s)
    return {"id": None, "when": s, "max": int(m.group(1)), "benchmark": benchmark} if m else None


def score_limits(report: dict, cfg: dict, fz: dict | None = None, catalog: dict | None = None) -> dict:
    """{benchmark: {"max": N, "why": [{kind, max, why}]}} for every benchmark held below 10."""
    caps = catalog_caps(catalog)
    fz = fz if fz is not None else analyze_findings(report, cfg)
    open_ = [f for f in report.get("findings", []) if f.get("status") in OPEN_STATUSES]
    critical_gaps = [g for g in report.get("gap_register", []) if g.get("status") in OPEN_STATUSES and g.get("severity") == "critical"]
    out = {}
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if b.get("applicability") == "not_applicable":
            continue
        why = []
        if not b.get("strengths"):
            why.append({"kind": "strengths", "max": NO_STRENGTH_MAX, "why": "no strengths (positive evidence)"})
        if not b.get("enforcement"):
            why.append({"kind": "enforcement", "max": NO_ENFORCEMENT_MAX, "why": "no enforcement evidence"})
        # A finding is the benchmark's if the benchmark lists it or the finding names the benchmark: dropping it from
        # finding_ids by hand mustn't lift the limit.
        mine = list(dict.fromkeys(list(b.get("finding_ids", [])) +
                                  [f.get("id") for f in report.get("findings", []) if f.get("benchmark_id") == bid]))
        crit = [fid for fid in mine if fz.get(fid, {}).get("effective_severity") == "critical"
                and fz.get(fid, {}).get("status") in OPEN_STATUSES]
        if crit:
            why.append({"kind": "critical", "max": CRITICAL_MAX, "why": f"open critical finding {', '.join(crit)}"})
        for entry in b.get("caps_applied", []) or []:
            c = resolve_cap(entry, bid, caps)
            if c:
                why.append({"kind": "cap", "max": c["max"], "why": (f"{c['id']}: " if c["id"] else "") + c["when"]})
        for f in open_:
            c = caps.get(f.get("cap") or "")
            sev = fz.get(f.get("id"), {}).get("effective_severity", f.get("severity"))
            if sev not in CAP_SEVERITIES:   # since scoring 5.0, a minor finding can't hold a hard cap
                continue
            if c and c["benchmark"] == bid:
                why.append({"kind": "cap", "max": c["max"], "why": f"{c['id']}: {c['when']} ({f.get('id')})"})
            elif not c and f.get("cap") and f.get("benchmark_id") == bid and resolve_cap(f["cap"], bid, caps):
                c2 = resolve_cap(f["cap"], bid, caps)
                why.append({"kind": "cap", "max": c2["max"], "why": (f"{c2['id']}: " if c2["id"] else "") + f"{c2['when']} ({f.get('id')})"})
        for cid, cond in AUTO_CAPS.items():
            c = caps.get(cid)
            if c and c["benchmark"] == bid and critical_gaps:
                why.append({"kind": "cap", "max": c["max"], "why": f"{cid}: {c['when']} ({', '.join(g.get('id', '?') for g in critical_gaps)})"})
        if why:
            seen, uniq = set(), []
            for w in why:
                if (w["kind"], w["why"]) not in seen:
                    seen.add((w["kind"], w["why"]))
                    uniq.append(w)
            out[bid] = {"max": min(w["max"] for w in uniq), "why": uniq}
    return out


def left_to_the_other_report(report: dict, bid: str, cfg: dict) -> bool:
    """In a monorepo split into components (grader Part 9), the repo report grades what the whole repository shares
    (REPO_LEVEL) and each component's report grades the rest; each leaves the other's benchmarks not_applicable. Only a
    project that defines [[components]] is split, so a report can't claim the split to leave a gate out."""
    comp = (report.get("component") or {}).get("name")
    parts = cfg.get("components") or []
    return bool(comp) and bool(parts) and (comp == "repo" or comp in parts) and (bid in REPO_LEVEL) != (comp == "repo")


def gate_not_applicable(bid: str, cfg: dict, report: dict | None = None) -> str | None:
    """Why a gate can't be not_applicable: it would drop out of the gate check, and with it the overall cap and every
    level's gate_min. Dropping a gate is a person's decision, made in the config, never a grader's. (A monorepo's
    split leaves a gate to the report that grades it: that's not dropping it.)"""
    if bid not in cfg["gates"]["benchmarks"] or (report is not None and left_to_the_other_report(report, bid, cfg)):
        return None
    why = ", ".join(cfg["gates"]["why"].get(bid, [])) or "the config"
    return (f"{bid} is a gate ({why}), so it can't be not_applicable: that would take it out of the gate check. If it truly "
            f"doesn't apply to this project, a person removes the gate in project.toml ([gates] exclude = [\"{bid}\"]); "
            "otherwise grade it, as limited if it applies only slightly")


def over_limit(b: dict, limit: dict | None) -> list[dict]:
    """The reasons a benchmark's score is too high: caps and open critical findings. (Strengths and enforcement
    are checked on their own, since a grader adds them after scoring.)"""
    if not limit or not isinstance(b.get("score"), int):
        return []
    return [w for w in limit["why"] if w["kind"] in ("cap", "critical") and b["score"] > w["max"]]


def compute_rollup(report: dict, cfg: dict) -> dict:
    weight_issues = []
    scored = []
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if bid in cfg["weights"]:
            want = expected_weight(b.get("applicability"), cfg["weights"][bid]["weight"])
            if b.get("applicability") != "not_applicable" and b.get("weight") != want:
                weight_issues.append(f"{bid}: weight {b.get('weight')} but the config gives {want}")
        if b.get("applicability") != "not_applicable" and isinstance(b.get("score"), int) and b.get("weight", 0) > 0:
            scored.append(b)
    by_id = {b["id"]: b for b in scored}

    pillar_scores = {p: weighted([(b["score"], b["weight"]) for b in scored if b.get("pillar") == p]) for p in PILLARS}
    overall_raw = weighted([(b["score"], b["weight"]) for b in scored])

    g = cfg["gates"]
    gates = [bid for bid in g["benchmarks"]]
    gate_status = []
    failed_hard = []
    for bid in gates:
        b = by_id.get(bid)
        st = {"benchmark_id": bid, "why": g["why"].get(bid, []), "score": b["score"] if b else None}
        if b and b["score"] <= g["hard_floor"]:
            st["status"] = "failed"
            failed_hard.append(bid)
        else:
            st["status"] = "passed" if b else "not scored"
        gate_status.append(st)
    overall = overall_raw
    cap_applied = bool(failed_hard) and overall is not None and overall > g["overall_cap"]
    if failed_hard and overall is not None:
        overall = min(overall, g["overall_cap"])

    fz = analyze_findings(report, cfg)
    open_f = {fid: z for fid, z in fz.items() if z["status"] in OPEN_STATUSES}
    by_zone: dict[str, dict[str, int]] = {}
    for z in open_f.values():
        by_zone.setdefault(z["criticality"], {s: 0 for s in SEVERITIES})
        if z["effective_severity"] in SEVERITIES:
            by_zone[z["criticality"]][z["effective_severity"]] += 1

    gaps_open = [x for x in report.get("gap_register", []) if x.get("status") in OPEN_STATUSES]
    critical_gaps = sum(1 for x in gaps_open if x.get("severity") == "critical")
    major_must = sum(1 for x in gaps_open if x.get("severity") == "major" and x.get("necessity") == "must-have")
    holdout = report.get("holdout", {}) or {}
    hold_rate = holdout.get("pass_rate") if holdout.get("run") else None

    def unmet(level: dict) -> list[dict]:
        out = []
        if "overall_min" in level and (overall is None or overall < level["overall_min"]):
            out.append({"requirement": f"overall ≥ {level['overall_min']}", "current": overall})
        if "gate_min" in level:
            for bid in gates:
                b = by_id.get(bid)
                if b and b["score"] < level["gate_min"]:
                    out.append({"requirement": f"gate ≥ {level['gate_min']}", "benchmark_id": bid,
                                "current": b["score"], "required": level["gate_min"]})
        if "any_min" in level:
            for b in scored:
                if b["score"] < level["any_min"] and not (b["id"] in gates and "gate_min" in level and b["score"] < level["gate_min"]):
                    out.append({"requirement": f"no benchmark < {level['any_min']}", "benchmark_id": b["id"],
                                "current": b["score"], "required": level["any_min"]})
        if "max_critical_gaps" in level and critical_gaps > level["max_critical_gaps"]:
            out.append({"requirement": "no critical gaps", "current": critical_gaps})
        if "max_major_must_have_gaps" in level and major_must > level["max_major_must_have_gaps"]:
            out.append({"requirement": "no major must-have gaps", "current": major_must})
        for lim in level.get("findings_limits", []) or []:
            ids = [fid for fid, z in open_f.items() if z["effective_severity"] == lim.get("severity")
                   and (not lim.get("zone") or z["criticality"] == lim["zone"])]
            if len(ids) > lim.get("max", 0):
                where = f" in {lim['zone']} zones" if lim.get("zone") else ""
                out.append({"requirement": f"at most {lim.get('max', 0)} open {lim.get('severity')} findings{where}",
                            "current": len(ids), "finding_ids": sorted(ids)})
        if level.get("tens_require_enforcement"):
            for b in scored:
                if b["score"] == 10 and not b.get("enforcement"):
                    out.append({"requirement": "every 10 backed by enforcement", "benchmark_id": b["id"], "current": 10})
        if "holdout_pass_rate_min" in level and hold_rate is not None and hold_rate < level["holdout_pass_rate_min"]:
            out.append({"requirement": f"hidden-check pass rate ≥ {level['holdout_pass_rate_min']}", "current": hold_rate})
        return out

    levels = [l for l in level_defs(cfg) if l["level"] != "L0"]
    current, next_level, blockers = "L0", None, []
    if failed_hard:
        next_level = levels[0]["level"] if levels else None
        blockers = [{"requirement": f"gate above {g['hard_floor']}", "benchmark_id": bid, "current": by_id[bid]["score"]}
                    for bid in failed_hard]
        blockers += unmet(levels[0]) if levels else []
    else:
        for lvl in levels:
            missing = unmet(lvl)
            if missing:
                next_level, blockers = lvl["level"], missing
                break
            current = lvl["level"]
    integrity = bool(report.get("integrity_flags"))
    before_integrity = current
    icap = cfg["maturity"].get("integrity_cap", "L1")
    if integrity and level_num(current) > level_num(icap):
        current = icap
        next_level = f"L{level_num(icap) + 1}"
        blockers = [{"requirement": "no integrity flags", "current": len(report["integrity_flags"])}]

    targets = compute_targets(report, cfg)
    below = []
    for b in scored:
        tv = targets.get(b["id"])
        if tv is not None and b["score"] < tv:
            below.append({"benchmark_id": b["id"], "score": b["score"], "target": tv, "gap": tv - b["score"],
                          "weight": b["weight"], "weighted_gap": (tv - b["score"]) * b["weight"]})
    below.sort(key=lambda x: (-x["weighted_gap"], x["benchmark_id"]))

    # ranked priorities
    pcfg = cfg.get("priorities", {})
    cost = pcfg.get("effort_cost", {"S": 1, "M": 2, "L": 4})
    mult = cfg["zones"]["priority_multiplier"]
    blocker_ids = {x.get("benchmark_id") for x in blockers if x.get("benchmark_id")}
    blocker_findings = {fid for x in blockers for fid in x.get("finding_ids", [])}
    prios = []
    sequential = True
    for b in report.get("benchmarks", []):
        if b.get("applicability") == "not_applicable" or not isinstance(b.get("score"), int):
            continue
        tv = targets.get(b["id"])
        ceiling = tv if tv is not None else 10
        reached = b["score"]   # format 5: each action's expected score counts the benchmark's earlier actions as done
        for act in b.get("path_to_target", []):
            resolved = [fz[f] for f in act.get("resolves", []) if f in fz]
            heat = max((r["criticality"] for r in resolved), key=lambda c: HEAT[c], default=cfg["zones"]["default"])
            expected = act.get("expected_new_score", b["score"])
            if not isinstance(expected, int):
                expected = b["score"]
            gain = max(0, min(expected, ceiling) - min(reached, ceiling))
            if sequential:
                reached = max(reached, expected)
            score = round(b.get("weight", 1) * gain * float(mult.get(heat, 1.0)) / float(cost.get(act.get("effort", "M"), 2)), 2)
            hot_critical = any(r["criticality"] == "hot" and r["effective_severity"] == "critical" and r["status"] in OPEN_STATUSES
                               for r in resolved)
            if b["id"] in failed_hard or hot_critical:
                tier = 0
            elif b["id"] in blocker_ids or blocker_findings.intersection(act.get("resolves", [])):
                tier = 1
            elif tv is not None and b["score"] < tv and not act.get("optional"):
                tier = 2
            else:
                tier = 3
            prios.append({"action_id": act.get("id"), "benchmark_id": b["id"], "tier": tier, "priority": score,
                          "zone": heat, "gain": gain, "effort": act.get("effort"),
                          "requires_human_decision": bool(act.get("requires_human_decision")),
                          "decision_question": act.get("decision_question"), "action": act.get("action"),
                          "decision": decision_for(act, cfg)})
    prios.sort(key=lambda p: (p["tier"], -p["priority"], p["action_id"] or ""))
    for i, p in enumerate(prios, 1):
        p["rank"] = i

    return {
        "computed_by": "gradekit.py",
        "config_hash": cfg["hash"],
        "pillar_scores": pillar_scores,
        "overall_score_uncapped": overall_raw,
        "overall_score": overall,
        "overall_cap_applied": cap_applied,
        "gates": gate_status,
        "maturity": {"current_level": current, "level_before_integrity_cap": before_integrity if integrity else None,
                     "next_level": next_level, "blockers": blockers},
        "open_gaps": {"critical": critical_gaps, "major_must_have": major_must},
        "open_findings_by_zone": by_zone,
        "finding_zones": fz,
        "targets": targets,
        "below_target": below,
        "priorities": prios,
        "weight_issues": weight_issues,
        "limits": {bid: lim for bid, lim in score_limits(report, cfg, fz).items() if lim["max"] < 10},
        "applicability": {
            "limited": [b["id"] for b in report.get("benchmarks", []) if b.get("applicability") == "limited"],
            "not_applicable": [b["id"] for b in report.get("benchmarks", []) if b.get("applicability") == "not_applicable"],
            "weight_notes": {b["id"]: b["weight_note"] for b in report.get("benchmarks", []) if b.get("weight_note")},
        },
    }


def decision_for(action: dict, cfg: dict) -> dict | None:
    """The human (or permitted agent) answer to an action's decision question, if any."""
    if not action.get("requires_human_decision"):
        return None
    allow_agents = bool((cfg.get("review") or {}).get("allow_agent_decisions"))
    match = None
    for d in cfg.get("decisions", []) or []:
        if d.get("action_id") != action.get("id"):
            continue
        q1, q2 = norm(str(d.get("question") or "")).lower(), norm(str(action.get("decision_question") or "")).lower()
        if q1 and q2 and q1 != q2:
            continue  # same ID, different question: an answer from an earlier cycle
        match = d  # last matching entry wins (append-only history)
    if not match:
        return {"status": "pending"}
    by = str(match.get("decided_by") or "")
    if by.lower().startswith("agent") and not allow_agents:
        return {"status": "pending", "note": f"answered by {by}, but agent decisions are not allowed (set [review] allow_agent_decisions = true in project.toml)"}
    return {"status": "approved" if match.get("approved") else "declined", "answer": match.get("answer"),
            "decided_by": by, "date": match.get("date")}


TIER_WHY = {0: "Fixes a critical problem in a hot zone, or a failed hard gate",
            1: "Clears a blocker to the next maturity level",
            2: "Raises a benchmark that's below its target",
            3: "Beyond the target"}
TOP_PRIORITIES = 10


def derived_top_priorities(report: dict, roll: dict) -> list[dict]:
    """The first ten of rollup.priorities, as top_priorities. `why_first` is the action's own (`report action
    --why-first`), else what the report already said for that action, else a line from its tier."""
    actions = {a.get("id"): a for b in report.get("benchmarks", []) for a in b.get("path_to_target", [])}
    said = {p.get("action_id"): p for p in report.get("top_priorities") or [] if p.get("action_id")}
    out = []
    for p in roll.get("priorities", [])[:TOP_PRIORITIES]:
        act, old = actions.get(p["action_id"]) or {}, said.get(p["action_id"]) or {}
        why = act.get("why_first") or old.get("why_first") or TIER_WHY.get(p["tier"], "")
        gain = f"+{p['gain']} on {p['benchmark_id']}" if p.get("gain") else f"no gain on {p['benchmark_id']} by itself"
        out.append({"rank": p["rank"], "benchmark_id": p["benchmark_id"], "action_id": p["action_id"], "why_first": why,
                    "expected_gain": gain})
    return out


def apply_rollup(report: dict, cfg: dict) -> dict:
    for f in report.get("findings", []):
        refresh_fingerprint(f)
    roll = compute_rollup(report, cfg)
    report["rollup"] = roll
    for b in report.get("benchmarks", []):
        b["target"] = roll["targets"].get(b.get("id"))
    report["top_priorities"] = derived_top_priorities(report, roll)
    return roll


def print_rollup(roll: dict) -> None:
    ps = "  ".join(f"{p}:{'—' if v is None else v}" for p, v in roll["pillar_scores"].items())
    print(f"Pillars   {ps}")
    print(f"Overall   {roll['overall_score']}" + (" (capped by a failed gate)" if roll["overall_cap_applied"] else ""))
    gates = ", ".join(f"{g['benchmark_id']}={g['score']}{'✗' if g['status'] == 'failed' else ''}" for g in roll["gates"])
    print(f"Gates     {gates}")
    m = roll["maturity"]
    print(f"Maturity  {m['current_level']}" + (f" → next {m['next_level']}" if m["next_level"] else " (top level)"))
    for blk in m["blockers"]:
        bid = f" {blk['benchmark_id']}" if "benchmark_id" in blk else ""
        req = f" (needs {blk['required']})" if "required" in blk else ""
        fids = f" [{', '.join(blk['finding_ids'])}]" if blk.get("finding_ids") else ""
        print(f"  blocker:{bid} {blk['requirement']}: current {blk['current']}{req}{fids}")
    z = roll["open_findings_by_zone"]
    if z:
        print("Open findings (effective severity): " + "; ".join(
            f"{k}: " + ", ".join(f"{n} {s}" for s, n in v.items() if n) for k, v in sorted(z.items(), key=lambda kv: -HEAT[kv[0]]) if any(v.values())))
    if roll["priorities"]:
        print("Top priorities:")
        for p in roll["priorities"][:8]:
            hd = f"  [decision: {p['decision']['status']}]" if p.get("decision") else ""
            print(f"  {p['rank']}. T{p['tier']} {p['action_id']} ({p['zone']}, +{p['gain']}, {p['effort']}) score {p['priority']}{hd}")
    a = roll["applicability"]
    if a["limited"] or a["not_applicable"] or a["weight_notes"]:
        print(f"Limited: {', '.join(a['limited']) or 'none'} · N/A: {', '.join(a['not_applicable']) or 'none'}"
              f" · weight notes: {', '.join(a['weight_notes']) or 'none'}")
    for w in roll["weight_issues"]:
        print(f"  weight issue: {w}")


def cmd_rollup(args) -> int:
    report = load_report(args.report)
    cfg = load_config(args, report)
    if (report.get("config") or {}).get("hash") not in (None, cfg["hash"]):
        print(f"warning: report config hash {report['config']['hash']} ≠ {cfg['hash']}; scoring with the latter")
    roll = apply_rollup(report, cfg)
    print_rollup(roll)
    out = None
    if args.write or args.out:
        out = args.out or args.report
        write_json(out, report)
        print(f"\nwrote rollup to {out}")
    args._result = {"rollup": roll, "written": out}
    return 1 if roll["weight_issues"] else 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_rollup(sub):
    p = sub.add_parser("rollup", help="compute gates, zones, scores, targets, maturity and priorities")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    with_config(p)
    p.add_argument("--write", action="store_true", help="write rollup and targets back into the report")
    p.add_argument("--out", help="write the updated report here instead")
    p.set_defaults(fn=cmd_rollup)
