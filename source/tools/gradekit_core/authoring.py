"""Writing a report: the `report …` commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from .common import (
    benchmarks_by_id, die, emit, enforcement_items, evidence_line, EXIT_INCOMPLETE, expected_weight,
    FINDING_STATUSES, _finite_number, GAP_STATUSES, iter_evidence, load_json, load_report, MAX_QUOTE_LINES, norm,
    _not_json, pin_problem, plural, refresh_fingerprint, REPO_LEVEL, repo_relative, REPORT_FORMAT, RUBRIC, say_later,
    SEVERITIES, slug, started_arg, utc_now, write_json,
)
from .config import load_config, project_dir_for_report, project_dir_from_args, report_folders, with_config
from .records import ACCEPT_HINT, open_disputes, WITHDRAW_HINT
from .rollup import (
    apply_rollup, CAP_SEVERITIES, catalog_caps, compute_rollup, compute_targets, gate_not_applicable, over_limit,
    resolve_cap, score_limits,
)
from .validate import validate_report
from .evidence import fs_reader, record_citations_checked, verify_evidence, zip_reader
from .orders import work_order_note


# Graders build reports with these commands instead of typing JSON: weights, targets, quotes and
# IDs all come from the tool. Every command re-normalizes the report against the effective config.

REPORT_LISTS = ("commands_run", "feature_inventory", "gap_register", "findings", "integrity_flags",
                "top_priorities", "limitations")
CONFIDENCE = ("high", "medium", "low")


def minutes_between(start: str, end: str) -> float | None:
    import datetime
    try:
        a, b = (datetime.datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in (start, end))
    except (TypeError, ValueError):
        return None
    return round(max((b - a).total_seconds(), 0) / 60, 1)


def blank_benchmark(b: dict, cfg: dict) -> dict:
    cw = cfg["weights"][b["id"]]["weight"]
    return {"id": b["id"], "name": b["name"], "pillar": b["pillar"], "applicability": "full", "applicability_reason": None,
            "config_weight": cw, "weight": cw, "weight_note": None, "score": None, "confidence": None,
            "carried_forward": False, "caps_applied": [], "finding_ids": [], "strengths": [], "enforcement": [],
            "gaming_flags": [], "target": None, "path_to_target": [], "previous_score": None, "change_explanation": None}


def normalize_report(report: dict, cfg: dict, catalog: dict | None = None) -> dict:
    """Fill everything the tool knows: every benchmark (catalog order), names, pillars, weights, targets
    and finding_ids. Never touches a grader's judgments (scores, findings, evidence, prose)."""
    catalog = catalog or RUBRIC.catalog
    for key in REPORT_LISTS:
        report.setdefault(key, [])
    report.setdefault("metrics", {})
    report.setdefault("scope_examined", "")
    report.setdefault("holdout", {"run": False, "checks_run": None, "pass_rate": None, "private_details": None})
    have = benchmarks_by_id(report)
    benches = []
    for c in catalog["benchmarks"]:
        b = have.get(c["id"]) or blank_benchmark(c, cfg)
        b.update({"name": c["name"], "pillar": c["pillar"], "config_weight": cfg["weights"][c["id"]]["weight"]})
        b["weight"] = expected_weight(b.get("applicability"), b["config_weight"])
        if b.get("applicability") == "not_applicable":
            b["score"], b["confidence"] = None, None
        for key in ("caps_applied", "finding_ids", "strengths", "enforcement", "gaming_flags", "path_to_target"):
            b.setdefault(key, [])
        benches.append(b)
    report["benchmarks"] = benches + [b for bid, b in have.items() if bid not in {c["id"] for c in catalog["benchmarks"]}]
    by_id = benchmarks_by_id(report)
    for f in report["findings"]:
        b = by_id.get(f.get("benchmark_id"))
        if b is not None and f.get("id") not in b["finding_ids"]:
            b["finding_ids"].append(f.get("id"))
        refresh_fingerprint(f)
    for bid, tv in compute_targets(report, cfg).items():
        if bid in by_id:
            by_id[bid]["target"] = tv
    return report


def authoring_config(args, report: dict) -> dict:
    if not (getattr(args, "config", None) or getattr(args, "project", None) or getattr(args, "project_dir", None)):
        pdir = project_dir_for_report(args.report)
        if pdir:
            args.project_dir = str(pdir)
    return load_config(args, report, quiet=True)


def parse_cite(spec: str) -> tuple[str, int, int]:
    m = re.fullmatch(r"(.+):(\d+)(?:-(\d+))?", spec.strip())
    if not m:
        die(f"--cite takes FILE:LINE or FILE:START-END, got '{spec}'")
    start, end = int(m.group(2)), int(m.group(3) or m.group(2))
    if start < 1 or end < start:
        die(f"bad line range in '{spec}'")
    return repo_relative(m.group(1)), start, end


def repo_reader(repo: str | None):
    if not repo:
        die("--cite needs --repo (the code checkout, or a zip of it) to read the quote from")
    path = Path(repo)
    if path.suffix == ".zip" and path.is_file():
        return zip_reader(str(path))
    if not path.is_dir():
        die(f"repo not found: {repo}")
    return fs_reader(path)


def cite(spec: str, read_lines, note: str | None = None) -> dict:
    """An evidence object whose quote is copied from the file, so it always verifies."""
    rel, start, end = parse_cite(spec)
    if Path(rel).is_absolute() or ".." in Path(rel).parts:
        die(f"cite a path inside the repo: {rel}")
    lines = read_lines(rel)
    if isinstance(lines, str):
        die(lines)
    if end > len(lines):
        die(f"{rel} has {len(lines)} lines; cited {start}-{end}")
    if not "".join(lines[start - 1:end]).strip():
        near = next((n for d in range(1, 4) for n in (start - d, end + d) if 1 <= n <= len(lines) and lines[n - 1].strip()), None)
        die(f"{rel}:{start}-{end} is blank; cite the lines that show the problem" + (f" (line {near} has text)" if near else ""))
    asked = (start, end)
    while not lines[start - 1].strip():   # a blank line at either end is an off-by-one: cite only the lines with text
        start += 1
    while not lines[end - 1].strip():
        end -= 1
    if end - start + 1 > MAX_QUOTE_LINES:   # a quote is 1-3 lines: keep the first three, and say so
        say_later(f"note: {rel}:{asked[0]}-{asked[1]} is {asked[1] - asked[0] + 1} lines and a quote is at most {MAX_QUOTE_LINES}: cited "
                  f"{rel}:{start}-{start + MAX_QUOTE_LINES - 1}. If the line that shows it is further down, cite that instead, "
                  "or give --cite again for it")
        end = start + MAX_QUOTE_LINES - 1
        while not lines[end - 1].strip():
            end -= 1
    elif (start, end) != asked:
        say_later(f"note: {rel}:{asked[0]}-{asked[1]} has blank lines at its ends; cited {rel}:{start}-{end}")
    quote = "\n".join(lines[start - 1:end])
    first = quote.strip().splitlines()[0].strip()
    say_later(f"cited {rel}:{start}{'' if start == end else f'-{end}'}: {first[:70]}{'…' if len(first) > 70 or start != end else ''}")
    ev = {"type": "code", "file": rel, "lines": str(start) if start == end else f"{start}-{end}", "quote": quote}
    if note:
        ev["note"] = note
    return ev


def read_text_arg(value: str | None) -> str | None:
    """'@path' reads a file, '-' reads stdin; anything else is the text itself."""
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        try:
            return Path(value[1:]).read_text(encoding="utf-8")
        except OSError as exc:
            die(f"cannot read {value[1:]}: {exc}")
    return value


def _record_order(namespace, dest, values):
    setattr(namespace, "_order", (getattr(namespace, "_order", None) or []) + [(dest, values)])


class InOrder(argparse._StoreAction):
    """Stores the option as usual, and also records it in args._order, so evidence and notes keep the order given."""
    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string)
        _record_order(namespace, self.dest, values)


class InOrderAppend(argparse._AppendAction):
    """The same, for a repeatable option."""
    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string)
        _record_order(namespace, self.dest, values)


class InOrderTrue(argparse._StoreTrueAction):
    """A flag (--no-output) whose place among the other options counts."""
    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string)
        _record_order(namespace, self.dest, True)


def as_list(v) -> list:
    return [] if v is None else v if isinstance(v, list) else [v]


