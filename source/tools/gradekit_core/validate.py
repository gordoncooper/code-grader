"""validate: a report against the schema, the config and the suite's rules."""
from __future__ import annotations

import copy

from .common import (
    all_text, expected_weight, fingerprint_of, iter_evidence, kit_scoring_version, load_catalog, load_json,
    load_report, major, MAX_QUOTE_LINES, old_format_problem, OPEN_STATUSES, READABLE_REPORT_MAJORS, SCHEMA_PATH,
    scoring_version_of, SEVERITIES, withheld,
)
from .config import load_config, PUBLISHING_DEFAULTS, with_config
from .zones import analyze_findings
from .records import disposition_entry
from .schema import schema_messages
from .rollup import (
    CAP_SEVERITIES, catalog_caps, gate_not_applicable, left_to_the_other_report, over_limit, resolve_cap,
    score_limits,
)
from .publishing import publish_problems, sensitive_ids


def validate_report(report: dict, cfg: dict, catalog: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    problem = old_format_problem(report)
    if problem:
        return [problem], warnings
    errors += schema_messages(report, load_json(SCHEMA_PATH))
    if not isinstance(report.get("benchmarks"), list):
        return errors, warnings

    if major(report.get("suite_version", "0")) not in READABLE_REPORT_MAJORS:
        errors.append(f"suite_version {report.get('suite_version')}: this kit ({catalog['suite_version']}) reads reports from suite "
                      f"{' and '.join(m + '.x' for m in READABLE_REPORT_MAJORS)}; re-grade the project with this kit")
    rc = report.get("config", {}) or {}
    if rc.get("hash") != cfg["hash"]:
        errors.append(f"report was graded with config {rc.get('hash')} but checked against {cfg['hash']} "
                      "(pass the same --config the grader used)")
    if rc.get("preset") and rc.get("preset") != cfg["preset"]:
        errors.append(f"report preset '{rc.get('preset')}' differs from config preset '{cfg['preset']}'")

    canon = {b["id"]: b for b in catalog["benchmarks"]}
    seen: dict[str, int] = {}
    for b in report["benchmarks"]:
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
        if f.get("status") == "withdrawn" and (f.get("dispute") or {}).get("answer") != "withdrawn":
            errors.append(f"finding {fid} is withdrawn, but no answered dispute withdraws it: only a person's dispute (disputes.json) "
                          f"does, answered with `report finding answer REPORT {fid} --withdraw`")
        if f.get("status") == "accepted" and disposition_entry(f, cfg) is None:
            errors.append(f"finding {fid} is accepted, but no entry in dispositions.json accepts it: only people accept findings, "
                          f"by adding an entry for it there (`report finding accept REPORT {fid}` then records it)")
        if f.get("disposition") and f.get("status") != "accepted":
            warnings.append(f"finding {fid}: has a disposition but status is '{f.get('status')}'")
        if withheld(f):
            pass   # computed from the full report, before its evidence was withheld
        elif f.get("fingerprint") and f["fingerprint"] != fingerprint_of(f):
            errors.append(f"finding {fid}: fingerprint {f['fingerprint']} doesn't match its evidence (gradekit writes it: "
                          "`report check --write` or `rollup --write`)")
        elif not f.get("fingerprint"):
            warnings.append(f"finding {fid}: no fingerprint yet (`report check --write` or `rollup --write` adds it)")
    if report.get("rollup") and not str((report.get("run") or {}).get("model") or "").strip():
        errors.append("run.model is empty: a finished report records the model that graded it (`report set REPORT run.model NAME`)")
    if "migrated" in report:
        errors.append("migrated: `gradekit migrate` marked 4.x reports it converted, which kept their 4.x rules; this kit has only "
                      "its own rules, so open the report with the 5.x kit, or grade the project again")
    if major(scoring_version_of(report)) != major(kit_scoring_version()):
        errors.append(f"config.scoring_version is {scoring_version_of(report)}, but this kit grades under scoring {kit_scoring_version()} "
                      "only: scores from another scoring major aren't comparable, so grade the project again with this kit")
    if report.get("repo_rollup") and not cfg.get("components"):
        errors.append("repo_rollup is only for a monorepo's repo report, and project.toml defines no [[components]]")
    fz = analyze_findings(report, cfg)
    limits = score_limits(report, cfg, fz, catalog)
    caps_ = catalog_caps(catalog)
    for fid, f in findings.items():
        if f.get("cap"):
            c = caps_.get(f["cap"])
            if c is None:
                errors.append(f"finding {fid}: unknown cap {f['cap']} (the rubric lists each benchmark's caps)")
            elif c["benchmark"] != f.get("benchmark_id"):
                errors.append(f"finding {fid}: cap {f['cap']} belongs to {c['benchmark']}, not {f.get('benchmark_id')}")
            elif f.get("severity") not in CAP_SEVERITIES and f.get("status") in OPEN_STATUSES:
                warnings.append(f"finding {fid}: cap {f['cap']} doesn't hold on a {f.get('severity')} finding (a cap needs one that's "
                                "major or worse); raise its severity, or remove the cap")

    gates = set(cfg["gates"]["benchmarks"])
    referenced: set[str] = set()
    action_ids: set[str] = set()
    for b in report["benchmarks"]:
        bid = b.get("id")
        if bid not in canon:
            continue
        c = canon[bid]
        if b.get("name") != c["name"]:
            warnings.append(f"{bid}: name '{b.get('name')}' differs from catalog '{c['name']}'")
        if b.get("pillar") != c["pillar"]:
            errors.append(f"{bid}: pillar '{b.get('pillar')}' should be '{c['pillar']}'")
        app = b.get("applicability")
        cw = cfg["weights"][bid]["weight"]
        if b.get("config_weight") != cw:
            errors.append(f"{bid}: config_weight {b.get('config_weight')} should be {cw} (from the effective config)")
        want = expected_weight(app, cw)
        if app != "not_applicable" and b.get("weight") != want:
            errors.append(f"{bid}: weight {b.get('weight')} should be {want} ({app} applicability, config weight {cw})")
        if app in ("limited", "not_applicable") and not (b.get("applicability_reason") or "").strip():
            errors.append(f"{bid}: applicability '{app}' requires applicability_reason")
        if bid in gates and app == "not_applicable" and gate_not_applicable(bid, cfg, report):
            errors.append(gate_not_applicable(bid, cfg, report))
        elif bid in gates and app != "full" and not left_to_the_other_report(report, bid, cfg):
            warnings.append(f"{bid} is a gate but marked '{app}'; gates should almost always fully apply. Double-check.")
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
            gaps = [g for g in report.get("gap_register", []) if bid in (g.get("benchmark_ids") or []) and g.get("status") in OPEN_STATUSES]
            if score <= 6 and not b.get("finding_ids") and not gaps and not b.get("carried_forward"):
                warnings.append(f"{bid}: score {score} but no findings or gaps explain what is wrong")
            for w in over_limit(b, limits.get(bid)):
                errors.append(f"{bid}: score {score} is above its limit of {w['max']} ({w['why']})")
            for entry in b.get("caps_applied", []) or []:
                if resolve_cap(entry, bid, caps_) is None:
                    warnings.append(f"{bid}: caps_applied entry {entry!r} isn't a rubric cap (use its ID, e.g. {bid}-cap-1)")
        for fid in b.get("finding_ids", []):
            referenced.add(fid)
            if fid not in findings:
                errors.append(f"{bid}: references unknown finding {fid}")
        prev_expected = None
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
                elif fid in findings and findings[fid].get("benchmark_id") not in (None, bid):
                    warnings.append(f"{aid}: resolves {fid}, which is {findings[fid].get('benchmark_id')}'s; its fix belongs on "
                                    f"{findings[fid].get('benchmark_id')}'s path, or the ranking counts it twice")
            if act.get("requires_human_decision") and not (act.get("decision_question") or "").strip():
                errors.append(f"{aid}: requires_human_decision needs a decision_question")
            if isinstance(score, int) and isinstance(act.get("expected_new_score"), int) and act["expected_new_score"] < score:
                warnings.append(f"{aid}: expected_new_score {act['expected_new_score']} is below current score {score}")
            elif (isinstance(act.get("expected_new_score"), int) and isinstance(prev_expected, int)
                  and act["expected_new_score"] < prev_expected):
                warnings.append(f"{aid}: expected_new_score {act['expected_new_score']} is below the earlier action's "
                                f"{prev_expected}; it counts earlier actions as done, so it should be at least that")
            if isinstance(act.get("expected_new_score"), int):
                prev_expected = max(act["expected_new_score"], prev_expected or 0)

    listed_by = {fid: b.get("id") for b in report.get("benchmarks", []) for fid in b.get("finding_ids", []) or []}
    for fid, f in findings.items():
        own = f.get("benchmark_id")
        if f.get("status") in OPEN_STATUSES and own and fid not in referenced:
            errors.append(f"finding {fid} ({f.get('status')}) is {own}'s, but {own}'s finding_ids doesn't list it: "
                          "edit reports with `gradekit report` commands, which keep the lists, never by hand")
        elif f.get("status") in OPEN_STATUSES and fid not in referenced:
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
    if report.get("mode") == "full" and any(b.get("carried_forward") for b in report["benchmarks"]):
        warnings.append("full-mode report has carried_forward benchmarks; full audits should grade everything")

    sens = sensitive_ids(report)
    long_quotes = []
    for loc, ev, _ in iter_evidence(report):
        if ev.get("type") == "withheld" and loc.removeprefix("finding ") not in sens:
            errors.append(f"{loc}: withheld evidence is only for findings marked sensitive (redact adds it; graders cite real evidence)")
        if ev.get("type") == "code" and len(str(ev.get("quote") or "").strip("\n").splitlines()) > MAX_QUOTE_LINES:
            long_quotes.append(f"{loc} ({ev.get('file')}:{ev.get('lines')})")
    if long_quotes:
        warnings.append(f"{len(long_quotes)} quote(s) longer than {MAX_QUOTE_LINES} lines (cite the lines that show it; "
                        f"several --cite for several places): {', '.join(long_quotes[:5])}" + (" …" if len(long_quotes) > 5 else ""))
    pub = cfg.get("publishing") or PUBLISHING_DEFAULTS
    if pub.get("public"):
        floor = SEVERITIES.index(pub.get("warn_at", "major")) if pub.get("warn_at") in SEVERITIES else 1
        for fid, f in findings.items():
            if (f.get("benchmark_id") in (pub.get("sensitive_benchmarks") or []) and f.get("status") in OPEN_STATUSES
                    and f.get("severity") in SEVERITIES and SEVERITIES.index(f["severity"]) >= floor and fid not in sens):
                warnings.append(f"finding {fid} ({f.get('benchmark_id')}, {f.get('severity')}) isn't marked sensitive; "
                                f"this grading repo is public, so mark it \"sensitive\": true unless its details are harmless")
        if sens and not (report.get("publishing") or {}).get("redacted"):
            warnings.append(f"{len(sens)} sensitive finding(s); run `gradekit redact --in-place` before committing this report")
    return errors, warnings


def cmd_validate(args) -> int:
    catalog = load_catalog()
    report = load_report(args.report)
    cfg = load_config(args, report)
    errors, warnings = validate_report(report, cfg, catalog)
    if args.publish:
        errors += [f"publish: {e}" for e in publish_problems(report)]
    for w in cfg.get("warnings", []) + warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    args._result = {"valid": not errors, "errors": errors, "warnings": cfg.get("warnings", []) + warnings, "config_hash": cfg["hash"]}
    return 1 if errors else 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_validate(sub):
    p = sub.add_parser("validate", help="schema + config + semantic checks")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--publish", action="store_true", help="also fail unless the report is safe to commit to a public grading repo")
    with_config(p)
    p.set_defaults(fn=cmd_validate)
