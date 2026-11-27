"""verify-evidence: every code citation checked against the repo."""
from __future__ import annotations

import re
from pathlib import Path

from .common import die, iter_evidence, kit_version, load_report, norm, repo_relative, utc_now


def check_code_evidence(ev: dict, read_lines, tolerance: int) -> str | None:
    """read_lines(rel_path) -> list of lines, or a string describing why it can't be read."""
    rel = str(ev.get("file", ""))
    if Path(rel).is_absolute() or rel.startswith("/"):
        return f"absolute path not allowed: {rel}"
    if ".." in Path(rel).parts:
        return f"path escapes the repo: {rel}"
    lines = read_lines(rel)
    if isinstance(lines, str):
        return lines
    quote = norm(ev.get("quote", ""))
    if ev.get("lines") in (None, ""):   # format 5: the quote is the anchor
        if not quote:
            return "empty quote"
        return None if quote in norm("\n".join(lines)) else f"quote not found in {rel}"
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(ev.get("lines", "")))
    if not m:
        return f"bad line range '{ev.get('lines')}'"
    start, end = int(m.group(1)), int(m.group(2) or m.group(1))
    if end < start or start < 1:
        return f"bad line range '{ev.get('lines')}'"
    if end > len(lines):
        return f"{rel} has {len(lines)} lines; cited {start}-{end}"
    window = norm("\n".join(lines[max(0, start - 1 - tolerance):min(len(lines), end + tolerance)]))
    quote = norm(ev.get("quote", ""))
    if not quote:
        return "empty quote"
    if quote not in window:
        return f"quote not found at {rel}:{start}-{end} (±{tolerance} lines)"
    return None


def fs_reader(repo: Path):
    repo = repo.resolve()

    def read(rel: str):
        target = (repo / rel).resolve()
        try:
            target.relative_to(repo)
        except ValueError:
            return f"path escapes the repo: {rel}"
        if not target.is_file():
            return f"file not found: {rel}"
        try:
            return target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return f"cannot read {rel}: {exc}"
    return read


def zip_reader(zip_path: str):
    """Reads files from a repo archive, e.g. GitHub's "Download ZIP" (one top-level folder)."""
    import zipfile

    zf = zipfile.ZipFile(zip_path)
    names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in names}
    strip = len(tops) == 1 and all("/" in n for n in names)
    index = {(n.split("/", 1)[1] if strip else n): n for n in names}

    def read(rel: str):
        key = repo_relative(rel)
        if key not in index:
            return f"file not found in archive: {rel}"
        return zf.read(index[key]).decode("utf-8", errors="replace").splitlines()
    return read


def verify_evidence(report: dict, read_lines, tolerance: int = 2) -> dict:
    carried = {b["id"] for b in report.get("benchmarks", []) if b.get("carried_forward")}
    checked = skipped = 0
    failures: list[str] = []
    other = {"command": 0, "absence": 0, "withheld": 0}
    for loc, ev, bid in iter_evidence(report):
        etype = ev.get("type")
        if etype != "code":
            other[etype] = other.get(etype, 0) + 1
            continue
        if bid in carried:
            skipped += 1
            continue
        checked += 1
        problem = check_code_evidence(ev, read_lines, tolerance)
        if problem:
            failures.append(f"{loc}: {problem}")
    return {"checked": checked, "failures": failures, "skipped_carried_forward": skipped,
            "command": other.get("command", 0), "absence": other.get("absence", 0), "withheld": other.get("withheld", 0)}


def code_citations(report: dict) -> int:
    carried = {b["id"] for b in report.get("benchmarks", []) if b.get("carried_forward")}
    return sum(1 for _, ev, bid in iter_evidence(report) if ev.get("type") == "code" and bid not in carried)


def record_citations_checked(report: dict, result: dict) -> None:
    """run.citations_checked: that every code quote was just checked against the code, with --repo. `gradekit ci`
    can't see the code, so this record is how it knows; any later edit drops it."""
    if result.get("failures"):
        return
    report.setdefault("run", {})["citations_checked"] = {"code_citations": result["checked"], "date": utc_now(),
                                                         "kit": kit_version()}


def citations_check_note(report: dict) -> str | None:
    """What `gradekit ci` says when a report's quotes weren't checked against the code, or changed since."""
    n, rec = code_citations(report), (report.get("run") or {}).get("citations_checked")
    if not n:
        return None
    if not rec:
        return (f"{'its code quote wasn' if n == 1 else f'its {n} code quotes weren'}'t checked against the code: the grader runs `report check REPORT "
                "--repo CODE --write` (or `deliver --repo CODE`), which records it")
    if rec.get("code_citations") != n:
        return (f"its code quotes changed after they were checked against the code ({rec.get('code_citations')} then, {n} now): "
                "check them again with `report check REPORT --repo CODE --write`")
    return None


def cmd_verify_evidence(args) -> int:
    report = load_report(args.report)
    repo = Path(args.repo)
    if repo.suffix == ".zip" and repo.is_file():
        res = verify_evidence(report, zip_reader(str(repo)), args.tolerance)
    else:
        if not repo.is_dir():
            die(f"repo not found: {repo}")
        res = verify_evidence(report, fs_reader(repo), args.tolerance)
    for f in res["failures"]:
        print(f"FAIL: {f}")
    print(f"\ncode citations checked: {res['checked']}, failed: {len(res['failures'])}, "
          f"skipped (carried forward): {res['skipped_carried_forward']}; command: {res['command']}, "
          f"absence: {res['absence']} (not machine-checkable)" + (f"; withheld: {res['withheld']}" if res["withheld"] else ""))
    args._result = res
    return 1 if res["failures"] else 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_verify_evidence(sub):
    p = sub.add_parser("verify-evidence", help="check code citations against the repo")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--repo", default=".", help="repo folder, or a .zip of it (default: current folder)")
    p.add_argument("--tolerance", type=int, default=2, help="line drift allowed around the cited range (default 2)")
    p.set_defaults(fn=cmd_verify_evidence)