def paired(args, first: str, seconds: tuple[str, ...], hint: str) -> list[tuple]:
    """Pairs each --first with its --second (e.g. --command with --excerpt or --no-output), in the order given."""
    firsts = as_list(getattr(args, first, None))
    order = [(k, v) for k, v in (getattr(args, "_order", None) or []) if k in seconds]
    if order:
        thens = order
    else:   # called without the parser's record (or only one of each)
        thens = [(seconds[0], v) for v in as_list(getattr(args, seconds[0], None))]
        if len(seconds) > 1 and getattr(args, seconds[1], None):
            thens.append((seconds[1], True))
    if len(firsts) != len(thens):
        die(f"each --{first.replace('_', '-')} needs its own {hint}, in the same order: "
            f"got {len(firsts)} --{first.replace('_', '-')} and {len(thens)} {hint}")
    return [(f, k, v) for f, (k, v) in zip(firsts, thens)]


def evidence_notes(args, kinds: list[str]) -> list[str | None]:
    """The note for each evidence item, in the order the items were given. One --note applies to every item (as
    before 5.0). With several, each --note belongs to the evidence just before it, and a --note before any evidence
    applies to the items without one of their own; or, after all the evidence, one --note per item, in order."""
    notes = getattr(args, "note", None)
    if isinstance(notes, str):
        notes = [notes]
    notes = notes or []
    if len(notes) <= 1:
        return [notes[0] if notes else None] * len(kinds)
    order = [(k, v) for k, v in (getattr(args, "_order", None) or []) if k in ("cite", "command", "absence", "note")]
    first_note = next((i for i, (k, _) in enumerate(order) if k == "note"), len(order))
    if len(notes) == len(kinds) and all(k == "note" for k, _ in order[first_note:]) and first_note == len(order) - len(notes):
        return list(notes)   # all the notes after all the evidence: one each, in order
    mine: list[str | None] = []
    default = None
    for k, v in order:
        if k == "note":
            if mine and mine[-1] is None:
                mine[-1] = v
            elif not mine:
                default = v
            else:
                die(f"--note {v!r} follows evidence that already has a note: give each --note right after its --cite, --command or --absence")
        else:
            mine.append(None)
    return [n if n is not None else default for n in mine]


def evidence_from_args(args, required: bool = False, report: dict | None = None) -> list[dict]:
    out = []
    for second, first in (("excerpt", "command"), ("no_output", "command"), ("method", "absence")):
        if getattr(args, second, None) and not as_list(getattr(args, first, None)):
            die(f"--{second.replace('_', '-')} goes with --{first}: give the --{first} it belongs to")
    cites = getattr(args, "cite", None) or []
    kinds = (["cite"] * len(cites)) + (["command"] * len(as_list(getattr(args, "command", None)))) \
        + (["absence"] * len(as_list(getattr(args, "absence", None))))
    if getattr(args, "_order", None) and len(kinds) > 1:   # the order they were given, for the notes
        kinds = [k for k, _ in args._order if k in ("cite", "command", "absence")]
    notes = dict(zip(range(len(kinds)), evidence_notes(args, kinds)))
    by_kind = {k: [notes[i] for i, kk in enumerate(kinds) if kk == k] for k in ("cite", "command", "absence")}
    if cites:
        read = repo_reader(getattr(args, "repo", None))
        out += [cite(c, read, n) for c, n in zip(cites, by_kind["cite"] or [None] * len(cites))]
    ran = (report or {}).get("commands_run") or []
    cmd_notes = by_kind["command"] or []
    for k, (command, kind, value) in enumerate(paired(args, "command", ("excerpt", "no_output"), "--excerpt (or --no-output)")
                                               if as_list(getattr(args, "command", None)) else []):
        m = re.fullmatch(r"@(\d+)", command.strip())
        if m:   # a command already recorded with `report ran`: its exact text
            n = int(m.group(1))
            if not 1 <= n <= len(ran):
                die(f"--command {command}: the report has {plural(len(ran), 'recorded command')} "
                    "(`report show REPORT commands` numbers them)")
            command = ran[n - 1]["command"]
        if kind == "no_output":
            excerpt = "(no output)"
        else:
            excerpt = read_text_arg(value)
            if not (excerpt or "").strip():
                die("--command needs --excerpt (the relevant output, copied; '@file' or '-' for stdin), or --no-output "
                    "for a command that printed nothing (say what happened, e.g. the exit code or a timeout, in --note)")
            fp = next((c.get("output") for c in ran if norm(str(c.get("command") or "")) == norm(command) and c.get("output")), None)
            bad = excerpt_mismatches(excerpt, fp or {})
            if bad:
                die(f"{plural(len(bad), 'line')} of this excerpt {'is' if len(bad) == 1 else 'are'}n't "
                    f"{'a whole line' if len(bad) == 1 else 'whole lines'} of what `{command[:50]}` printed (e.g. {bad[0][:70]!r}). "
                    "Copy whole lines from its output (spacing can differ, and '...' can stand for lines you leave out)")
        note = cmd_notes[k] if k < len(cmd_notes) else None
        out.append({"type": "command", "command": command, "excerpt": excerpt.strip("\n"), **({"note": note} if note else {})})
    abs_notes = by_kind["absence"] or []
    for k, (what, _, how) in enumerate(paired(args, "absence", ("method",), "--method (how you searched)")
                                       if as_list(getattr(args, "absence", None)) else []):
        note = abs_notes[k] if k < len(abs_notes) else None
        out.append({"type": "absence", "searched": what, "method": how, **({"note": note} if note else {})})
    if required and not out:
        die("give evidence: --cite FILE:LINES (with --repo), --command CMD --excerpt TEXT, or --absence WHAT --method HOW")
    return out


def recorded_ids(report: dict) -> set[str]:
    """The IDs a report gives its findings and gaps. Only these: text that mentions an ID ("confirmed A1-001")
    doesn't take it."""
    ids = {str(f.get("id")) for f in report.get("findings") or [] if isinstance(f, dict) and f.get("id")}
    ids |= {str(g.get("id")) for g in report.get("gap_register") or [] if isinstance(g, dict) and g.get("id")}
    return ids


def known_ids(report_path, report: dict, pattern: str) -> set[str]:
    """IDs matching pattern in this report and every report of its project, so new IDs never reuse old ones."""
    ids = recorded_ids(report)
    pdir = project_dir_for_report(report_path)
    if pdir:
        for folder in report_folders(pdir):
            for f in [folder / "report.json", *sorted((folder / "runs").glob("*.json"))]:
                if f.exists() and f.resolve() != Path(report_path).resolve():
                    try:
                        ids |= recorded_ids(json.loads(f.read_text(encoding="utf-8", errors="replace")))
                    except json.JSONDecodeError:
                        continue
    return {i for i in ids if re.fullmatch(pattern.replace(r"\b", ""), i)}


def next_id(prefix: str, sep: str, taken: set[str], width: int = 3) -> str:
    nums = [int(i.rsplit(sep, 1)[1]) for i in taken if i.startswith(prefix + sep) and i.rsplit(sep, 1)[1].isdigit()]
    return f"{prefix}{sep}{str(max(nums, default=0) + 1).zfill(width)}"


def benchmark_or_die(report: dict, bid: str) -> dict:
    b = benchmarks_by_id(report).get(str(bid).upper())
    if b is None:
        die(f"unknown benchmark '{bid}'")
    return b


def finding_or_die(report: dict, fid: str) -> dict:
    f = next((f for f in report.get("findings", []) if f.get("id") == fid), None)
    if f is None:
        die(f"no finding {fid} in this report")
    return f


