"""Disputes: people disputing findings, and graders' answers."""
from __future__ import annotations

from pathlib import Path

from .common import die, DISPUTES_FILE, emit, GradekitError, load_json, plural, PROJECT_FILE, utc_now, write_json
from .config import project_dir_for_report, project_dir_from_args, report_folders, with_config
from .records import (
    disposition_entry, disposition_text, earlier_finding, finding_in, load_disputes, not_the_same_finding,
    open_disputes, report_folder_name,
)
from .authoring import finding_or_die, load_for_edit, report_arg, save_edit


# A person who thinks a finding is wrong disputes it in projects/NAME/disputes.json (append-only). The next
# grader must answer: uphold it (with a note saying why it stands) or withdraw it (status `withdrawn`, which
# counts nowhere). An answer names the dispute's date, so the dispute is closed by the report that answers it.

def cmd_dispute_add(args) -> int:
    pdir = project_dir_from_args(args)
    if pdir is None or not (pdir / PROJECT_FILE).exists():
        die("give --project NAME (or --project-dir) of a project with a project.toml")
    folders = report_folders(pdir)
    known = {}
    for folder in folders:
        try:
            known.update({f.get("id"): folder.name for f in load_json(folder / "report.json").get("findings", [])})
        except GradekitError:
            continue
    if args.finding not in known:
        die(f"no finding {args.finding} in {pdir.name}'s reports")
    path = pdir / DISPUTES_FILE
    data = load_json(path) if path.exists() else {"_about": "Findings people think are wrong. Append new entries; never edit old "
                                                             "ones. The next grader answers each: upheld, or withdrawn.", "disputes": []}
    entry = {"finding_id": args.finding, "report": args.report or known[args.finding], "reason": args.reason, "by": args.by,
             "date": utc_now()}
    data.setdefault("disputes", []).append(entry)
    write_json(path, data)
    emit(args, {"dispute": entry, "written": str(path)},
         f"disputed {args.finding} in {path}\nThe next grader must answer it; commit {DISPUTES_FILE} in a pull request of its own.")
    return 0


def cmd_dispute_list(args) -> int:
    root = Path(args.grading_repo or ".")
    pdirs = [project_dir_from_args(args)] if (args.project or args.project_dir) else (
        [d for d in sorted((root / "projects").iterdir()) if (d / PROJECT_FILE).exists()] if (root / "projects").is_dir() else [])
    rows = []
    for pdir in pdirs:
        still = {(d.get("finding_id"), d.get("date")) for d in open_disputes(pdir)}
        for d in load_disputes(pdir):
            st = "open" if (d.get("finding_id"), d.get("date")) in still else "answered"
            if args.all or st == "open":
                rows.append({**d, "project": pdir.name, "status": st})
    emit(args, {"disputes": rows}, "\n".join(f"{r['finding_id']}  {r['status']:<8} {r['project']}  by {r.get('by')}: {r.get('reason')}"
                                             for r in rows) or "no open disputes")
    return 0


def cmd_finding_answer(args) -> int:
    report, cfg = load_for_edit(args)
    f = finding_or_die(report, args.id)
    pdir = project_dir_for_report(args.report) or project_dir_from_args(args)
    mine = [d for d in open_disputes(pdir, report) if d.get("finding_id") == args.id]
    if not mine:
        die(f"no open dispute on {args.id} in {DISPUTES_FILE}")
    d = mine[-1]
    why = not_the_same_finding(f, finding_in(pdir, d.get("report"), f["id"])) if args.withdraw else None
    if why:
        die(f"{f['id']} isn't the finding {d.get('by') or 'they'} disputed: {why}. Answer the dispute on that finding")
    f["dispute"] = {"answer": "withdrawn" if args.withdraw else "upheld", "note": args.note, "disputed_on": d["date"], "by": d.get("by")}
    if args.withdraw:
        f["status"] = "withdrawn"
    save_edit(args, report, cfg)
    emit(args, {"id": f["id"], "dispute": f["dispute"]},
         f"{f['id']}: dispute {'withdrawn: the finding no longer counts' if args.withdraw else 'upheld'}")
    return 0


