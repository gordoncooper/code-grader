"""ci: the check on a grading repo's pull requests."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

from .common import (
    dash, DECISIONS_FILE, DISPOSITIONS_FILE, DISPUTES_FILE, emit, git_out, GradekitError, load_catalog, load_json,
    load_report, major, old_format_problem, PROJECT_FILE, report_format, suite_pin,
)
from .config import component_reports, load_config, parse_list_text, PUBLISHING_DEFAULTS, report_folders
from .records import disposition_entry, earlier_finding, finding_in, load_disputes, not_the_same_finding
from .rollup import compute_rollup
from .publishing import publish_problems, repo_rollup
from .validate import validate_report
from .evidence import citations_check_note
from .orders import ORDER_FILE, order_problems, work_order_note
from .render import render_report_md, review_link
from .index import INDEX_FILE, index_text


# Checks a pull request to a grading repo. One kind of change per pull request:
#   report    one new report folder (report.json, report.md, runs/*.json), and answers to its questions in its
#             project's decisions.json (append-only)
#   settings  a project's project.toml, decisions.json, dispositions.json (append-only), org.toml
# Writes a summary comment and labels; the host's CI posts them (see ci/ in the kit).

CI_MARKER = "<!-- gradekit-ci -->"
REPORT_FOLDER_FILES = re.compile(r"(report\.json|report\.md|runs/[^/]+\.json|components/[^/]+\.(?:json|md))")
SETTINGS_FILES = {PROJECT_FILE, DECISIONS_FILE, DISPOSITIONS_FILE, DISPUTES_FILE, "reports/.gitkeep"}
ROOT_SETTINGS = {"org.toml", "README.md", ".gitignore"}
CI_LABELS = {"report": "grading: report", "settings": "grading: settings",
             "problems": "grading: needs changes"}


def git_changes(root, base: str, head: str) -> list[tuple[str, str]]:
    out = git_out(root, "diff", "--no-renames", "--name-status", f"{base}...{head}")
    return [(ln.split("\t", 1)[0][0], ln.split("\t", 1)[1]) for ln in out.splitlines() if "\t" in ln]


def classify_change(changes: list[tuple[str, str]]) -> dict:
    """What kind of grading change this is, and anything about its shape that's wrong."""
    problems, report_folders_, settings, other = [], set(), {}, []
    for status, path in changes:
        if path == f"projects/{INDEX_FILE}":
            continue   # derived; checked against `gradekit index` in ci_check
        parts = path.split("/")
        if parts[0] == "projects" and len(parts) >= 4 and parts[2] == "reports" and len(parts) >= 5:
            folder = (parts[1], parts[3])
            rest = "/".join(parts[4:])
            report_folders_.add(folder)
            if path.endswith(".private.json"):
                problems.append(f"{path} is a private report: it must never be committed (remove it from the pull request)")
            elif not REPORT_FOLDER_FILES.fullmatch(rest):
                problems.append(f"{path}: a report folder holds only report.json, report.md and runs/*.json")
            elif status != "A":
                problems.append(f"{path} is {'deleted' if status == 'D' else 'changed'}: reports are never edited after they're committed")
        elif parts[0] == "projects" and len(parts) >= 3 and ("/".join(parts[2:]) in SETTINGS_FILES or ORDER_FILE.fullmatch("/".join(parts[2:]))):
            settings.setdefault(parts[1], []).append((status, "/".join(parts[2:])))
        elif path in ROOT_SETTINGS:
            settings.setdefault("", []).append((status, path))
        else:
            other.append(path)
    # A report's pull request may also answer that report's decision questions (the decide CI job commits them there).
    with_answers = bool(report_folders_) and len(report_folders_) == 1 and \
        set(settings) == {next(iter(report_folders_))[0]} and all(n == DECISIONS_FILE for _, n in settings[next(iter(report_folders_))[0]])
    kinds = (["report"] if report_folders_ else []) + (["settings"] if settings and not with_answers else [])
    if len(report_folders_) > 1:
        problems.append("a pull request adds one report: " + ", ".join(f"projects/{p}/reports/{f}" for p, f in sorted(report_folders_)))
    if len(kinds) > 1:
        problems.append("a report pull request changes only its report folder (and its project's decisions.json); send the settings changes "
                        f"({', '.join(p for p in sorted(settings) if p) or 'root files'}) separately")
    projects_ = sorted({p for p, _ in report_folders_} | {p for p in settings if p})
    if len(projects_) > 1:
        problems.append(f"one project per pull request (this one touches {', '.join(projects_)})")
    if other and kinds:
        problems.append("grading changes come on their own; this also changes " + ", ".join(other[:8]) + ("…" if len(other) > 8 else ""))
    kind = kinds[0] if len(kinds) == 1 else ("mixed" if kinds else "other")
    folder = sorted(report_folders_)[0] if report_folders_ else None
    return {"kind": kind, "project": folder[0] if folder else (projects_[0] if projects_ else None),
            "folder": folder[1] if folder else None, "settings": settings, "other": other, "problems": problems,
            "with_answers": with_answers}


