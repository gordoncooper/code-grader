"""Work orders, and grading on a schedule."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from .common import die, emit, GradekitError, load_json, plural, PROJECT_FILE, utc_now, write_json
from .config import (
    load_config, project_dir_from_args, project_dir_or_die, report_folders, SCHEDULE_DEFAULTS, with_config,
)


# A work order is the request behind a run: who asked for what (grade, review, improve or check a pull
# request), on which commit or change, delivered how. It lives in projects/NAME/orders/<id>.json. The report
# that answers it records its ID in run.work_order, which closes it; people can also close one by hand.

ORDERS_DIR = "orders"
ORDER_ROLES = ("grade", "review", "improve", "prcheck")
ORDER_FILE = re.compile(r"orders/(\d{4}-\d{2}-\d{2}-(?:grade|review|improve|prcheck)-\d+)\.json")


def load_orders(pdir: Path) -> list[dict]:
    out = []
    for f in sorted((pdir / ORDERS_DIR).glob("*.json")) if (pdir / ORDERS_DIR).is_dir() else []:
        try:
            o = load_json(f)
        except GradekitError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def answered_orders(pdir: Path) -> dict:
    """{work order ID: report folder} for every report that records its work order."""
    out = {}
    for folder in report_folders(pdir):
        for f in [folder / "report.json", *sorted((folder / "runs").glob("*.json"))]:
            try:
                wo = ((load_json(f).get("run") or {}).get("work_order")) if f.exists() else None
            except GradekitError:
                wo = None
            if wo:
                out.setdefault(str(wo), folder.name)
    return out


def order_status(order: dict, answered: dict) -> str:
    if order.get("status") in ("done", "cancelled"):
        return order["status"]
    return "done" if order.get("id") in answered else "open"


def order_problems(order: dict, name: str | None = None) -> list[str]:
    p = []
    oid = str(order.get("id") or "")
    if not ORDER_FILE.fullmatch(f"orders/{oid}.json"):
        p.append(f"id {oid!r} should look like 2026-11-08-grade-1")
    if name and name != f"{oid}.json":
        p.append(f"the file is {name}, but its id is {oid}")
    if order.get("role") not in ORDER_ROLES:
        p.append(f"role {order.get('role')!r} should be one of {', '.join(ORDER_ROLES)}")
    if order.get("status", "open") not in ("open", "done", "cancelled"):
        p.append(f"status {order.get('status')!r} should be open, done or cancelled")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(order.get("created") or "")):
        p.append("created should be a UTC timestamp")
    return p


def work_order_note(pdir: Path | None, report: dict) -> str | None:
    wo = (report.get("run") or {}).get("work_order")
    if not wo or pdir is None:
        return None
    if not (pdir / ORDERS_DIR / f"{wo}.json").exists():
        return f"run.work_order {wo}: there's no {ORDERS_DIR}/{wo}.json in the project (a typo, or an order from somewhere else)"
    return None


def write_order(pdir: Path, role: str, **fields) -> tuple[dict, Path]:
    """projects/NAME/orders/<date>-<role>-<n>.json, with the next free n for today."""
    now = utc_now()
    n = 1 + max([int(m.group(1)) for f in (pdir / ORDERS_DIR).glob(f"{now[:10]}-{role}-*.json")
                 if (m := re.search(r"-(\d+)\.json$", f.name))] or [0]) if (pdir / ORDERS_DIR).is_dir() else 1
    oid = f"{now[:10]}-{role}-{n}"
    order = {"id": oid, "project": pdir.name, "role": role, "status": "open", "created": now, **fields}
    order = {k: v for k, v in order.items() if v is not None}
    out = pdir / ORDERS_DIR / f"{oid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, order)
    return order, out


def cmd_order_new(args) -> int:
    pdir = project_dir_from_args(args)
    if pdir is None or not (pdir / PROJECT_FILE).exists():
        die("give --project NAME (or --project-dir) of a project with a project.toml")
    order, out = write_order(pdir, args.role, requested_by=args.by, commit=args.commit, base_commit=args.base_commit,
                             change=args.change, delivery=args.delivery, budget=args.budget, notes=args.note)
    oid = order["id"]
    emit(args, {"order": order, "written": str(out)},
         f"wrote {out}\nGive the agent its ID (\"Work order: {oid}\"); its report records it with `--work-order {oid}`, which closes the order.")
    return 0


# ---------------------------------------------------------------- scheduled grading
# `gradekit due` says which projects are due for a grade under their [schedule]; with --write-orders it writes a grade
# work order for each, which the scheduled CI job sends as a pull request. A grader (a person's agent, or an agent run
# on a schedule) picks open orders up with `gradekit order list`.

def code_head(url: str | None) -> tuple[str | None, str | None]:
    """The default branch's newest commit of a code repo, by `git ls-remote` (no clone). (sha, None) or (None, why)."""
    import subprocess
    if not url:
        return None, "no code_repo in project.toml"
    try:
        r = subprocess.run(["git", "ls-remote", url, "HEAD"], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git ls-remote failed: {exc}"
    sha = (r.stdout.split() or [None])[0]
    if r.returncode != 0 or not sha:
        return None, f"couldn't read {url} ({(r.stderr.strip().splitlines() or ['no output'])[-1]})"
    return sha, None


def due_check(pdir: Path, cfg: dict, today: str, head: str | None, head_note: str | None) -> dict:
    """Whether a project is due for a grade today, and why (or why not)."""
    import datetime
    sched = cfg.get("schedule") or SCHEDULE_DEFAULTS
    every = sched.get("grade_every_days") or 0
    full = [f for f in report_folders(pdir) if load_json(f / "report.json").get("mode") != "pr"]
    last = load_json(full[-1] / "report.json") if full else None
    run = (last or {}).get("run") or {}
    last_date, last_commit = str(run.get("date") or "")[:10] or None, str(run.get("commit") or "") or None
    out = {"project": pdir.name, "grade_every_days": every, "last_grade": last_date, "last_commit": (last_commit or "")[:7] or None,
           "code_head": head[:7] if head else None, "due": False}
    open_grades = [o["id"] for o in load_orders(pdir) if o.get("role") == "grade" and order_status(o, answered_orders(pdir)) == "open"]
    if not every:
        out["reason"] = "no schedule ([schedule] grade_every_days = 0)"
        return out
    if open_grades:
        out["reason"] = f"already ordered ({', '.join(open_grades)})"
        return out
    if last_date is None:
        out.update(due=True, reason="never graded")
        return out
    days = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last_date)).days
    out["days_since"] = days
    if days < every:
        out["reason"] = f"graded {plural(days, 'day')} ago; next after {every}"
        return out
    if sched.get("only_if_code_changed", True):
        if head is None:
            out["reason"] = f"{days} days since the last grade, but the code's newest commit is unknown ({head_note or 'not checked'}); "\
                            "run with --check-code, or set only_if_code_changed = false"
            return out
        if last_commit and (head.startswith(last_commit) or last_commit.startswith(head)):
            out["reason"] = f"{days} days since the last grade, but the code hasn't changed ({head[:7]})"
            return out
    out.update(due=True, reason=f"{days} days since the last grade (every {every})" +
               (f"; the code moved from {last_commit[:7]} to {head[:7]}" if head and last_commit else ""))
    return out


