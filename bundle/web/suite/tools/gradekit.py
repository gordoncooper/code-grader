#!/usr/bin/env python3
"""gradekit: companion tool for the Code Grading Suite (v3).

Never trust a grader's arithmetic or citations; check them.

Commands:
  validate         Check a report against the schema and the suite's rules.
  verify-evidence  Confirm every code citation exists in the repo and the quote matches.
  rollup           Compute weights check, targets, pillar/overall scores, caps and maturity.
  stability        Merge several independent runs on one commit into a median consensus.
  diff             Compare two reports (score deltas, findings, regressions, divergence).
  calibrate        Compare a report against human-expected scores for a reference repo.
  redact           Strip hidden-check details so a report can be shared with improvers.
  rollup-repo      Combine per-component reports for a monorepo.

Standard library only; uses `jsonschema` for structural validation when installed.
Exit codes: 0 ok, 1 invalid/failed check, 2 regression (diff --fail-on-regression),
3 unstable runs (stability --strict), 4 calibration failed.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import statistics
import sys
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent.parent
WEIGHTS_PATH = SUITE_DIR / "rubric" / "weights.json"
SCHEMA_PATH = SUITE_DIR / "schema" / "report.schema.json"
PILLARS = ["A", "B", "C", "D", "E", "F", "X"]
OPEN_STATUSES = {"new", "open", "regressed"}


# --------------------------------------------------------------------------- helpers

def load_json(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        sys.exit(f"error: file not found: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {path} is not valid JSON: {exc}")


def write_json(path: str | Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_weights() -> dict:
    return load_json(WEIGHTS_PATH)


def major(version: str) -> str:
    return str(version).split(".")[0]


def level_num(level: str) -> int:
    return int(str(level).lstrip("L"))


def benchmarks_by_id(report: dict) -> dict:
    return {b.get("id"): b for b in report.get("benchmarks", [])}


def expected_weight(applicability: str, profile_weight: int) -> int:
    if applicability == "limited":
        return min(profile_weight, 1)
    if applicability == "not_applicable":
        return 0
    return profile_weight


def iter_evidence(report: dict):
    """Yield (location, evidence, benchmark_id_or_None) for every evidence object."""
    for f in report.get("findings", []):
        for ev in f.get("evidence", []):
            yield f"finding {f.get('id')}", ev, f.get("benchmark_id")
    for b in report.get("benchmarks", []):
        for i, s in enumerate(b.get("strengths", [])):
            for ev in s.get("evidence", []):
                yield f"{b.get('id')} strength #{i + 1}", ev, b.get("id")
        for ev in b.get("enforcement", []):
            yield f"{b.get('id')} enforcement", ev, b.get("id")
    for feat in report.get("feature_inventory", []):
        for ev in feat.get("evidence", []) or []:
            yield f"feature '{feat.get('feature')}'", ev, None
    for i, flag in enumerate(report.get("integrity_flags", [])):
        for ev in flag.get("evidence", []):
            yield f"integrity flag #{i + 1}", ev, None


def all_text(obj) -> str:
    if isinstance(obj, dict):
        return " ".join(all_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(all_text(v) for v in obj)
    return str(obj) if obj is not None else ""


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- validate

def validate_report(report: dict, weights: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # Structural schema
    try:
        import jsonschema  # type: ignore

        schema = load_json(SCHEMA_PATH)
        validator = jsonschema.Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(report), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"schema: {loc}: {err.message}")
    except ImportError:
        warnings.append("jsonschema not installed; structural schema check skipped (semantic checks still run)")
        for key in ("suite_version", "mode", "run", "profile", "benchmarks", "findings"):
            if key not in report:
                errors.append(f"missing required field '{key}'")

    if errors and not isinstance(report.get("benchmarks"), list):
        return errors, warnings

    # Suite version
    if major(report.get("suite_version", "0")) != major(weights["suite_version"]):
        errors.append(f"suite_version {report.get('suite_version')} does not match suite major version {weights['suite_version']}")

    profile = report.get("profile")
    if profile not in weights["profiles"]:
        errors.append(f"unknown profile '{profile}'")
        return errors, warnings

    canon = {b["id"]: b for b in weights["benchmarks"]}
    seen: dict[str, int] = {}
    for b in report.get("benchmarks", []):
        seen[b.get("id")] = seen.get(b.get("id"), 0) + 1
    for bid in canon:
        if bid not in seen:
            errors.append(f"benchmark {bid} missing (every benchmark must appear once; use not_applicable)")
    for bid, n in seen.items():
        if bid not in canon:
            errors.append(f"unknown benchmark id {bid}")
        elif n > 1:
            errors.append(f"benchmark {bid} appears {n} times")

    findings = {f.get("id"): f for f in report.get("findings", [])}
    if len(findings) != len(report.get("findings", [])):
        errors.append("duplicate finding IDs")
    for fid, f in findings.items():
        if fid and not str(fid).startswith(f"{f.get('benchmark_id')}-"):
            errors.append(f"finding {fid}: ID prefix does not match benchmark_id {f.get('benchmark_id')}")
        if f.get("status") == "accepted" and not f.get("disposition"):
            errors.append(f"finding {fid}: status 'accepted' requires disposition text")
        if f.get("disposition") and f.get("status") != "accepted":
            warnings.append(f"finding {fid}: has a disposition but status is '{f.get('status')}'")

    referenced: set[str] = set()
    action_ids: set[str] = set()
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if bid not in canon:
            continue
        c = canon[bid]
        if b.get("name") != c["name"]:
            warnings.append(f"{bid}: name '{b.get('name')}' differs from canonical '{c['name']}'")
        if b.get("pillar") != c["pillar"]:
            errors.append(f"{bid}: pillar '{b.get('pillar')}' should be '{c['pillar']}'")
        app = b.get("applicability")
        pw = c["weights"][profile]
        if b.get("profile_weight") != pw:
            errors.append(f"{bid}: profile_weight {b.get('profile_weight')} should be {pw} for profile {profile}")
        want = expected_weight(app, pw)
        if app != "not_applicable" and b.get("weight") != want:
            errors.append(f"{bid}: weight {b.get('weight')} should be {want} ({app} applicability, profile weight {pw})")
        if app in ("limited", "not_applicable") and not (b.get("applicability_reason") or "").strip():
            errors.append(f"{bid}: applicability '{app}' requires applicability_reason")
        score = b.get("score")
        if app == "not_applicable":
            if score is not None:
                errors.append(f"{bid}: not_applicable benchmarks must have score null")
        else:
            if score is None:
                errors.append(f"{bid}: applicable benchmark has no score")
            if b.get("confidence") is None:
                errors.append(f"{bid}: applicable benchmark needs confidence")
        if isinstance(score, int):
            if score >= 9 and not b.get("strengths"):
                errors.append(f"{bid}: score {score} requires positive evidence in 'strengths'")
            if score == 10 and not b.get("enforcement"):
                errors.append(f"{bid}: score 10 requires 'enforcement' evidence (otherwise max 9)")
            if score <= 6 and not b.get("finding_ids") and not b.get("carried_forward"):
                warnings.append(f"{bid}: score {score} but no findings explain what is wrong")
        for fid in b.get("finding_ids", []):
            referenced.add(fid)
            if fid not in findings:
                errors.append(f"{bid}: references unknown finding {fid}")
        for act in b.get("path_to_target", []):
            aid = act.get("id", "")
            if aid in action_ids:
                errors.append(f"duplicate action id {aid}")
            action_ids.add(aid)
            if not aid.startswith(f"{bid}-act-"):
                errors.append(f"{bid}: action id {aid} should start with {bid}-act-")
            for fid in act.get("resolves", []):
                if fid not in findings and not fid.startswith("GAP-"):
                    errors.append(f"{aid}: resolves unknown finding {fid}")
            if act.get("requires_human_decision") and not (act.get("decision_question") or "").strip():
                errors.append(f"{aid}: requires_human_decision needs a decision_question")
            if isinstance(score, int) and isinstance(act.get("expected_new_score"), int) and act["expected_new_score"] < score:
                warnings.append(f"{aid}: expected_new_score {act['expected_new_score']} is below current score {score}")

    for fid, f in findings.items():
        if f.get("status") in OPEN_STATUSES and fid not in referenced:
            warnings.append(f"finding {fid} ({f.get('status')}) is not referenced by any benchmark")

    gap_ids = [g.get("id") for g in report.get("gap_register", [])]
    if len(gap_ids) != len(set(gap_ids)):
        errors.append("duplicate gap IDs")

    for p in report.get("top_priorities", []):
        aid = p.get("action_id")
        if aid and aid not in action_ids:
            errors.append(f"top_priorities rank {p.get('rank')}: unknown action_id {aid}")

    holdout = report.get("holdout", {})
    if holdout.get("run") and holdout.get("pass_rate") is None:
        errors.append("holdout.run is true but pass_rate is null")
    # Leak check: names of hidden checks must not appear elsewhere in the report.
    private = holdout.get("private_details")
    names: set[str] = set()
    if isinstance(private, list):
        for item in private:
            if isinstance(item, dict):
                for key in ("check", "id", "name"):
                    val = item.get(key)
                    if isinstance(val, str) and len(val) >= 6:
                        names.add(val)
    if names:
        public = copy.deepcopy(report)
        public.get("holdout", {}).pop("private_details", None)
        public_text = all_text(public)
        for n in sorted(names):
            if n in public_text:
                errors.append(f"hidden-check leak: '{n}' appears outside holdout.private_details")

    if report.get("mode") == "full" and any(b.get("carried_forward") for b in report.get("benchmarks", [])):
        warnings.append("full-mode report has carried_forward benchmarks; full audits should grade everything")

    return errors, warnings


def cmd_validate(args) -> int:
    weights = load_weights()
    report = load_json(args.report)
    errors, warnings = validate_report(report, weights)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


# --------------------------------------------------------------------------- verify-evidence

def check_code_evidence(ev: dict, repo: Path, tolerance: int) -> str | None:
    rel = ev.get("file", "")
    if Path(rel).is_absolute():
        return f"absolute path not allowed: {rel}"
    target = (repo / rel).resolve()
    try:
        target.relative_to(repo)
    except ValueError:
        return f"path escapes the repo: {rel}"
    if not target.is_file():
        return f"file not found: {rel}"
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(ev.get("lines", "")))
    if not m:
        return f"bad line range '{ev.get('lines')}'"
    start = int(m.group(1))
    end = int(m.group(2) or start)
    if end < start or start < 1:
        return f"bad line range '{ev.get('lines')}'"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"cannot read {rel}: {exc}"
    if end > len(lines):
        return f"{rel} has {len(lines)} lines; cited {start}-{end}"
    lo = max(0, start - 1 - tolerance)
    hi = min(len(lines), end + tolerance)
    window = norm("\n".join(lines[lo:hi]))
    quote = norm(ev.get("quote", ""))
    if not quote:
        return "empty quote"
    if quote not in window:
        return f"quote not found at {rel}:{start}-{end} (±{tolerance} lines)"
    return None


def cmd_verify_evidence(args) -> int:
    report = load_json(args.report)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        sys.exit(f"error: repo not found: {repo}")
    carried = {b["id"] for b in report.get("benchmarks", []) if b.get("carried_forward")}
    checked = skipped = 0
    failures: list[str] = []
    other = {"command": 0, "absence": 0}
    for loc, ev, bid in iter_evidence(report):
        etype = ev.get("type")
        if etype != "code":
            other[etype] = other.get(etype, 0) + 1
            continue
        if bid in carried:
            skipped += 1
            continue
        checked += 1
        problem = check_code_evidence(ev, repo, args.tolerance)
        if problem:
            failures.append(f"{loc}: {problem}")
    for f in failures:
        print(f"FAIL: {f}")
    print(f"\ncode citations checked: {checked}, failed: {len(failures)}, "
          f"skipped (carried forward): {skipped}; command: {other.get('command', 0)}, "
          f"absence: {other.get('absence', 0)} (not machine-checkable)")
    return 1 if failures else 0


# --------------------------------------------------------------------------- rollup

def compute_targets(report: dict, weights: dict) -> dict:
    mode = report.get("target_mode", "proportional")
    overrides = report.get("target_overrides", {}) or {}
    tcfg = weights["targets"]
    level_req = None
    if mode.startswith("level:"):
        lvl = mode.split(":", 1)[1]
        level_req = next((l for l in weights["maturity_levels"] if l["level"] == lvl), None)
        if level_req is None:
            raise SystemExit(f"error: unknown target level '{lvl}'")
    targets = {}
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if b.get("applicability") == "not_applicable" or b.get("score") is None:
            targets[bid] = None
            continue
        w = b.get("weight", 1)
        if mode == "maximal":
            t = 10
        elif level_req is not None:
            if b.get("pillar") == "A":
                t = level_req.get("pillar_A_min", level_req.get("any_min", 1))
            else:
                t = level_req.get("any_min", 1)
        else:
            t = tcfg["proportional_by_weight"].get(str(w), 8)
        if b.get("applicability") == "limited":
            t = min(t, tcfg["limited_cap"])
        if bid in overrides:
            t = overrides[bid]
        targets[bid] = t
    return targets


def weighted(items: list[tuple[int, int]]) -> float | None:
    total_w = sum(w for _, w in items)
    if total_w == 0:
        return None
    return round(sum(s * w for s, w in items) / total_w, 1)


def compute_rollup(report: dict, weights: dict) -> dict:
    canon = {b["id"]: b for b in weights["benchmarks"]}
    profile = report.get("profile")
    weight_issues = []
    scored: list[dict] = []
    for b in report.get("benchmarks", []):
        bid = b.get("id")
        if bid in canon and profile in weights["profiles"]:
            pw = canon[bid]["weights"][profile]
            want = expected_weight(b.get("applicability"), pw)
            if b.get("applicability") != "not_applicable" and b.get("weight") != want:
                weight_issues.append(f"{bid}: weight {b.get('weight')} but rules give {want}")
        if b.get("applicability") != "not_applicable" and isinstance(b.get("score"), int) and b.get("weight", 0) > 0:
            scored.append(b)

    pillar_scores = {}
    for p in PILLARS:
        pillar_scores[p] = weighted([(b["score"], b["weight"]) for b in scored if b.get("pillar") == p])
    overall_raw = weighted([(b["score"], b["weight"]) for b in scored])
    cap = weights["overall_cap"]
    by_id = {b["id"]: b for b in scored}
    cap_applied = any(by_id.get(i, {}).get("score", 99) <= cap["score_at_or_below"] for i in cap["if_any_of"])
    overall = overall_raw
    if cap_applied and overall is not None:
        overall = min(overall, cap["overall_max"])

    gaps_open = [g for g in report.get("gap_register", []) if g.get("status") in OPEN_STATUSES]
    critical_gaps = sum(1 for g in gaps_open if g.get("severity") == "critical")
    major_must = sum(1 for g in gaps_open if g.get("severity") == "major" and g.get("necessity") == "must-have")
    holdout = report.get("holdout", {}) or {}
    hold_rate = holdout.get("pass_rate") if holdout.get("run") else None
    pillar_a = [b for b in scored if b.get("pillar") == "A"]

    def unmet(level: dict) -> list[dict]:
        out = []
        if "overall_min" in level and (overall is None or overall < level["overall_min"]):
            out.append({"requirement": f"overall ≥ {level['overall_min']}", "current": overall})
        if "pillar_A_min" in level:
            for b in pillar_a:
                if b["score"] < level["pillar_A_min"]:
                    out.append({"requirement": f"Pillar A ≥ {level['pillar_A_min']}", "benchmark_id": b["id"],
                                "current": b["score"], "required": level["pillar_A_min"]})
        if "any_min" in level:
            for b in scored:
                if b["score"] < level["any_min"] and not (b.get("pillar") == "A" and "pillar_A_min" in level and b["score"] < level["pillar_A_min"]):
                    out.append({"requirement": f"no benchmark < {level['any_min']}", "benchmark_id": b["id"],
                                "current": b["score"], "required": level["any_min"]})
        if "max_critical_gaps" in level and critical_gaps > level["max_critical_gaps"]:
            out.append({"requirement": "no critical gaps", "current": critical_gaps})
        if "max_major_must_have_gaps" in level and major_must > level["max_major_must_have_gaps"]:
            out.append({"requirement": "no major must-have gaps", "current": major_must})
        if level.get("tens_require_enforcement"):
            for b in scored:
                if b["score"] == 10 and not b.get("enforcement"):
                    out.append({"requirement": "every 10 backed by enforcement", "benchmark_id": b["id"], "current": 10})
        if "holdout_pass_rate_min" in level and hold_rate is not None and hold_rate < level["holdout_pass_rate_min"]:
            out.append({"requirement": f"hidden-check pass rate ≥ {level['holdout_pass_rate_min']}", "current": hold_rate})
        return out

    levels = [l for l in weights["maturity_levels"] if l["level"] != "L0"]
    current = "L0"
    blockers: list[dict] = []
    next_level = None
    if not cap_applied:
        for lvl in levels:
            missing = unmet(lvl)
            if missing:
                next_level, blockers = lvl["level"], missing
                break
            current = lvl["level"]
    else:
        next_level = "L1"
        blockers = [{"requirement": "score above 3 (A1/A2 floor)", "benchmark_id": i, "current": by_id[i]["score"]}
                    for i in cap["if_any_of"] if i in by_id and by_id[i]["score"] <= cap["score_at_or_below"]]
        blockers += unmet(levels[0])

    integrity = bool(report.get("integrity_flags"))
    level_before_integrity = current
    if integrity and level_num(current) > 1:
        current = "L1"
        next_level = "L2"
        blockers = [{"requirement": "no integrity flags", "current": len(report["integrity_flags"])}]

    targets = compute_targets(report, weights)
    to_target = []
    for b in scored:
        t = targets.get(b["id"])
        if t is not None and b["score"] < t:
            to_target.append({"benchmark_id": b["id"], "score": b["score"], "target": t,
                              "gap": t - b["score"], "weight": b["weight"],
                              "weighted_gap": (t - b["score"]) * b["weight"]})
    to_target.sort(key=lambda x: (-x["weighted_gap"], x["benchmark_id"]))

    return {
        "computed_by": "gradekit.py",
        "pillar_scores": pillar_scores,
        "overall_score_uncapped": overall_raw,
        "overall_score": overall,
        "overall_cap_applied": cap_applied,
        "maturity": {
            "current_level": current,
            "level_before_integrity_cap": level_before_integrity if integrity else None,
            "next_level": next_level,
            "blockers": blockers,
        },
        "open_gaps": {"critical": critical_gaps, "major_must_have": major_must},
        "targets": targets,
        "below_target": to_target,
        "weight_issues": weight_issues,
        "applicability": {
            "limited": [b["id"] for b in report.get("benchmarks", []) if b.get("applicability") == "limited"],
            "not_applicable": [b["id"] for b in report.get("benchmarks", []) if b.get("applicability") == "not_applicable"],
            "weight_notes": {b["id"]: b["weight_note"] for b in report.get("benchmarks", []) if b.get("weight_note")},
        },
    }


def apply_rollup(report: dict, weights: dict) -> dict:
    roll = compute_rollup(report, weights)
    report["rollup"] = roll
    for b in report.get("benchmarks", []):
        b["target"] = roll["targets"].get(b.get("id"))
    return roll


def print_rollup(roll: dict, label: str = "") -> None:
    if label:
        print(f"== {label} ==")
    ps = "  ".join(f"{p}:{'—' if v is None else v}" for p, v in roll["pillar_scores"].items())
    print(f"Pillars   {ps}")
    capnote = " (capped by A1/A2)" if roll["overall_cap_applied"] else ""
    print(f"Overall   {roll['overall_score']}{capnote}")
    m = roll["maturity"]
    print(f"Maturity  {m['current_level']}" + (f" → next {m['next_level']}" if m["next_level"] else " (top level)"))
    for blk in m["blockers"]:
        bid = f" {blk['benchmark_id']}" if "benchmark_id" in blk else ""
        req = f" (needs {blk['required']})" if "required" in blk else ""
        print(f"  blocker:{bid} {blk['requirement']}: current {blk['current']}{req}")
    if roll["below_target"]:
        print("Below target (by weighted gap):")
        for t in roll["below_target"][:10]:
            print(f"  {t['benchmark_id']}: {t['score']} → {t['target']} (weight {t['weight']})")
    a = roll["applicability"]
    if a["limited"] or a["not_applicable"] or a["weight_notes"]:
        print(f"Limited: {', '.join(a['limited']) or 'none'} · N/A: {', '.join(a['not_applicable']) or 'none'}"
              f" · weight notes: {', '.join(a['weight_notes']) or 'none'}")
    for w in roll["weight_issues"]:
        print(f"  weight issue: {w}")


def cmd_rollup(args) -> int:
    weights = load_weights()
    report = load_json(args.report)
    roll = apply_rollup(report, weights)
    print_rollup(roll)
    if args.write or args.out:
        out = args.out or args.report
        write_json(out, report)
        print(f"\nwrote rollup to {out}")
    return 1 if roll["weight_issues"] else 0


# --------------------------------------------------------------------------- stability

def cmd_stability(args) -> int:
    weights = load_weights()
    runs = [load_json(p) for p in args.reports]
    if len(runs) < 2:
        sys.exit("error: need at least two runs")
    commits = {r.get("run", {}).get("commit") for r in runs}
    if len(commits) > 1:
        print(f"warning: runs graded different commits: {sorted(map(str, commits))}")
    ids = [b["id"] for b in weights["benchmarks"]]
    rows = []
    medians: dict[str, dict] = {}
    unstable = []
    for bid in ids:
        entries = [benchmarks_by_id(r).get(bid, {}) for r in runs]
        apps = [e.get("applicability", "not_applicable") for e in entries]
        scores = [e.get("score") for e in entries]
        na_votes = apps.count("not_applicable")
        majority_na = na_votes > len(runs) / 2
        nums = [s for s in scores if isinstance(s, int)]
        med = None if majority_na or not nums else statistics.median_low(nums)
        spread = (max(nums) - min(nums)) if nums else 0
        app_split = len(set(apps)) > 1
        flag = spread > 1 or app_split
        if flag:
            unstable.append(bid)
        applicable_apps = [a for a in apps if a != "not_applicable"]
        maj_app = "not_applicable" if majority_na else statistics.mode(applicable_apps)
        medians[bid] = {"median": med, "applicability": maj_app, "scores": scores,
                        "applicability_votes": apps, "spread": spread, "unstable": flag}
        rows.append((bid, scores, med, spread, flag, app_split))

    def distance(r):
        d = 0
        bb = benchmarks_by_id(r)
        for bid, m in medians.items():
            s = bb.get(bid, {}).get("score")
            if isinstance(s, int) and m["median"] is not None:
                d += abs(s - m["median"])
        return d

    base_idx = min(range(len(runs)), key=lambda i: distance(runs[i]))
    consensus = copy.deepcopy(runs[base_idx])
    canon = {b["id"]: b for b in weights["benchmarks"]}
    for b in consensus.get("benchmarks", []):
        m = medians.get(b.get("id"))
        if not m:
            continue
        if m["applicability"] == "not_applicable":
            b["applicability"] = "not_applicable"
            b["score"] = None
            b["confidence"] = None
            b.setdefault("applicability_reason", "majority of runs judged not applicable")
        else:
            if b.get("applicability") == "not_applicable":
                b["applicability"] = m["applicability"]
                b["applicability_reason"] = b.get("applicability_reason") or "consensus of other runs"
                b["confidence"] = "low"
            b["score"] = m["median"]
            pw = canon[b["id"]]["weights"][consensus["profile"]]
            b["weight"] = expected_weight(b["applicability"], pw)
    overall_by_run = [compute_rollup(r, weights)["overall_score"] for r in runs]
    consensus["stability"] = {
        "runs": len(runs),
        "base_run_index": base_idx + 1,
        "method": "median_low of integer scores; majority vote on applicability",
        "overall_by_run": overall_by_run,
        "unstable_benchmarks": unstable,
        "per_benchmark": medians,
    }
    roll = apply_rollup(consensus, weights)

    print(f"{'ID':<4} {'scores':<20} {'median':>6} {'spread':>6}")
    for bid, scores, med, spread, flag, app_split in rows:
        s = ",".join("–" if x is None else str(x) for x in scores)
        mark = "  ← unstable" + (" (applicability split)" if app_split else "") if flag else ""
        print(f"{bid:<4} {s:<20} {('–' if med is None else med):>6} {spread:>6}{mark}")
    print(f"\noverall by run: {overall_by_run}  → consensus {roll['overall_score']} ({roll['maturity']['current_level']})")
    print(f"unstable benchmarks: {', '.join(unstable) or 'none'}  (spread > 1 or applicability split: tighten their rubric wording)")
    if args.out:
        write_json(args.out, consensus)
        print(f"wrote consensus report to {args.out}")
    return 3 if (args.strict and unstable) else 0


# --------------------------------------------------------------------------- diff

def cmd_diff(args) -> int:
    weights = load_weights()
    old, new = load_json(args.old), load_json(args.new)
    regressions: list[str] = []
    notes: list[str] = []
    same_major = major(old.get("suite_version", "0")) == major(new.get("suite_version", "0"))
    r_old, r_new = compute_rollup(old, weights), compute_rollup(new, weights)

    print(f"{old.get('run', {}).get('commit')} → {new.get('run', {}).get('commit')}  (mode: {new.get('mode')})")
    if not same_major:
        notes.append("suite major versions differ; score deltas are not comparable and are not used for regressions")

    ob, nb = benchmarks_by_id(old), benchmarks_by_id(new)
    changes = []
    for bid in [b["id"] for b in weights["benchmarks"]]:
        so, sn = ob.get(bid, {}).get("score"), nb.get(bid, {}).get("score")
        if so != sn:
            changes.append((bid, so, sn))
            if same_major and isinstance(so, int) and isinstance(sn, int) and sn < so:
                regressions.append(f"{bid} dropped {so} → {sn}")
            if same_major and isinstance(so, int) and sn is None:
                notes.append(f"{bid} went from {so} to N/A; check the applicability reason")
        go = set(ob.get(bid, {}).get("gaming_flags", []) or [])
        gn = set(nb.get(bid, {}).get("gaming_flags", []) or [])
        for g in sorted(gn - go):
            regressions.append(f"{bid} new gaming flag: {g}")

    print("\nScore changes:" if changes else "\nScore changes: none")
    for bid, so, sn in changes:
        print(f"  {bid}: {'–' if so is None else so} → {'–' if sn is None else sn}")
    print(f"Overall: {r_old['overall_score']} → {r_new['overall_score']}   "
          f"Maturity: {r_old['maturity']['current_level']} → {r_new['maturity']['current_level']}")
    if level_num(r_new["maturity"]["current_level"]) < level_num(r_old["maturity"]["current_level"]):
        regressions.append(f"maturity dropped {r_old['maturity']['current_level']} → {r_new['maturity']['current_level']}")

    of = {f["id"]: f for f in old.get("findings", [])}
    nf = {f["id"]: f for f in new.get("findings", [])}
    new_ids = [i for i, f in nf.items() if i not in of or f.get("status") == "new"]
    fixed = [i for i, f in nf.items() if f.get("status") == "fixed" and of.get(i, {}).get("status") != "fixed"]
    regressed = [i for i, f in nf.items() if f.get("status") == "regressed"]
    vanished = [i for i, f in of.items() if i not in nf and f.get("status") in OPEN_STATUSES]
    print(f"\nFindings: {len(new_ids)} new, {len(fixed)} fixed, {len(regressed)} regressed")
    for i in new_ids:
        f = nf[i]
        print(f"  new       {i} [{f.get('severity')}] {f.get('title')}")
        if f.get("severity") in ("critical", "major"):
            regressions.append(f"new {f.get('severity')} finding {i}: {f.get('title')}")
    for i in fixed:
        print(f"  fixed     {i} {nf[i].get('title')}")
    for i in regressed:
        print(f"  regressed {i} {nf[i].get('title')}")
        regressions.append(f"finding regressed {i}: {nf[i].get('title')}")
    for i in vanished:
        notes.append(f"open finding {i} disappeared without a 'fixed' status (finding IDs must be stable)")

    if new.get("integrity_flags"):
        regressions.append(f"{len(new['integrity_flags'])} integrity flag(s) in the new report")

    ho, hn = old.get("holdout", {}) or {}, new.get("holdout", {}) or {}
    if ho.get("run") and hn.get("run") and ho.get("pass_rate") is not None and hn.get("pass_rate") is not None:
        print(f"Hidden checks: {ho['pass_rate']:.0%} → {hn['pass_rate']:.0%}")
        if hn["pass_rate"] < ho["pass_rate"]:
            regressions.append(f"hidden-check pass rate dropped {ho['pass_rate']:.0%} → {hn['pass_rate']:.0%}")
            if (r_new["overall_score"] or 0) - (r_old["overall_score"] or 0) >= 0.5:
                notes.append("DIVERGENCE: visible scores rose while hidden checks fell; suspect the code is being "
                             "tuned to the rubric. Review the changes by hand before trusting these scores.")

    for n in notes:
        print(f"note: {n}")
    if regressions:
        print("\nREGRESSIONS:")
        for r in regressions:
            print(f"  - {r}")
        print("\nverdict: FAIL")
    else:
        print("\nverdict: PASS")
    return 2 if (args.fail_on_regression and regressions) else 0


# --------------------------------------------------------------------------- calibrate

def cmd_calibrate(args) -> int:
    report = load_json(args.report)
    exp = load_json(args.expected)
    crit = {"within_tolerance_pct": 90, "mae_max": 0.75, **exp.get("criteria", {})}
    bb = benchmarks_by_id(report)
    total = within = 0
    abs_errors = []
    app_mismatch = []
    print(f"{'ID':<4} {'expected':>8} {'actual':>6} {'Δ':>4}")
    for bid, e in sorted(exp.get("expected", {}).items()):
        b = bb.get(bid, {})
        actual = b.get("score")
        if e.get("applicability") and e["applicability"] != b.get("applicability"):
            app_mismatch.append(f"{bid}: expected {e['applicability']}, got {b.get('applicability')}")
        if e.get("score") is None or actual is None:
            continue
        tol = e.get("tolerance", 1)
        delta = actual - e["score"]
        total += 1
        within += abs(delta) <= tol
        abs_errors.append(abs(delta))
        mark = "" if abs(delta) <= tol else "  ← outside tolerance"
        print(f"{bid:<4} {e['score']:>8} {actual:>6} {delta:>+4}{mark}")
    if not total:
        sys.exit("error: no comparable benchmarks")
    pct = 100 * within / total
    mae = sum(abs_errors) / total
    bias = sum((bb[b]["score"] - e["score"]) for b, e in exp["expected"].items()
               if e.get("score") is not None and bb.get(b, {}).get("score") is not None) / total
    for m in app_mismatch:
        print(f"applicability mismatch: {m}")
    ok = pct >= crit["within_tolerance_pct"] and mae <= crit["mae_max"] and not app_mismatch
    print(f"\nwithin tolerance: {pct:.0f}% (need ≥ {crit['within_tolerance_pct']}%)  "
          f"MAE: {mae:.2f} (need ≤ {crit['mae_max']})  bias: {bias:+.2f} "
          f"({'grader runs generous' if bias > 0.25 else 'grader runs harsh' if bias < -0.25 else 'no clear bias'})")
    print("calibration: PASS" if ok else "calibration: FAIL")
    return 0 if ok else 4


# --------------------------------------------------------------------------- redact

def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("private_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


def cmd_redact(args) -> int:
    report = load_json(args.report)
    shared = strip_private(copy.deepcopy(report))
    if "holdout" in shared:
        shared["holdout"]["private_details"] = "[redacted]"
    out = args.out or re.sub(r"\.json$", "", args.report) + ".shared.json"
    write_json(out, shared)
    print(f"wrote redacted report to {out}")
    return 0


# --------------------------------------------------------------------------- rollup-repo

def cmd_rollup_repo(args) -> int:
    weights = load_weights()
    reports = [load_json(p) for p in args.reports]
    rows = []
    for path, r in zip(args.reports, reports):
        comp = r.get("component") or {}
        name = comp.get("name") or Path(path).stem
        cw = comp.get("weight", 1)
        roll = compute_rollup(r, weights)
        rows.append({"component": name, "weight": cw, "profile": r.get("profile"),
                     "overall": roll["overall_score"], "level": roll["maturity"]["current_level"],
                     "next_level": roll["maturity"]["next_level"], "blockers": roll["maturity"]["blockers"]})
    scored = [(r["overall"], r["weight"]) for r in rows if r["overall"] is not None]
    tw = sum(w for _, w in scored)
    overall = round(sum(s * w for s, w in scored) / tw, 1) if tw else None
    lowest = min(rows, key=lambda r: level_num(r["level"]))
    print(f"{'component':<20} {'profile':<12} {'weight':>6} {'overall':>7} level")
    for r in rows:
        print(f"{r['component']:<20} {str(r['profile']):<12} {r['weight']:>6} {str(r['overall']):>7} {r['level']}")
    print(f"\nrepo overall (component-weighted): {overall}")
    print(f"repo maturity (lowest component): {lowest['level']}  ← limited by '{lowest['component']}'")
    if args.out:
        write_json(args.out, {"computed_by": "gradekit.py rollup-repo", "overall_score": overall,
                              "maturity": lowest["level"], "limited_by": lowest["component"], "components": rows})
        print(f"wrote {args.out}")
    return 0


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gradekit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="schema + semantic checks")
    p.add_argument("report")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("verify-evidence", help="check code citations against the repo")
    p.add_argument("report")
    p.add_argument("--repo", required=True)
    p.add_argument("--tolerance", type=int, default=2, help="line drift allowed around the cited range (default 2)")
    p.set_defaults(fn=cmd_verify_evidence)

    p = sub.add_parser("rollup", help="compute pillar/overall scores, targets, maturity")
    p.add_argument("report")
    p.add_argument("--write", action="store_true", help="write rollup and targets back into the report")
    p.add_argument("--out", help="write the updated report here instead")
    p.set_defaults(fn=cmd_rollup)

    p = sub.add_parser("stability", help="median consensus across independent runs")
    p.add_argument("reports", nargs="+")
    p.add_argument("--out", help="write the consensus report here")
    p.add_argument("--strict", action="store_true", help="exit 3 if any benchmark is unstable")
    p.set_defaults(fn=cmd_stability)

    p = sub.add_parser("diff", help="compare two reports")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--fail-on-regression", action="store_true")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("calibrate", help="compare a report with expected scores")
    p.add_argument("report")
    p.add_argument("expected")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("redact", help="strip hidden-check details for sharing")
    p.add_argument("report")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_redact)

    p = sub.add_parser("rollup-repo", help="combine per-component reports")
    p.add_argument("reports", nargs="+")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_rollup_repo)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