def file_at(root, rev: str, path: str) -> str | None:
    import subprocess
    r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def config_at(root, rev: str, project: str) -> dict | None:
    """The project's effective config as it was at rev (None if it didn't exist)."""
    toml = file_at(root, rev, f"projects/{project}/{PROJECT_FILE}")
    if toml is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        pdir = Path(tmp) / "projects" / project
        pdir.mkdir(parents=True)
        (pdir / PROJECT_FILE).write_text(toml, encoding="utf-8")
        for name in (DECISIONS_FILE, DISPOSITIONS_FILE):
            t = file_at(root, rev, f"projects/{project}/{name}")
            if t is not None:
                (pdir / name).write_text(t, encoding="utf-8")
        org = file_at(root, rev, "org.toml")
        if org is not None:
            (Path(tmp) / "org.toml").write_text(org, encoding="utf-8")
        try:
            return load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), quiet=True)
        except GradekitError:
            return None


def append_only(old_text: str | None, new_text: str, key: str, name: str) -> list[str]:
    try:
        new = parse_list_text(new_text, key, name)
        old = parse_list_text(old_text, key, name) if old_text else []
    except GradekitError as exc:
        return [str(exc)]
    for i, entry in enumerate(old):
        if i >= len(new) or new[i] != entry:
            return [f"{name} is append-only: entry {i + 1} was changed or removed (add a new entry instead; the newest wins)"]
    return []


def people_records_problems(report: dict, pdir: Path, folder: str, cfg: dict) -> tuple[list[str], list[str]]:
    """A new report's acceptances and withdrawals, held to what people wrote and to the reports before it."""
    problems, warnings = [], []
    disputes = load_disputes(pdir)
    for f in report.get("findings", []):
        fid = f.get("id")
        entry = disposition_entry(f, cfg) if f.get("status") == "accepted" else None
        if entry:   # (no entry at all: validate already says so)
            why = not_the_same_finding(f, earlier_finding(pdir, folder, fid, entry[1].get("date")))
            if why:
                problems.append(f"finding {fid} is accepted, but it isn't the finding people accepted: {why}")
            if not entry[1].get("finding_id"):
                warnings.append(f"finding {fid} is accepted by a `match` entry ({DISPOSITIONS_FILE} entry {entry[0]}: "
                                f"{entry[1].get('match')!r}); check that it describes this finding")
        ans = f.get("dispute") or {}
        if f.get("status") == "withdrawn" and ans.get("answer") == "withdrawn":
            d = next((d for d in disputes if d.get("finding_id") == fid and d.get("date") == ans.get("disputed_on")), None)
            if d is None:
                problems.append(f"finding {fid} is withdrawn, but {DISPUTES_FILE} has no dispute on it dated {ans.get('disputed_on')}")
            else:
                why = not_the_same_finding(f, finding_in(pdir, d.get("report"), fid))
                if why:
                    problems.append(f"finding {fid} is withdrawn, but it isn't the finding that was disputed: {why}")
    return problems, warnings