def cmd_due(args) -> int:
    root = Path(args.grading_repo or ".")
    if args.project or args.project_dir:
        pdirs = [project_dir_or_die(args)]
    else:
        if not (root / "projects").is_dir():
            die(f"{root} has no projects/ folder (is it a grading repo?)")
        pdirs = [d for d in sorted((root / "projects").iterdir()) if (d / PROJECT_FILE).exists()]
    heads = {}
    for h in args.code_head or []:
        name, _, sha = h.partition("=")
        if not sha:
            die(f"--code-head {h}: expected NAME=SHA")
        heads[name] = sha
    today = args.today or utc_now()[:10]
    rows, written = [], []
    for pdir in pdirs:
        try:
            cfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), quiet=True)
        except GradekitError as exc:
            rows.append({"project": pdir.name, "due": False, "reason": f"config: {exc}"})
            continue
        head, note = heads.get(pdir.name), None
        sched = cfg.get("schedule") or SCHEDULE_DEFAULTS
        if head is None and args.check_code and sched.get("grade_every_days") and sched.get("only_if_code_changed", True):
            head, note = code_head((cfg.get("project") or {}).get("code_repo"))
        row = due_check(pdir, cfg, today, head, note)
        if row["due"] and args.write_orders:
            order, out = write_order(pdir, "grade", requested_by=args.by, commit=head,
                                     notes=f"Scheduled grade: {row['reason']}.", delivery="pr")
            row["order"] = order["id"]
            written.append(str(out))
        rows.append(row)
    lines = [f"{'due' if r['due'] else '-  '}  {r['project']}: {r['reason']}" + (f" → work order {r['order']}" if r.get("order") else "")
             for r in rows]
    emit(args, {"today": today, "projects": rows, "written": written}, "\n".join(lines) or "no projects")
    return 0