def cmd_report_new(args) -> int:
    if args.mode == "pr" and not args.base_commit:
        die("--mode pr needs --base-commit")
    m = re.fullmatch(r"(\d+)/(\d+)", args.run or "1/1")
    if not m or not 1 <= int(m.group(1)) <= int(m.group(2)):
        die(f"--run takes N/COUNT, e.g. 2/3; got '{args.run}'")
    run_index, run_count = int(m.group(1)), int(m.group(2))
    repo_level = getattr(args, "component", None) == "repo"
    if repo_level:
        args.component = None
    cfg = load_config(args, quiet=True)
    if pin_problem(cfg):
        die(pin_problem(cfg))
    comp = (cfg.get("component") or {}).get("name")
    if (comp or repo_level) and run_count > 1:
        die("several runs per component aren't supported yet: grade each component once (--run 1/1)")
    pdir = project_dir_from_args(args)
    commit = args.commit.strip()
    now = utc_now()
    if args.out:
        out = Path(args.out)
    elif pdir:
        folder = pdir / "reports" / f"{now[:10]}-{commit[:7]}"
        out = folder / (f"components/{slug(comp)}.json" if comp else "report.json" if run_count == 1 else f"runs/run-{run_index}.json")
    else:
        die("give --project NAME (or --project-dir), or --out FILE")
    if out.exists() and not args.force:
        die(f"{out} exists (use --force to start it again)")
    catalog = RUBRIC.catalog
    previous = {}
    if pdir:
        rel_name = f"components/{slug(comp)}.json" if comp else "report.json"
        older = [f for f in report_folders(pdir) if (f / rel_name).exists() and (f / rel_name).resolve() != out.resolve()]
        if older:
            previous = benchmarks_by_id(load_json(older[-1] / rel_name))
    project = (cfg.get("project") or {}).get("name") or (pdir.name if pdir else None)
    report = {
        "schema_version": REPORT_FORMAT, "suite_version": catalog["suite_version"], "mode": args.mode,
        "run": {"project": project, "commit": commit, "base_commit": args.base_commit, "started": started_arg(args, now), "date": now,
                "grader": args.grader, "model": args.model, "session": args.session, "work_order": args.work_order,
                "run_index": run_index, "run_count": run_count, "suite_source": args.suite_source},
        "component": ({"name": cfg["component"]["name"], "path": cfg["component"].get("path"), "weight": cfg["component"].get("weight", 1)}
                      if cfg.get("component") else None),
        "config": {"hash": cfg["hash"], "preset": cfg["preset"], "source": " + ".join(cfg["sources"][1:]) or None,
                   "component": (cfg.get("component") or {}).get("name"), "scoring_version": cfg["suite_version"]},
        "commands_run": [], "scope_examined": "", "metrics": {}, "feature_inventory": [], "gap_register": [],
        "findings": [], "benchmarks": [blank_benchmark(c, cfg) for c in catalog["benchmarks"]], "integrity_flags": [],
        "holdout": {"run": False, "checks_run": None, "pass_rate": None, "private_details": None},
        "rollup": None, "top_priorities": [], "limitations": [],
    }
    for b in report["benchmarks"]:
        b["previous_score"] = (previous.get(b["id"]) or {}).get("score")
    if repo_level or comp:   # grader Part 9: the repo report grades what the whole repo shares; components grade the rest
        if repo_level:
            report["component"] = {"name": "repo", "path": "."}
        for b in report["benchmarks"]:
            shared = b["id"] in REPO_LEVEL
            if shared != bool(repo_level):
                b.update(applicability="not_applicable", score=None, confidence=None,
                         applicability_reason="graded per component" if repo_level else "graded at repo level")
    normalize_report(report, cfg, catalog)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    emit(args, {"report": str(out), "commit": commit, "config_hash": cfg["hash"], "previous": bool(previous)},
         f"wrote {out}\nnext: add findings and scores with `gradekit report finding add` / `report score`, then `gradekit report check {out}`")
    return 0


def load_for_edit(args) -> tuple[dict, dict]:
    report = load_report(args.report)
    cfg = authoring_config(args, report)
    return report, cfg


def save_edit(args, report: dict, cfg: dict) -> None:
    normalize_report(report, cfg)
    if report.get("rollup"):   # stored by `report check --write`; any edit after it would leave it stale
        report.pop("rollup")
        say_later("note: the stored rollup was dropped, because the report changed; `report check --write` stores it again")
    (report.get("run") or {}).pop("citations_checked", None)   # likewise: the quotes may have changed
    write_json(args.report, report)


def cmd_report_cite(args) -> int:
    ev = cite(args.spec, repo_reader(args.repo), args.note)
    emit(args, ev, json.dumps(ev, indent=None if args.compact else 2, ensure_ascii=False))
    return 0


def cmd_finding_add(args) -> int:
    report, cfg = load_for_edit(args)
    bench = benchmark_or_die(report, args.benchmark)
    bid = bench["id"]
    if args.id:
        if not re.fullmatch(rf"{bid}-\d{{3,}}", args.id):
            die(f"--id must look like {bid}-007")
        if any(f.get("id") == args.id for f in report["findings"]):
            die(f"{args.id} is already in this report; use `report finding update`")
        fid = args.id
    else:
        fid = next_id(bid, "-", known_ids(args.report, report, rf"\b{bid}-\d{{3,}}\b"))
    run = report.get("run") or {}
    if args.status == "accepted":
        die(f"add it with its real status, then accept it with {ACCEPT_HINT}")
    if args.status == "withdrawn":
        die(f"a finding is withdrawn by answering a person's dispute: {WITHDRAW_HINT}")
    seen = args.first_seen or ((run.get("base_commit") or run.get("commit")) if args.status == "noticed" else run.get("commit"))
    f = {"id": fid, "benchmark_id": bid, "title": args.title, "severity": args.severity, "status": args.status,
         "first_seen_commit": seen,
         "evidence": evidence_from_args(args, required=True, report=report), "disposition": None, "disposition_concern": None}
    if args.paths:
        f["paths"] = [repo_relative(p) for p in args.paths]
    if args.sensitive:
        f["sensitive"] = True
    if args.cap:
        f["cap"] = finding_cap_or_die(args.cap, bid, report, args.severity)
    report["findings"].append(f)
    save_edit(args, report, cfg)
    emit(args, {"id": fid, "finding": f}, f"added {fid} ({args.severity}): {args.title}")
    return 0


def finding_cap_or_die(cap: str, bid: str, report: dict, severity: str | None = None) -> str:
    caps = catalog_caps()
    if cap not in caps or caps[cap]["benchmark"] != bid:
        mine = "; ".join(f"{k}: {c['when']} → max {c['max']}" for k, c in caps.items() if c["benchmark"] == bid)
        die(f"{cap}: not one of {bid}'s caps ({mine or 'it has none'})")
    if severity is not None and severity not in CAP_SEVERITIES:
        die(f"{cap}: a rubric cap holds only on a finding that's major or worse. If this {severity} finding really triggers it, "
            "its consequence is bigger than minor; otherwise leave the cap off")
    return cap


def cmd_finding_update(args) -> int:
    report, cfg = load_for_edit(args)
    f = finding_or_die(report, args.id)
    if args.status == "accepted" and f.get("status") != "accepted":
        die(f"accept a finding with {ACCEPT_HINT}")
    if args.status == "withdrawn" and f.get("status") != "withdrawn":
        die(f"a finding is withdrawn by answering a person's dispute: {WITHDRAW_HINT}")
    if args.status not in (None, "accepted") and f.get("status") == "accepted":
        f.pop("disposition_ref", None)   # no longer accepted: the people's entry no longer applies to it
        f["disposition"] = None
    for key in ("title", "severity", "status"):
        if getattr(args, key) is not None:
            f[key] = getattr(args, key)
    if args.disposition_concern is not None:
        f["disposition_concern"] = args.disposition_concern or None
    if args.sensitive is not None:
        if args.sensitive:
            f["sensitive"] = True
        else:
            f.pop("sensitive", None)
    if args.paths:
        f["paths"] = list(dict.fromkeys(list(f.get("paths", []) or []) + [repo_relative(p) for p in args.paths]))
    if args.cap is not None:
        if args.cap:
            f["cap"] = finding_cap_or_die(args.cap, f.get("benchmark_id"), report, f.get("severity"))
        else:
            f.pop("cap", None)
    new_ev = evidence_from_args(args, report=report)
    if args.replace_evidence:
        if not new_ev:
            die("--replace-evidence needs new evidence")
        f["evidence"] = new_ev
    else:
        f["evidence"] = f.get("evidence", []) + new_ev
    save_edit(args, report, cfg)
    emit(args, {"id": f["id"], "finding": f}, f"updated {f['id']}")
    return 0