def cmd_finding_accept(args) -> int:
    """Record that people accepted a finding: status accepted, with their entry's text. Only people write
    dispositions.json, so a finding no entry accepts can't be accepted here."""
    report, cfg = load_for_edit(args)
    f = finding_or_die(report, args.id)
    entries = cfg.get("dispositions") or []
    if args.entry is not None:
        if not 1 <= args.entry <= len(entries):
            die(f"--entry {args.entry}: dispositions.json has {plural(len(entries), 'entry')}")
        found = (args.entry, entries[args.entry - 1])
        if found[1].get("finding_id") and found[1]["finding_id"] != f["id"]:
            die(f"entry {args.entry} in dispositions.json accepts {found[1]['finding_id']}, not {f['id']}")
    else:
        found = disposition_entry({"id": f["id"]}, cfg)   # an entry naming this finding
        if found is None:
            matches = [(i, d) for i, d in enumerate(entries, 1) if not d.get("finding_id") and d.get("match")]
            hint = ("; if one of these describes it, give --entry N: " + "; ".join(f"{i}: {d['match']}" for i, d in matches)) if matches else ""
            die(f"no entry in dispositions.json accepts {f['id']}: only people accept findings, by adding an entry with its "
                f"finding_id{hint}")
    i, d = found
    pdir = project_dir_for_report(args.report)
    why = not_the_same_finding(f, earlier_finding(pdir, report_folder_name(args.report), f["id"], d.get("date")))
    if why:
        die(f"{f['id']} isn't the finding people accepted: {why}. A new problem gets a new ID (`report finding add` without --id)")
    f["status"] = "accepted"
    f["disposition"] = disposition_text(d)
    if d.get("finding_id"):
        f.pop("disposition_ref", None)   # the entry names the finding
    else:
        f["disposition_ref"] = i         # a `match` entry: say which one
    save_edit(args, report, cfg)
    by = f", decided by {d['decided_by']}" if d.get("decided_by") else ""
    emit(args, {"id": f["id"], "disposition": f["disposition"], "entry": i},
         f"{f['id']}: accepted ({f['disposition']}; dispositions.json entry {i}{by})")
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_finding_answer(fsub):
    q = fsub.add_parser("answer", help="answer a dispute on a finding: uphold it, or withdraw the finding")
    report_arg(q)
    q.add_argument("id")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--uphold", action="store_true", help="the finding stands")
    g.add_argument("--withdraw", action="store_true", help="the finding was wrong: status withdrawn, and it counts nowhere")
    q.add_argument("--note", required=True, help="why, for the person who disputed it")
    q.set_defaults(fn=cmd_finding_answer)


def add_finding_accept(fsub):
    q = fsub.add_parser("accept", help="mark a finding accepted, as an entry people added to dispositions.json says")
    report_arg(q)
    q.add_argument("id")
    q.add_argument("--entry", type=int, metavar="N", help="the dispositions.json entry (1 = first) when it's a `match` entry, "
                                                          "not one naming the finding's ID")
    q.set_defaults(fn=cmd_finding_accept)


def add_dispute(sub):
    p = sub.add_parser("dispute", help="say a finding is wrong (people): the next grader must answer it")
    dsub = p.add_subparsers(dest="dispute_cmd", required=True, metavar="STEP")
    q = dsub.add_parser("add", help="append a dispute to projects/NAME/disputes.json")
    with_config(q)
    q.add_argument("finding", metavar="FINDING_ID")
    q.add_argument("--reason", required=True, help="why the finding is wrong")
    q.add_argument("--by", required=True, help="who disputes it")
    q.add_argument("--report", metavar="FOLDER", help="the report folder it's in (default: the newest with that finding)")
    q.set_defaults(fn=cmd_dispute_add)
    q = dsub.add_parser("list", help="open disputes (with --all, every one), for a project or the whole grading repo")
    with_config(q)
    q.add_argument("--all", action="store_true")
    q.set_defaults(fn=cmd_dispute_list)