def cmd_order_list(args) -> int:
    root = Path(args.grading_repo or ".")
    pdirs = [project_dir_from_args(args)] if (args.project or args.project_dir) else (
        [d for d in sorted((root / "projects").iterdir()) if (d / PROJECT_FILE).exists()] if (root / "projects").is_dir() else [])
    rows = []
    for pdir in pdirs:
        answered = answered_orders(pdir)
        for o in load_orders(pdir):
            st = order_status(o, answered)
            if args.all or st == "open":
                rows.append({**o, "status": st, "report": answered.get(o.get("id"))})
    lines = [f"{r['id']}  {r['status']:<9} {r.get('project', '')}  {r['role']}" + (f"  → {r['report']}" if r.get("report") else "")
             + (f"  ({r['notes']})" if r.get("notes") else "") for r in rows]
    emit(args, {"orders": rows}, "\n".join(lines) or ("no work orders" if args.all else "no open work orders"))
    return 0


def cmd_order_close(args) -> int:
    pdir = project_dir_from_args(args)
    if pdir is None:
        die("give --project NAME (or --project-dir)")
    f = pdir / ORDERS_DIR / f"{args.id}.json"
    if not f.exists():
        die(f"no work order {args.id} in {pdir / ORDERS_DIR}")
    o = load_json(f)
    o["status"] = args.status
    o["closed"] = {"date": utc_now(), "by": args.by, **({"note": args.note} if args.note else {})}
    write_json(f, o)
    emit(args, {"order": o}, f"{args.id}: {args.status}")
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_order(sub):
    p = sub.add_parser("order", help="work orders: the request behind a run (new, list, close)")
    osub = p.add_subparsers(dest="order_cmd", required=True, metavar="STEP")
    q = osub.add_parser("new", help="write projects/NAME/orders/<id>.json, and print the ID to give the agent")
    with_config(q)
    q.add_argument("--role", required=True, choices=ORDER_ROLES)
    q.add_argument("--commit", help="the commit to grade or check")
    q.add_argument("--base-commit", help="prcheck: the change's base commit")
    q.add_argument("--change", metavar="URL", help="prcheck: the pull request")
    q.add_argument("--delivery", help="how the agent hands back its work, e.g. pr")
    q.add_argument("--budget", help="improve: how much to do, e.g. \"tier 0 and 1\"")
    q.add_argument("--by", help="who asked")
    q.add_argument("--note", help="anything else the agent should know")
    q.set_defaults(fn=cmd_order_new)
    q = osub.add_parser("list", help="open work orders (with --all, every one), for a project or the whole grading repo")
    with_config(q)
    q.add_argument("--all", action="store_true")
    q.set_defaults(fn=cmd_order_list)
    q = osub.add_parser("close", help="mark a work order done or cancelled (a report that records its ID closes it by itself)")
    with_config(q)
    q.add_argument("id")
    q.add_argument("--status", choices=["done", "cancelled"], default="done")
    q.add_argument("--by")
    q.add_argument("--note")
    q.set_defaults(fn=cmd_order_close)


def add_due(sub):
    p = sub.add_parser("due", help="which projects are due for a grade under their [schedule]; --write-orders asks for each")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--check-code", action="store_true", help="read each code repo's newest commit with `git ls-remote` (needs read access)")
    p.add_argument("--code-head", action="append", metavar="NAME=SHA", help="a project's newest code commit, if you know it (repeatable)")
    p.add_argument("--write-orders", action="store_true", help="write a grade work order for each project that's due")
    p.add_argument("--by", default="schedule", help="requested_by on the orders (default: schedule)")
    p.add_argument("--today", metavar="YYYY-MM-DD", help="default: today (UTC)")
    p.set_defaults(fn=cmd_due)