def cmd_report_score(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    if args.applicability:
        b["applicability"] = args.applicability
    if args.reason is not None:
        b["applicability_reason"] = args.reason or None
    if b["applicability"] in ("limited", "not_applicable") and not (b.get("applicability_reason") or "").strip():
        die(f"{b['id']} is {b['applicability']}: give --reason (based on the project's purpose, not its quality)")
    if b["applicability"] == "not_applicable" and gate_not_applicable(b["id"], cfg, report):
        die(gate_not_applicable(b["id"], cfg, report))
    if b["applicability"] == "not_applicable":
        if args.score is not None:
            die("a not_applicable benchmark has no score")
        b["score"], b["confidence"] = None, None
    else:
        if args.score is not None:
            b["score"] = args.score
        if args.confidence:
            b["confidence"] = args.confidence
        if (b.get("score") is None or b.get("confidence") is None) and not (args.applicability and args.score is None and not args.confidence):
            die(f"{b['id']} needs --score and --confidence")
    if args.score is not None or args.applicability:
        b["carried_forward"] = False
    if args.why is not None:
        b["change_explanation"] = args.why or None
    if args.rationale is not None:
        b["rationale"] = args.rationale or None
    if args.weight_note is not None:
        b["weight_note"] = args.weight_note or None
    caps = catalog_caps()
    for v in args.cap or []:
        c = resolve_cap(v, b["id"], caps)
        if c is None or (c["id"] and c["benchmark"] != b["id"]):
            die(f"{v}: not one of {b['id']}'s caps ({', '.join(k for k, c in caps.items() if c['benchmark'] == b['id']) or 'it has none'})")
    for key, vals in (("caps_applied", args.cap), ("gaming_flags", args.gaming_flag)):
        for v in vals or []:
            if v not in b[key]:
                b[key].append(v)
    too_high = over_limit(b, score_limits(report, cfg).get(b["id"]))
    if too_high:
        die(f"{b['id']}: {b['score']} is above its limit of {min(w['max'] for w in too_high)}: "
            + "; ".join(f"{w['why']} → max {w['max']}" for w in too_high))
    save_edit(args, report, cfg)
    if b["applicability"] == "not_applicable":
        state = "not applicable"
    elif b.get("score") is None:
        state = f"{b['applicability']}, not scored yet (`report score REPORT {b['id']} --score N --confidence C`)"
    else:
        state = f"{b['score']} ({b['confidence']} confidence)" + ("" if b["applicability"] == "full" else f", {b['applicability']}")
    msg = f"{b['id']} {b['name']}: " + state
    if b.get("target") is not None:
        msg += f", target {b['target']}"
    pending = [w for w in (score_limits(report, cfg).get(b["id"]) or {"why": []})["why"]
               if w["kind"] in ("strengths", "enforcement") and isinstance(b.get("score"), int) and b["score"] > w["max"]]
    for w in pending:   # checked at `report check`, since graders add strengths after scoring
        msg += f"\nnote: {b['id']} needs {'a strength' if w['kind'] == 'strengths' else 'enforcement'} for a score above {w['max']} ({w['why']})"
    emit(args, {"benchmark": b}, msg)
    return 0


def cmd_report_strength(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    b["strengths"].append({"note": args.text, "evidence": evidence_from_args(args, required=True, report=report)})
    save_edit(args, report, cfg)
    emit(args, {"benchmark_id": b["id"], "strengths": len(b["strengths"])}, f"{b['id']}: {len(b['strengths'])} strength(s)")
    return 0


def cmd_report_enforcement(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    b["enforcement"].append({"note": args.text, "evidence": evidence_from_args(args, required=True, report=report)})
    save_edit(args, report, cfg)
    emit(args, {"benchmark_id": b["id"], "enforcement": len(b["enforcement"])}, f"{b['id']}: {len(b['enforcement'])} enforcement item(s)")
    return 0


def cmd_report_action(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    findings = {f.get("id") for f in report["findings"]} | {g.get("id") for g in report["gap_register"]}
    for fid in args.resolves:
        if fid not in findings:
            die(f"--resolves {fid}: no such finding or gap in this report")
    aid = next_id(f"{b['id']}-act", "-", {a.get("id", "") for x in report["benchmarks"] for a in x["path_to_target"]}, width=1)
    act = {"id": aid, "action": args.action, "resolves": args.resolves, "expected_new_score": args.new_score,
           "effort": args.effort, "requires_human_decision": bool(args.decision), "decision_question": args.decision}
    if args.optional:
        act["optional"] = True
    if args.why_first:
        act["why_first"] = args.why_first
    b["path_to_target"].append(act)
    save_edit(args, report, cfg)
    emit(args, {"id": aid, "action": act}, f"added {aid}" + (" (needs a human decision)" if args.decision else ""))
    return 0


def cmd_report_gap(args) -> int:
    report, cfg = load_for_edit(args)
    for bid in args.benchmarks:
        benchmark_or_die(report, bid)
    gid = next_id("GAP", "-", known_ids(args.report, report, r"\bGAP-\d{3,}\b"))
    gap = {"id": gid, "gap": args.gap, "severity": args.severity, "necessity": args.necessity, "status": args.status,
           "rationale": args.rationale or "", "benchmark_ids": [b.upper() for b in args.benchmarks]}
    report["gap_register"].append(gap)
    save_edit(args, report, cfg)
    emit(args, {"id": gid, "gap": gap}, f"added {gid}: {args.gap}")
    return 0


def earlier_report_ids(report_path) -> set[str]:
    """Finding and gap IDs in the project's other report folders: IDs that must stay, because carry and diff track them."""
    ids: set[str] = set()
    pdir = project_dir_for_report(report_path)
    here = Path(report_path).resolve().parent
    for folder in report_folders(pdir) if pdir else []:
        if folder.resolve() == here:
            continue
        for f in [folder / "report.json", *sorted((folder / "runs").glob("*.json"))]:
            if f.exists():
                try:
                    ids |= recorded_ids(json.loads(f.read_text(encoding="utf-8", errors="replace")))
                except json.JSONDecodeError:
                    continue
    return ids


EDIT_REF_HELP = ("what to change: a strength or enforcement item as BENCHMARK/strength/N or BENCHMARK/enforcement/N "
                 "(N as `report show` numbers them), an action ID (A3-act-2), a gap ID (GAP-003), command/N, feature/N, or, for "
                 "remove, a finding ID")


def edit_target(report: dict, ref: str) -> dict:
    """{kind, items, index, item, benchmark} for a reference to one record of a report."""
    m = re.fullmatch(r"([A-Za-z]\d+)/(strength|strengths|enforcement)/(\d+)", ref.strip())
    if m:
        b = benchmark_or_die(report, m.group(1))
        kind = "enforcement" if m.group(2) == "enforcement" else "strength"
        items = b["enforcement"] if kind == "enforcement" else b["strengths"]
        n = int(m.group(3))
        if not 1 <= n <= len(items):
            die(f"{b['id']} has {len(items)} {kind} item(s); `report show $R {b['id']}` lists them")
        return {"kind": kind, "items": items, "index": n - 1, "item": items[n - 1], "benchmark": b}
    m = re.fullmatch(r"commands?/(\d+)", ref.strip())
    if m:
        items, n = report["commands_run"], int(m.group(1))
        if not 1 <= n <= len(items):
            die(f"the report has {len(items)} command(s); `report show $R commands` lists them")
        return {"kind": "command", "items": items, "index": n - 1, "item": items[n - 1], "benchmark": None}
    m = re.fullmatch(r"features?/(\d+)", ref.strip())
    if m:
        items, n = report["feature_inventory"], int(m.group(1))
        if not 1 <= n <= len(items):
            die(f"the report has {len(items)} feature(s); `report show $R features` lists them")
        return {"kind": "feature", "items": items, "index": n - 1, "item": items[n - 1], "benchmark": None}
    for b in report["benchmarks"]:
        for i, a in enumerate(b["path_to_target"]):
            if a.get("id") == ref:
                return {"kind": "action", "items": b["path_to_target"], "index": i, "item": a, "benchmark": b}
    for kind, key in (("gap", "gap_register"), ("finding", "findings")):
        for i, x in enumerate(report[key]):
            if x.get("id") == ref:
                return {"kind": kind, "items": report[key], "index": i, "item": x, "benchmark": None}
    die(f"nothing called {ref!r} in this report. {EDIT_REF_HELP[0].upper() + EDIT_REF_HELP[1:]}.")


def show_lines(report: dict, what: str | None) -> list[str]:
    """Numbered records, as `report update` and `report remove` address them."""
    def ev_text(evs):
        return "; ".join(evidence_line(e) for e in evs or [])
    if what and what.lower() in ("feature", "features"):
        return [f"feature/{i} {f.get('feature')} ({f.get('status')}){': ' + ev_text(f.get('evidence')) if f.get('evidence') else ''}"
                for i, f in enumerate(report["feature_inventory"], 1)] or ["no features yet"]
    if what and what.lower() in ("metric", "metrics"):
        notes = report.get("metrics_notes") or {}
        keys = list(dict.fromkeys(list((report.get("metrics") or {}).keys()) + list(notes.keys())))
        return [f"metrics.{k} = {json.dumps((report.get('metrics') or {}).get(k))}" + (f"  (metrics_notes.{k}: {notes[k]})" if k in notes else "")
                for k in keys] or ["no metrics yet: `report set REPORT metrics.KEY VALUE` (prompts/grader.md lists the keys)"]
    if what and what.lower() in ("command", "commands"):
        return [f"{i}. `{c.get('command')}` → {c.get('exit_code')}: {c.get('result_summary')}" + (f" (in {c['workdir']})" if c.get("workdir") else "")
                for i, c in enumerate(report.get("commands_run") or [], 1)] or ["no commands recorded yet"]
    if what and what.lower() in ("gap", "gaps"):
        return [f"{g['id']} {g.get('severity')} {g.get('necessity')} ({g.get('status')}): {g.get('gap')}"
                for g in report["gap_register"]] or ["no gaps yet"]
    benches = [benchmark_or_die(report, what)] if what else report["benchmarks"]
    out = []
    for b in benches:
        if not what and not (b["strengths"] or b["enforcement"] or b["path_to_target"] or b["finding_ids"]):
            continue
        score = b.get("score") if b.get("applicability") != "not_applicable" else "n/a"
        out.append(f"{b['id']} {b.get('name', '')} · score {score if score is not None else '–'}")
        out += [f"  {b['id']}/strength/{i} {s.get('note')} ({ev_text(s.get('evidence'))})" for i, s in enumerate(b["strengths"], 1)]
        out += [f"  {b['id']}/enforcement/{i} {e['note'] or '(no text)'} ({ev_text(e['evidence'])})"
                for i, e in enumerate(enforcement_items(b), 1)]
        fmap = {f.get("id"): f for f in report["findings"]}
        out += [f"  {fid} {fmap.get(fid, {}).get('severity')} {fmap.get(fid, {}).get('status')}: {fmap.get(fid, {}).get('title')}"
                for fid in b["finding_ids"]]
        for a in b["path_to_target"]:
            extra = (" optional" if a.get("optional") else "") + (f" resolves {', '.join(a['resolves'])}" if a.get("resolves") else "")
            out.append(f"  {a['id']} → {a.get('expected_new_score')} (effort {a.get('effort')}{extra}): {a.get('action')}")
    if not what:
        out.append("(also: `report show REPORT features|gaps|metrics|commands`)")
    return out


def cmd_report_show(args) -> int:
    report = load_report(args.report)
    lines = show_lines(report, args.what)
    emit(args, {"lines": lines}, "\n".join(lines))
    return 0


def cmd_report_update(args) -> int:
    report, cfg = load_for_edit(args)
    t = edit_target(report, args.ref)
    item, kind, changed = t["item"], t["kind"], []
    allowed = {"strength": {"text", "evidence"}, "enforcement": {"text", "evidence"},
               "command": {"command_text", "exit_code", "summary", "workdir", "env"},
               "action": {"action", "new_score", "effort", "resolves", "decision", "optional", "why_first"},
               "gap": {"gap", "severity", "necessity", "status", "rationale", "benchmarks"}}
    if kind not in allowed:
        die(f"{args.ref} is a {kind}: " + {"finding": "use `report finding update`",
                                             "feature": "give the feature again with `report feature`",
                                             }[kind])
    new_ev = evidence_from_args(args, report=report)
    given = {k for k in ("text", "action", "new_score", "effort", "resolves", "decision", "optional", "why_first", "gap", "severity",
                         "necessity", "status", "rationale", "benchmarks", "command_text", "exit_code", "summary", "workdir", "env")
             if getattr(args, k, None) is not None}
    if new_ev:
        given.add("evidence")
    if not given:
        die("nothing to change: give the new values (see `report update --help`)")
    wrong = given - allowed[kind]
    if wrong:
        die(f"{args.ref} is a{'n' if kind[0] in 'aeiou' else ''} {kind}; it has no {', '.join('--' + w.replace('_', '-') for w in sorted(wrong))}")
    if kind in ("strength", "enforcement"):
        if kind == "enforcement" and "type" in item:   # a format-4 item: wrap it first
            item = t["items"][t["index"]] = enforcement_items({"enforcement": [item]})[0]
        if args.text is not None:
            item["note"] = args.text
            changed.append("text")
        if new_ev:
            item["evidence"] = new_ev if args.replace_evidence else item.get("evidence", []) + new_ev
            changed.append("evidence replaced" if args.replace_evidence else "evidence added")
    elif kind == "command":
        old = item.get("command")
        for key, field in (("command_text", "command"), ("exit_code", "exit_code"), ("summary", "result_summary"), ("workdir", "workdir"), ("env", "env")):
            if getattr(args, key, None) is not None:
                if getattr(args, key) == "" and field in ("workdir", "env"):
                    item.pop(field, None)
                else:
                    item[field] = getattr(args, key)
        moved = 0
        if args.command_text is not None and args.command_text != old:   # evidence that quotes it follows the new text
            for _, ev, _ in iter_evidence(report):
                if ev.get("type") == "command" and ev.get("command") == old:
                    ev["command"] = args.command_text
                    moved += 1
        changed = sorted(given) + ([f"{plural(moved, 'evidence item')} now quote the new text"] if moved else [])
    elif kind == "action":
        if args.resolves is not None:
            ids = {f.get("id") for f in report["findings"]} | {g.get("id") for g in report["gap_register"]}
            for fid in args.resolves:
                if fid not in ids:
                    die(f"--resolves {fid}: no such finding or gap in this report")
            item["resolves"] = args.resolves
        for key, field in (("action", "action"), ("new_score", "expected_new_score"), ("effort", "effort")):
            if getattr(args, key) is not None:
                item[field] = getattr(args, key)
        if args.decision is not None:
            item["requires_human_decision"] = bool(args.decision)
            item["decision_question"] = args.decision or None
        if args.optional is not None:
            if args.optional:
                item["optional"] = True
            else:
                item.pop("optional", None)
        if args.why_first is not None:
            if args.why_first:
                item["why_first"] = args.why_first
            else:
                item.pop("why_first", None)
        changed = sorted(given)
        if args.optional is not None:
            changed = [c if c != "optional" else ("optional" if args.optional else "no longer optional") for c in changed]
    else:
        for key in ("gap", "severity", "necessity", "status", "rationale"):
            if getattr(args, key) is not None:
                item[key] = getattr(args, key)
        if args.benchmarks is not None:
            for bid in args.benchmarks:
                benchmark_or_die(report, bid)
            item["benchmark_ids"] = [b.upper() for b in args.benchmarks]
        changed = sorted(given)
    save_edit(args, report, cfg)
    emit(args, {"ref": args.ref, "kind": kind, "changed": changed, "item": item}, f"updated {args.ref}: {', '.join(changed)}")
    return 0


def cmd_report_remove(args) -> int:
    report, cfg = load_for_edit(args)
    t = edit_target(report, args.ref)
    kind, item, notes = t["kind"], t["item"], []
    if kind in ("finding", "gap") and item.get("id") in earlier_report_ids(args.report):
        die(f"{item['id']} is in an earlier report, so its ID stays: " +
            ("update it instead (`report finding update`: --status fixed if it's gone, or new evidence)" if kind == "finding"
             else f"update it instead (`report update $R {item['id']} --status …`)"))
    del t["items"][t["index"]]
    if kind in ("finding", "gap"):
        for b in report["benchmarks"]:
            if item["id"] in b["finding_ids"]:
                b["finding_ids"].remove(item["id"])
            for a in b["path_to_target"]:
                if item["id"] in a.get("resolves", []):
                    a["resolves"] = [x for x in a["resolves"] if x != item["id"]]
                    notes.append(f"{a['id']} no longer resolves it")
    save_edit(args, report, cfg)
    later = " (later items are renumbered: `report show` lists them)" if kind in ("strength", "enforcement", "feature", "command") else ""
    emit(args, {"ref": args.ref, "kind": kind, "removed": item, "notes": notes},
         f"removed {args.ref}{later}" + "".join(f"\n  note: {n}" for n in notes))
    return 0


def cmd_report_feature(args) -> int:
    report, cfg = load_for_edit(args)
    evidence = evidence_from_args(args, report=report)
    same = [f for f in report["feature_inventory"] if str(f.get("feature", "")).strip().lower() == args.feature.strip().lower()]
    if same:   # the same feature again updates it, e.g. when `carry` says its citation needs new evidence
        feat = same[0]
        feat.update({"source": args.source or feat.get("source"), "status": args.status})
        if evidence:
            feat["evidence"] = evidence
        save_edit(args, report, cfg)
        emit(args, {"feature": feat, "updated": True},
             f"updated feature '{feat['feature']}' ({args.status}{', new evidence' if evidence else ''})")
        return 0
    feat = {"feature": args.feature, "source": args.source, "status": args.status, "evidence": evidence}
    report["feature_inventory"].append(feat)
    save_edit(args, report, cfg)
    emit(args, {"feature": feat}, f"added feature '{args.feature}' ({args.status})")
    return 0


def cmd_report_flag(args) -> int:
    report, cfg = load_for_edit(args)
    flag = {"description": args.description, "evidence": evidence_from_args(args, required=True, report=report)}
    report["integrity_flags"].append(flag)
    save_edit(args, report, cfg)
    emit(args, {"integrity_flag": flag}, "added integrity flag (caps maturity at L1 for this run)")
    return 0


OUTPUT_LINES_MAX = 5000


def output_line_key(line: str) -> str:
    return hashlib.sha256(" ".join(line.split()).encode("utf-8", "replace")).hexdigest()[:10]


def output_fingerprint(text: str) -> dict:
    """What `report ran --output` keeps of a command's output: one short hash per distinct line (whitespace evened
    out), so `report check` can tell whether an excerpt was copied from it, without storing the output itself."""
    lines = [l for l in text.splitlines() if l.strip()]
    keys = sorted({output_line_key(l) for l in lines})
    if len(keys) > OUTPUT_LINES_MAX:
        return {"lines": len(lines), "too_long": True}
    return {"lines": len(lines), "line_hashes": keys}


def excerpt_mismatches(excerpt: str, fp: dict) -> list[str]:
    """Excerpt lines that aren't lines of the recorded output (elisions like '...' are fine)."""
    if not fp or fp.get("too_long") or not fp.get("line_hashes"):
        return []
    known = set(fp["line_hashes"])
    return [l.strip() for l in excerpt.splitlines()
            if l.strip() and l.strip() not in ("...", "…", "[...]", "(no output)") and output_line_key(l) not in known]


def cmd_report_ran(args) -> int:
    report, cfg = load_for_edit(args)
    entry = {"command": args.command_text, "exit_code": args.exit_code, "result_summary": args.summary}
    if args.workdir:
        entry["workdir"] = args.workdir
    if args.env:
        entry["env"] = args.env
    if args.output:
        entry["output"] = output_fingerprint(read_text_arg(args.output if args.output == "-" else "@" + args.output) or "")
    report["commands_run"].append(entry)
    save_edit(args, report, cfg)
    n = len(report["commands_run"])
    emit(args, {"command": entry, "n": n}, f"recorded `{args.command_text}` as command {n} (cite its output with `--command @{n}`)"
         + (f"; kept a fingerprint of its {entry['output']['lines']} output lines" if args.output else ""))
    return 0


SETTABLE = ("summary", "scope_examined", "project_context_inferred", "metrics", "metrics_notes", "limitations", "holdout",
            "top_priorities", "run")


def cmd_report_set(args) -> int:
    report, cfg = load_for_edit(args)
    parts = args.key.split(".")
    if parts[0] not in SETTABLE:
        die(f"`report set` covers {', '.join(SETTABLE)}; use the other report commands for findings, scores and evidence")
    if len(parts) == 2 and parts[1].isdigit() and isinstance(report.get(parts[0]), list):   # one item of a list: limitations.2
        items, n = report[parts[0]], int(parts[1])
        if not 1 <= n <= len(items):
            die(f"{parts[0]} has {plural(len(items), 'item')}; `report show REPORT {parts[0]}` numbers them")
        if args.remove:
            gone = items.pop(n - 1)
            save_edit(args, report, cfg)
            emit(args, {"key": args.key, "removed": gone}, f"removed {args.key}: {str(gone)[:70]}")
            return 0
        if args.value is None:
            die(f"give the new text for {args.key}, or --remove")
        raw = read_text_arg(args.value)
        try:
            items[n - 1] = json.loads(raw) if parts[0] != "limitations" else raw
        except json.JSONDecodeError:
            items[n - 1] = raw
        save_edit(args, report, cfg)
        emit(args, {"key": args.key, "value": items[n - 1]}, f"set {args.key}")
        return 0
    if args.remove:
        die(f"--remove takes one item of a list, e.g. `report set REPORT {parts[0]}.2 --remove`")
    if args.value is None:
        die(f"give a value for {args.key}")
    raw = read_text_arg(args.value)
    try:
        value = json.loads(raw, parse_float=_finite_number, parse_constant=_not_json)
    except ValueError as exc:
        if "JSON" in str(exc) and not isinstance(exc, json.JSONDecodeError):
            die(f"{args.key}: {exc}")
        value = raw
    node = report
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            die(f"{args.key}: {p} is not an object")
    last = parts[-1]
    if parts[0] == "metrics" and len(parts) == 2 and not (value is None or isinstance(value, (bool, int, float))):
        die(f"{args.key}: a metric is a number, true/false or null (got {args.value!r}); put words in metrics_notes.{last}")
    if args.append:
        node.setdefault(last, [])
        if not isinstance(node[last], list):
            die(f"{args.key} is not a list")
        node[last].append(value)
    else:
        if isinstance(node.get(last), list) and not isinstance(value, list):
            die(f"{args.key} is a list: add to it with --append, change one item with `report set REPORT {args.key}.N TEXT` "
                f"(or `--remove` it), or give the whole list as JSON ('[\"…\"]')")
        node[last] = value
    save_edit(args, report, cfg)
    emit(args, {"key": args.key, "value": node[last]}, f"set {args.key}")
    return 0


def report_todo(report: dict, pdir: Path | None = None) -> list[str]:
    """What a grader still has to do before the report is finished."""
    todo = []
    for b in report.get("benchmarks", []):
        if b.get("applicability") != "not_applicable" and (b.get("score") is None or b.get("confidence") is None):
            todo.append(f"{b['id']} {b['name']}: score it (`report score REPORT {b['id']} --score N --confidence C`), "
                        f"or mark it not applicable with a reason")
    if not str(report.get("scope_examined") or "").strip():
        todo.append("say what you examined: `report set REPORT scope_examined \"...\"`")
    if not report.get("commands_run"):
        todo.append("record the commands you ran: `report ran REPORT --command CMD --summary TEXT`")
    if not report.get("limitations"):
        todo.append("list limitations (or 'None'): `report set REPORT limitations \"...\" --append`")
    if not str(report.get("summary") or "").strip():
        todo.append("write the summary: `report set REPORT summary \"...\"`")
    for b in report.get("benchmarks", []):
        tv = b.get("target")
        if (isinstance(b.get("score"), int) and isinstance(tv, int) and b["score"] < tv and not b.get("carried_forward")
                and not any(not a.get("optional") for a in b.get("path_to_target", []))):
            todo.append(f"{b['id']}: {b['score']} is below its target {tv}; plan the path there "
                        f"(`report action REPORT {b['id']} --action \"...\" --new-score N --effort S|M|L`)")
    if not str((report.get("run") or {}).get("model") or "").strip():
        todo.append("record the model that graded: `report set REPORT run.model NAME` (or `report new --model`)")
    if pdir is not None:
        ids = {f.get("id") for f in report.get("findings", [])}
        for d in open_disputes(pdir, report):
            if d.get("finding_id") in ids:
                todo.append(f"answer the dispute on {d['finding_id']} ({d.get('by')}: {d.get('reason')}): "
                            f"`report finding answer REPORT {d['finding_id']} --uphold|--withdraw --note \"why\"`")
    return todo


def unrecorded_commands(report: dict) -> list[str]:
    """Command evidence whose command isn't in commands_run (the excerpt can't be traced to a recorded run), and
    excerpts with lines that aren't in the output recorded with `report ran --output`."""
    ran: dict = {}
    for c in report.get("commands_run") or []:
        ran.setdefault(norm(str(c.get("command") or "")), c.get("output"))
    out, seen = [], set()
    def walk(where, evs):
        for ev in evs or []:
            if ev.get("type") != "command":
                continue
            key = norm(str(ev.get("command") or ""))
            if key not in ran:
                if (where, key) not in seen:
                    seen.add((where, key))
                    out.append(f"{where}: its excerpt is from `{str(ev.get('command'))[:60]}`, which isn't in commands_run: record it with "
                               "`report ran`, then cite it as `--command @N`")
                continue
            bad = excerpt_mismatches(str(ev.get("excerpt") or ""), ran[key] or {})
            if bad:
                out.append(f"{where}: {plural(len(bad), 'line')} of its excerpt from `{str(ev.get('command'))[:40]}` "
                           f"{'is' if len(bad) == 1 else 'are'}n't in that command's recorded output (e.g. {bad[0][:60]!r}): "
                           "copy excerpts from the output, never from your own notes")
    for f in report.get("findings") or []:
        walk(f.get("id"), f.get("evidence"))
    for b in report.get("benchmarks") or []:
        for kind in ("strengths", "enforcement"):
            for i, item in enumerate(b.get(kind) or [], 1):
                walk(f"{b.get('id')} {kind[:-1] if kind == 'strengths' else kind} {i}", item.get("evidence"))
    return out


def cmd_report_check(args) -> int:
    report, cfg = load_for_edit(args)
    normalize_report(report, cfg)
    errors, warnings = validate_report(report, cfg, RUBRIC.catalog)
    pdir_ = project_dir_for_report(args.report) or project_dir_from_args(args)
    note = work_order_note(pdir_, report)
    if note:
        warnings.append(note)
    warnings += unrecorded_commands(report)
    todo = report_todo(report, pdir_)
    todo_ids = {t.split(" ", 1)[0] for t in todo}
    # A blank benchmark fails several rules at once; the to-do list says it once.
    errors = [e for e in errors if not any(e.startswith(f"{bid}: applicable benchmark") for bid in todo_ids)]
    evidence = None
    if args.repo:
        evidence = verify_evidence(report, repo_reader(args.repo), args.tolerance)
        errors += [f"citation: {f}" for f in evidence["failures"]]
    roll = None
    if not todo:
        roll = compute_rollup(report, cfg)
        errors += [f"weight: {w}" for w in roll["weight_issues"]]
    stored = report.get("rollup") or {}
    if stored and roll is not None and (stored.get("overall_score"), (stored.get("maturity") or {}).get("current_level")) != (
            roll["overall_score"], roll["maturity"]["current_level"]):
        warnings.append(f"the stored rollup ({stored.get('overall_score')}, {(stored.get('maturity') or {}).get('current_level')}) "
                        f"doesn't match the scores ({roll['overall_score']}, {roll['maturity']['current_level']}); "
                        "`report check --write` stores the current one, and `deliver` always does")
    wrote = None
    if args.write:
        if roll is not None:
            apply_rollup(report, cfg)
            if evidence is not None:
                record_citations_checked(report, evidence)
            report["run"]["date"] = utc_now()
            usage = report["run"].setdefault("usage", {})
            if usage.get("minutes") is None and report["run"].get("started"):
                usage["minutes"] = minutes_between(report["run"]["started"], report["run"]["date"])
            wrote = (f"wrote {args.report}: the rollup (overall {roll['overall_score']}, {roll['maturity']['current_level']}) and the finish "
                     f"time {report['run']['date']}" + (f", {report['run']['usage']['minutes']:g} min" if (report["run"].get("usage") or {}).get("minutes") is not None else ""))
        else:
            wrote = f"wrote {args.report} (tidied); the rollup isn't stored until nothing is left to do"
        write_json(args.report, report)
    status = "errors" if errors else "incomplete" if todo else "ready"
    result = {"status": status, "errors": errors, "warnings": cfg.get("warnings", []) + warnings, "todo": todo,
              "evidence": evidence, "overall_score": roll and roll["overall_score"],
              "level": roll and roll["maturity"]["current_level"]}
    lines = [f"ERROR:   {e}" for e in errors] + [f"warning: {w}" for w in result["warnings"]] + [f"todo:    {t}" for t in todo]
    if evidence:
        lines.append(f"citations: {evidence['checked']} checked, {len(evidence['failures'])} failed")
    if roll:
        lines.append(f"overall {roll['overall_score']}, maturity {roll['maturity']['current_level']}" +
                     ("" if args.write else "  (run with --write to store the rollup and stamp the finish time)"))
    lines.append(f"\n{status}: {len(errors)} error(s), {len(result['warnings'])} warning(s), {len(todo)} to do")
    if wrote:
        lines.append(wrote)
        result["wrote"] = wrote
    emit(args, result, "\n".join(lines))
    return 1 if errors else EXIT_INCOMPLETE if todo else 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def evidence_args(q, cite_help="FILE:LINE or FILE:START-END; the quote is copied from the file (repeatable)"):
    q.add_argument("--cite", action=InOrderAppend, metavar="FILE:LINES", help=cite_help)
    q.add_argument("--repo", metavar="DIR_OR_ZIP", help="the code checkout (or a zip of it) that --cite reads")
    q.add_argument("--command", action=InOrderAppend, metavar="CMD",
                   help="evidence from a command you ran (@N: the Nth command recorded with `report ran`; repeatable)…")
    q.add_argument("--excerpt", action=InOrderAppend, metavar="TEXT",
                   help="…and the relevant part of its output, copied ('@file' or '-' for stdin); one per --command, in order")
    q.add_argument("--no-output", action=InOrderTrue, help="…or: it printed nothing (say what happened in --note)")
    q.add_argument("--absence", action=InOrderAppend, metavar="WHAT", help="evidence that something is missing: what you looked for (repeatable)…")
    q.add_argument("--method", action=InOrderAppend, metavar="HOW", help="…and how you searched; one per --absence, in order")
    q.add_argument("--note", action=InOrderAppend, help="a note on the evidence given just before it (repeatable); "
                   "given once, it goes on every evidence item of this command")


def report_arg(q):
    q.add_argument("report", help="the report JSON being written")
    with_config(q)


def provenance(p):
    p.add_argument("--model", help="the model grading, e.g. claude-opus-5-5 (a finished report needs it)")
    p.add_argument("--session", help="the agent session's ID or URL, so reviewers can see who graded")
    p.add_argument("--work-order", help="the work order this run answers (its ID)")
    p.add_argument("--started", metavar="UTC_TIME", help="when the run began, if before this command (e.g. "
                   "the `date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ` you noted before preflight); usage.minutes counts from it")


def add_report_new(rsub):
    q = rsub.add_parser("new", help="start a report: every benchmark with its weight and target filled in")
    with_config(q)
    q.add_argument("--commit", required=True, help="the commit being graded")
    q.add_argument("--base-commit", help="pr mode: the pull request's base commit")
    q.add_argument("--mode", choices=["full", "pr"], default="full")
    q.add_argument("--grader", default="unknown", help="the agent or person grading, e.g. Claude Code")
    provenance(q)
    q.add_argument("--run", metavar="N/COUNT", help="for several independent graders: e.g. 2/3 (writes runs/run-2.json)")
    q.add_argument("--suite-source", default="local", help="where the suite came from, e.g. the AGENT.md URL and version")
    q.add_argument("--out", metavar="FILE", help="write here instead of projects/NAME/reports/<date>-<commit>/report.json")
    q.add_argument("--force", action="store_true", help="overwrite an existing report")
    q.set_defaults(fn=cmd_report_new)


def add_report_cite(rsub):
    q = rsub.add_parser("cite", help="print an evidence object for FILE:LINES with the exact quote")
    q.add_argument("spec", metavar="FILE:LINES")
    q.add_argument("--repo", required=True, metavar="DIR_OR_ZIP")
    q.add_argument("--note")
    q.add_argument("--compact", action="store_true", help="one line")
    q.set_defaults(fn=cmd_report_cite)


def add_finding_add(fsub):
    q = fsub.add_parser("add", help="add a finding; its ID is the next free one for the benchmark")
    report_arg(q)
    q.add_argument("--benchmark", required=True, metavar="ID")
    q.add_argument("--title", required=True)
    q.add_argument("--severity", required=True, choices=SEVERITIES[::-1])
    q.add_argument("--status", default="new", choices=FINDING_STATUSES,
                   help="new (caused by the graded code), noticed (already there before, first recorded now), open, …")
    q.add_argument("--first-seen", metavar="COMMIT", help="default: the graded commit")
    q.add_argument("--id", help="reuse an ID from the previous report (default: next free ID)")
    q.add_argument("--paths", nargs="+", metavar="GLOB", help="areas the finding concerns, for zones when there's no code evidence")
    q.add_argument("--sensitive", action="store_true", help="details must not be public (security); see `redact`")
    q.add_argument("--cap", metavar="CAP_ID", help="the rubric cap this finding triggers, e.g. E1-cap-1: it holds while the finding is open")
    evidence_args(q)
    q.set_defaults(fn=cmd_finding_add)


def add_finding_update(fsub):
    q = fsub.add_parser("update", help="change a finding or add evidence to it")
    report_arg(q)
    q.add_argument("id")
    q.add_argument("--title")
    q.add_argument("--severity", choices=SEVERITIES[::-1])
    q.add_argument("--status", choices=FINDING_STATUSES)
    q.add_argument("--disposition-concern", metavar="TEXT", help="why an accepted finding should be reconsidered ('' clears it)")
    q.add_argument("--paths", nargs="+", metavar="GLOB")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--sensitive", dest="sensitive", action="store_true", default=None)
    g.add_argument("--not-sensitive", dest="sensitive", action="store_false")
    q.add_argument("--replace-evidence", action="store_true", help="replace the evidence instead of adding to it")
    q.add_argument("--cap", metavar="CAP_ID", help="the rubric cap this finding triggers ('' removes it)")
    evidence_args(q)
    q.set_defaults(fn=cmd_finding_update)


def add_report_score(rsub):
    q = rsub.add_parser("score", help="score a benchmark, or mark it limited / not applicable")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--score", type=int, choices=range(1, 11), metavar="1-10")
    q.add_argument("--confidence", choices=CONFIDENCE)
    q.add_argument("--applicability", choices=["full", "limited", "not_applicable"])
    q.add_argument("--reason", help="why it's limited or not applicable (the project's purpose, not its quality)")
    q.add_argument("--rationale", help="one line: why this score (shown in the scorecard)")
    q.add_argument("--why", help="what changed since the previous report")
    q.add_argument("--weight-note", help="if the configured weight looks wrong for this code, say why")
    q.add_argument("--cap", action="append", metavar="CAP_ID",
                   help="a rubric cap that holds for this benchmark, e.g. E1-cap-1 (repeatable). Better: put it on the finding that triggers it")
    q.add_argument("--gaming-flag", action="append", help="a gaming pattern you found (repeatable)")
    q.set_defaults(fn=cmd_report_score)


def add_report_strength(rsub):
    q = rsub.add_parser("strength", help="add a strength (positive evidence) to a benchmark")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--text", required=True, help="what is good")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_strength)


def add_report_enforcement(rsub):
    q = rsub.add_parser("enforcement", help="add evidence that a benchmark's quality is enforced (CI, lint rule, test)")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--text", required=True, help="what enforces it, e.g. 'CI runs mypy --strict on every PR'")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_enforcement)


def add_report_action(rsub):
    q = rsub.add_parser("action", help="add a step on a benchmark's path to its target")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--action", required=True, help="what to do")
    q.add_argument("--resolves", nargs="*", default=[], metavar="ID", help="finding or gap IDs it resolves")
    q.add_argument("--new-score", type=int, required=True, choices=range(1, 11), metavar="1-10", help="the benchmark's expected score once this action is done, counting this benchmark's earlier actions as done too (so a second step that takes it from 6 to 8 says 8)")
    q.add_argument("--effort", required=True, choices=["S", "M", "L"])
    q.add_argument("--decision", metavar="QUESTION", help="a yes/no question a person must answer first")
    q.add_argument("--optional", action="store_true", help="beyond the target; only done when asked")
    q.add_argument("--why-first", metavar="TEXT", help="one line for top_priorities on why it comes first (default: a line from its tier)")
    q.set_defaults(fn=cmd_report_action)


def add_report_show(rsub):
    q = rsub.add_parser("show", help="list a report's strengths, enforcement, findings and actions, numbered for update and remove")
    q.add_argument("report", help="the report JSON")
    q.add_argument("what", nargs="?", metavar="ID|features|gaps|metrics|commands",
                   help="one benchmark, or the features, gaps, metrics or commands (default: every benchmark with records)")
    q.set_defaults(fn=cmd_report_show)


def add_report_update(rsub):
    q = rsub.add_parser("update", help="change a strength, enforcement item, action or gap (findings: `report finding update`)")
    report_arg(q)
    q.add_argument("ref", metavar="REF", help=EDIT_REF_HELP.replace(", feature/N, or, for remove, a finding ID", ""))
    q.add_argument("--text", help="strength or enforcement: the new text")
    evidence_args(q)
    q.add_argument("--replace-evidence", action="store_true", help="strength or enforcement: replace its evidence instead of adding to it")
    q.add_argument("--action", help="action: what to do")
    q.add_argument("--new-score", type=int, choices=range(1, 11), metavar="1-10", help="action: see `report action --help`")
    q.add_argument("--effort", choices=["S", "M", "L"])
    q.add_argument("--resolves", nargs="*", metavar="ID", help="action: the finding or gap IDs it resolves (replaces the list)")
    q.add_argument("--decision", metavar="QUESTION", help="action: a question a person must answer first ('' for none)")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--optional", dest="optional", action="store_true", default=None, help="action: beyond the target, done only when asked")
    g.add_argument("--not-optional", dest="optional", action="store_false", help="action: needed to reach the target")
    q.add_argument("--why-first", metavar="TEXT", help="action: one line for top_priorities ('' for the default)")
    q.add_argument("--gap", help="gap: its text")
    q.add_argument("--severity", choices=SEVERITIES[::-1])
    q.add_argument("--necessity", choices=["must-have", "nice-to-have"])
    q.add_argument("--status", choices=GAP_STATUSES)
    q.add_argument("--rationale")
    q.add_argument("--benchmarks", nargs="+", metavar="ID", help="gap: the benchmarks it affects (replaces the list)")
    q.add_argument("--command-text", metavar="CMD", help="command/N: exactly what ran (evidence quoting the old text follows it)")
    q.add_argument("--exit-code", type=int, help="command/N")
    q.add_argument("--summary", help="command/N: what it showed")
    q.add_argument("--workdir", metavar="DIR", help="command/N ('' to clear)")
    q.add_argument("--env", metavar="TEXT", help="command/N ('' to clear)")
    q.set_defaults(fn=cmd_report_update)


def add_report_remove(rsub):
    q = rsub.add_parser("remove", help="remove a strength, enforcement item, action, feature, or a finding or gap new in this report")
    report_arg(q)
    q.add_argument("ref", metavar="REF", help=EDIT_REF_HELP + " (only one no earlier report has: IDs that were reported stay)")
    q.set_defaults(fn=cmd_report_remove)


def add_report_gap(rsub):
    q = rsub.add_parser("gap", help="add a gap (something the code should do but doesn't)")
    report_arg(q)
    q.add_argument("--gap", required=True)
    q.add_argument("--severity", required=True, choices=SEVERITIES[::-1])
    q.add_argument("--necessity", required=True, choices=["must-have", "nice-to-have"])
    q.add_argument("--status", default="new", choices=GAP_STATUSES)
    q.add_argument("--rationale")
    q.add_argument("--benchmarks", nargs="+", required=True, metavar="ID")
    q.set_defaults(fn=cmd_report_gap)


def add_report_feature(rsub):
    q = rsub.add_parser("feature", help="add a feature to the inventory (the same name again updates it: status, source, evidence)")
    report_arg(q)
    q.add_argument("--feature", required=True)
    q.add_argument("--source", required=True, help="where it's claimed, e.g. README")
    q.add_argument("--status", required=True, choices=["complete", "partial", "stub", "broken", "undocumented"])
    evidence_args(q)
    q.set_defaults(fn=cmd_report_feature)


def add_report_flag(rsub):
    q = rsub.add_parser("flag", help="record an integrity flag: repo text that tries to influence grading")
    report_arg(q)
    q.add_argument("--description", required=True)
    evidence_args(q)
    q.set_defaults(fn=cmd_report_flag)


def add_report_ran(rsub):
    q = rsub.add_parser("ran", help="record a command you ran")
    report_arg(q)
    q.add_argument("--command", "--command-text", dest="command_text", required=True, metavar="CMD",
                   help="exactly what you ran, so others (and `guard snapshot --from-report`) can run it again; notes go in --summary")
    q.add_argument("--exit-code", type=int)
    q.add_argument("--summary", required=True)
    q.add_argument("--workdir", metavar="DIR", help="where it ran, if not the code checkout (e.g. 'a copy of CODE')")
    q.add_argument("--output", metavar="FILE", help="its output (saved to a file, or '-' for stdin): gradekit keeps a fingerprint, "
                   "so `report check` can tell whether excerpts were copied from it")
    q.add_argument("--env", metavar="TEXT", help="what it ran with, e.g. 'Python 3.13 venv with requirements-dev.txt'")
    q.set_defaults(fn=cmd_report_ran)


def add_report_set(rsub):
    q = rsub.add_parser("set", help=f"set a field: {', '.join(SETTABLE)} (dotted keys, e.g. metrics.line_coverage_pct)")
    report_arg(q)
    q.add_argument("key", help="e.g. summary, metrics.line_coverage_pct, or limitations.2 (one item of a list)")
    q.add_argument("value", nargs="?", help="JSON (a number, true, an object…) or plain text")
    q.add_argument("--append", action="store_true", help="append to a list")
    q.add_argument("--remove", action="store_true", help="remove one item of a list (key LIST.N)")
    q.set_defaults(fn=cmd_report_set)


def add_report_check(rsub):
    q = rsub.add_parser("check", help="what's missing or wrong; with --write, store the rollup when it's complete")
    report_arg(q)
    q.add_argument("--repo", metavar="DIR_OR_ZIP", help="also verify every citation against the code")
    q.add_argument("--tolerance", type=int, default=2)
    q.add_argument("--write", action="store_true", help="store the rollup and the finish time")
    q.set_defaults(fn=cmd_report_check)