def ci_check(root: Path, base: str, head: str, changes: list[tuple[str, str]], site: str | None = None,
             repo_url: str | None = None, branch: str | None = None) -> dict:
    mb = git_out(root, "merge-base", base, head, check=False) or base
    shape = classify_change(changes)
    problems, warnings = list(shape["problems"]), []
    summary: dict = {}
    project = shape["project"]
    pdir = root / "projects" / project if project else None

    if shape["kind"] == "report" and pdir is not None:
        folder = shape["folder"]
        rel = f"projects/{project}/reports/{folder}"
        if file_at(root, mb, f"{rel}/report.json") is not None:
            problems.append(f"{rel} already exists on the base branch: reports are never edited after they're committed")
        rpath = root / rel / "report.json"
        if not rpath.exists():
            problems.append(f"{rel} has no report.json")
        else:
            try:
                report = load_report(rpath)
                cfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), report, quiet=True)
                errors, warns = validate_report(report, cfg, load_catalog())
                note = work_order_note(pdir, report)
                if note:
                    warnings.append(note)
                pin = suite_pin(cfg)
                if pin and major(report.get("suite_version", "0")) != pin:
                    problems.append(f"the project is pinned to suite {pin}, but this report was made with suite {report.get('suite_version')}: "
                                    f"grade it with a {pin}.x kit, or change the pin in project.toml first (a settings change of its own)")
                problems += [f"report: {e}" for e in errors]
                for where, rep in [("report", report)] + [(f"components/{cp.name}", load_json(cp)) for cp in component_reports(root / rel)
                                                     if not old_format_problem(load_json(cp))]:
                    p_, w_ = people_records_problems(rep, pdir, folder, cfg)
                    problems += [f"{where}: {x}" for x in p_]
                    warnings += [f"{where}: {x}" for x in w_]
                earlier = [d for d in report_folders(pdir) if d.name != folder]
                if earlier and report_format(report) < max(report_format(load_json(d / "report.json")) for d in earlier):
                    problems.append(f"this report is format {report_format(report)}, older than the project's earlier reports: "
                                    "a project's reports never go back to an older format (grade it with this kit)")
                run_day = str((report.get("run") or {}).get("date") or "")[:10]
                if run_day and not folder.startswith(run_day):
                    problems.append(f"the folder is {folder}, but the report was graded on {run_day} (expected {run_day}-<commit>)")
                if earlier and folder < max(d.name for d in earlier):
                    problems.append(f"{folder} sorts before {max(d.name for d in earlier)}: a new report comes after the project's others")
                warnings += [f"report: {w}" for w in cfg.get("warnings", []) + warns if "run `gradekit redact" not in w]
                if (cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"):
                    problems += [f"publish: {e}" for e in publish_problems(report)]
                run = report.get("run") or {}
                commit = str(run.get("commit") or "")
                if commit and not folder.endswith("-" + commit[:7]):
                    problems.append(f"the folder is {folder}, but the report grades commit {commit[:7]} (expected <date>-{commit[:7]})")
                note = citations_check_note(report)
                if note:
                    warnings.append(note)
                roll = compute_rollup(report, cfg)
                stored = report.get("rollup") or {}
                if not stored:
                    problems.append("report has no rollup: run `gradekit rollup --write` (or `report check --write`)")
                elif (stored.get("overall_score"), (stored.get("maturity") or {}).get("current_level")) != (
                        roll["overall_score"], roll["maturity"]["current_level"]):
                    problems.append(f"the stored rollup ({stored.get('overall_score')}, {(stored.get('maturity') or {}).get('current_level')}) "
                                    f"doesn't match the report ({roll['overall_score']}, {roll['maturity']['current_level']}): "
                                    "never edit scores by hand; run `gradekit rollup --write`")
                md = root / rel / "report.md"
                if not md.exists():
                    warnings.append("no report.md (`gradekit render report` makes it)")
                else:
                    try:
                        if md.read_text(encoding="utf-8") != render_report_md(report, cfg):
                            warnings.append("report.md differs from what `gradekit render report` makes from report.json")
                    except GradekitError:
                        pass
                comps = component_reports(root / rel)
                parts = cfg.get("components") or {}
                if parts and {cp.stem for cp in comps} != set(parts):
                    missing, extra = sorted(set(parts) - {cp.stem for cp in comps}), sorted({cp.stem for cp in comps} - set(parts))
                    problems.append("a monorepo report has one report per component in project.toml ([[components]])"
                                    + (f"; missing: {', '.join(f'components/{m}.json' for m in missing)}" if missing else "")
                                    + (f"; not in project.toml: {', '.join(extra)}" if extra else ""))
                elif comps and not parts:
                    problems.append("this report has components/, but project.toml defines no [[components]]")
                if report.get("repo_rollup") and not parts:
                    problems.append("repo_rollup is only for a monorepo's repo report, and project.toml defines no [[components]]")
                for cp in comps:
                    try:
                        cr = load_report(cp)
                        ccfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), cr, quiet=True)
                        cerr, _ = validate_report(cr, ccfg, load_catalog())
                        problems += [f"components/{cp.name}: {e}" for e in cerr]
                        cmajor = major(cr.get("suite_version", "0"))
                        if (report_format(cr) != report_format(report) or cmajor != major(report.get("suite_version", "0"))
                                or (pin and cmajor != pin)):
                            problems.append(f"components/{cp.name} was made with suite {cr.get('suite_version')} (format {report_format(cr)}); "
                                            f"every report in the folder is made with the same kit"
                                            + (f", and the project is pinned to {pin}" if pin else ""))
                        if (cr.get("component") or {}).get("name") != cp.stem:
                            problems.append(f"components/{cp.name} grades component '{(cr.get('component') or {}).get('name')}', not '{cp.stem}'")
                        if (ccfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"):
                            problems += [f"components/{cp.name}: publish: {e}" for e in publish_problems(cr)]
                        croll, cst = compute_rollup(cr, ccfg), cr.get("rollup") or {}
                        if (cst.get("overall_score"), (cst.get("maturity") or {}).get("current_level")) != (
                                croll["overall_score"], croll["maturity"]["current_level"]):
                            problems.append(f"components/{cp.name}: the stored rollup doesn't match its scores; run `gradekit rollup --write`")
                    except GradekitError as exc:
                        problems.append(f"components/{cp.name}: {exc}")
                if comps and parts:
                    try:
                        want = repo_rollup(comps, parts)
                        have = report.get("repo_rollup")
                        if not have:
                            problems.append("a monorepo report needs its repo-wide result: `gradekit rollup-repo FOLDER --write`")
                        elif (have.get("overall_score"), have.get("maturity")) != (want["overall_score"], want["maturity"]):
                            problems.append(f"repo_rollup ({have.get('overall_score')}, {have.get('maturity')}) doesn't match the "
                                            f"component reports ({want['overall_score']}, {want['maturity']}): run `gradekit rollup-repo FOLDER --write`")
                    except GradekitError as exc:
                        problems.append(str(exc))
                if (root / rel / "runs").is_dir() and not report.get("stability"):
                    warnings.append("there are runs/ but report.json isn't their consensus (`gradekit stability … --out report.json`)")
                pending = [p for p in roll["priorities"] if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
                summary = {"project": project, "folder": folder, "commit": commit[:7], "date": str(run.get("date") or "")[:10],
                           "overall": roll["overall_score"], "level": roll["maturity"]["current_level"],
                           "next_level": roll["maturity"].get("next_level"),
                           "gates": [(g["benchmark_id"], g["score"], g["status"]) for g in roll["gates"]],
                           "pending_decisions": [(p["action_id"], p.get("decision_question")) for p in pending],
                           "mode": report.get("mode")}
            except GradekitError as exc:
                problems.append(f"report: {exc}")

    if shape["kind"] == "settings" or (shape["kind"] == "report" and shape["with_answers"]):
        for proj, files in shape["settings"].items():
            for status, name in files:
                path = f"projects/{proj}/{name}" if proj else name
                if status == "D" and name in (PROJECT_FILE, DECISIONS_FILE, DISPOSITIONS_FILE, DISPUTES_FILE, "org.toml"):
                    problems.append(f"{path} is deleted")
                    continue
                if ORDER_FILE.fullmatch(name):
                    if status == "D":
                        problems.append(f"{path} is deleted: close a work order instead (`gradekit order close`)")
                        continue
                    try:
                        order = json.loads((root / path).read_text(encoding="utf-8"))
                    except json.JSONDecodeError as exc:
                        problems.append(f"{path}: {exc}")
                        continue
                    problems += [f"{path}: {p}" for p in order_problems(order, name.split("/")[-1])]
                    before = file_at(root, mb, path)
                    if before is not None:
                        try:
                            old = json.loads(before)
                        except json.JSONDecodeError:
                            old = {}
                        changed = {k for k in set(old) | set(order) if old.get(k) != order.get(k)} - {"status", "closed"}
                        if changed:
                            problems.append(f"{path}: a work order only changes when it's closed (status, closed); this changes "
                                            + ", ".join(sorted(changed)))
                    continue
                if name in (DECISIONS_FILE, DISPOSITIONS_FILE, DISPUTES_FILE):
                    key = {DECISIONS_FILE: "decisions", DISPOSITIONS_FILE: "dispositions", DISPUTES_FILE: "disputes"}[name]
                    new_text = (root / path).read_text(encoding="utf-8")
                    problems += append_only(file_at(root, mb, path), new_text, key, path)
                    need = {"decisions": ("action_id", "approved"), "dispositions": ("finding_id", "decision", "reason"),
                            "disputes": ("finding_id", "reason", "by", "date")}[key]
                    try:
                        for i, e in enumerate(parse_list_text(new_text, key, path)):
                            missing = [k for k in need if k not in e]
                            if missing:
                                problems.append(f"{path} entry {i + 1} needs {', '.join(missing)}")
                    except GradekitError:
                        pass
    if shape["kind"] == "settings":
        projects_ = [p for p in shape["settings"] if p] or ([project] if project else [])
        if "" in shape["settings"] and not projects_:
            projects_ = [d.name for d in sorted((root / "projects").iterdir()) if (d / PROJECT_FILE).exists()] if (root / "projects").is_dir() else []
        for proj in projects_:
            try:
                cfg = load_config(argparse.Namespace(project_dir=str(root / "projects" / proj), config=None, component=None), quiet=True)
                warnings += [f"{proj}: {w}" for w in cfg.get("warnings", [])]
                before = config_at(root, mb, proj)
                if before is None:
                    summary.setdefault("new_projects", []).append(proj)
                elif before["hash"] != cfg["hash"]:
                    warnings.append(f"{proj}: the scoring config changes ({before['hash']} → {cfg['hash']}), so the next report "
                                    "is weighted differently from earlier ones; diffs will say so")
                summary.setdefault("configs", []).append((proj, cfg["hash"], cfg["preset"]))
            except GradekitError as exc:
                problems.append(f"{proj}: config: {exc}")

    if any(p == f"projects/{INDEX_FILE}" for _, p in changes):
        idx = root / "projects" / INDEX_FILE
        if idx.exists() and idx.read_text(encoding="utf-8") != index_text(root):
            problems.append(f"projects/{INDEX_FILE} doesn't match the reports: don't edit it; run `gradekit index` "
                            "(or leave it out: CI rebuilds it after merging)")
    labels = ([CI_LABELS[shape["kind"]]] if shape["kind"] in CI_LABELS else []) + ([CI_LABELS["problems"]] if problems else [])
    result = {"kind": shape["kind"], "project": project, "folder": shape["folder"], "ok": not problems,
              "problems": problems, "warnings": warnings, "labels": labels, "summary": summary,
              "changed": [p for _, p in changes]}
    result["comment"] = ci_comment(result, site, repo_url, branch)
    return result


def ci_comment(res: dict, site: str | None, repo_url: str | None, branch: str | None) -> str:
    s = res["summary"]
    head = "✅ passed" if res["ok"] else "❌ needs changes"
    lines = [CI_MARKER, f"### Grading check: {head}", ""]
    if res["kind"] == "report" and s:
        lines.append(f"**Report** for `{s['project']}` at `{s['commit']}` ({s['date']}"
                     + (", PR check" if s.get("mode") == "pr" else "") + f"): overall **{dash(s['overall'])}**, "
                     f"maturity **{s['level']}**" + (f" (next: {s['next_level']})" if s.get("next_level") else "") + ".")
        lines += ["", "Gates: " + " · ".join(f"{g} {dash(sc)} {st}" for g, sc, st in s["gates"])]
        if s["pending_decisions"]:
            lines += ["", f"**{len(s['pending_decisions'])} decision(s) waiting:**"]
            lines += [f"- [ ] {a}: {q}" for a, q in s["pending_decisions"]]
        link = review_link(site, repo_url, s["project"], branch) if branch else None
        if link:
            lines += ["", f"[Review this report{' and answer the decisions' if s['pending_decisions'] else ''}]({link})"]
    elif res["kind"] == "settings":
        lines.append("**Settings** change" + (f" for `{res['project']}`" if res["project"] else "") + ".")
        for proj, h_, preset in s.get("configs", []):
            lines.append(f"- `{proj}`: config {h_} (preset {preset})" + (" · new project" if proj in s.get("new_projects", []) else ""))
    elif res["kind"] == "other":
        lines.append("No grading files changed, so there was nothing to check.")
    if res["problems"]:
        lines += ["", "**Problems**", ""] + [f"- {p}" for p in res["problems"]]
    if res["warnings"]:
        items = [f"- {w}" for w in res["warnings"]]
        if len(items) > 5:
            lines += ["", f"<details><summary><b>{len(items)} warnings</b></summary>", ""] + items + ["", "</details>"]
        else:
            lines += ["", "**Warnings**", ""] + items
    lines += ["", f"<sub>gradekit ci · suite {load_catalog()['suite_version']}</sub>", ""]
    return "\n".join(lines)


def cmd_ci(args) -> int:
    root = Path(git_out(args.grading_repo or ".", "rev-parse", "--show-toplevel"))
    if args.changed:
        changes = [tuple(c.split(":", 1)) if re.match(r"^[AMD]:", c) else ("A", c) for c in args.changed]
    else:
        changes = git_changes(root, args.base, args.head)
    res = ci_check(root, args.base, args.head, changes, args.site, args.grading_repo_url, args.branch)
    if args.comment_file:
        Path(args.comment_file).write_text(res["comment"], encoding="utf-8")
    if args.labels_file:
        Path(args.labels_file).write_text("\n".join(res["labels"]) + ("\n" if res["labels"] else ""), encoding="utf-8")
    lines = [f"{res['kind']} change" + (f" · {res['project']}" if res["project"] else "") + (f" · {res['folder']}" if res["folder"] else "")]
    lines += [f"PROBLEM: {p}" for p in res["problems"]] + [f"warning: {w}" for w in res["warnings"]]
    lines.append(f"\n{'passed' if res['ok'] else 'needs changes'}; labels: {', '.join(res['labels']) or 'none'}")
    emit(args, res, "\n".join(lines))
    return 0 if res["ok"] else 1
