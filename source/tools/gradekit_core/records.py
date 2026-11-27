"""People's records: accepted findings (dispositions.json), disputes, and which earlier finding an ID names."""
from __future__ import annotations

from pathlib import Path

from .common import DISPUTES_FILE, finding_similarity, GradekitError, load_json, SEVERITIES, withheld
from .config import folder_reports, read_list_file, report_folders


def disposition_entry(f: dict, cfg: dict) -> tuple[int, dict] | None:
    """The entry in dispositions.json that accepts a finding, as (its 1-based position, the entry): the newest one
    naming the finding's ID, or else the `match` entry the finding points to with disposition_ref. Only people write
    that file, so only they accept findings."""
    entries = cfg.get("dispositions") or []
    named = [(i, d) for i, d in enumerate(entries, 1) if d.get("finding_id") == f.get("id")]
    if named:
        return named[-1]
    ref = f.get("disposition_ref")
    if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(entries) and not entries[ref - 1].get("finding_id"):
        return ref, entries[ref - 1]
    return None


def report_folder_name(path) -> str:
    """The report folder a report file belongs to: …/<folder>/report.json or …/<folder>/components/NAME.json."""
    parent = Path(path).resolve().parent
    return parent.parent.name if parent.name == "components" else parent.name


def finding_in(pdir: Path | None, folder: str | None, fid: str) -> tuple[str, dict] | None:
    """The finding `fid` in a report folder (its report.json or a component report), as (folder, finding)."""
    d = pdir / "reports" / str(folder) if pdir and folder else None
    if d is None or not d.is_dir():
        return None
    for path in folder_reports(d):
        try:
            hit = next((f for f in load_json(path).get("findings", []) if f.get("id") == fid), None) if path.exists() else None
        except GradekitError:
            hit = None
        if hit:
            return d.name, hit
    return None


def earlier_finding(pdir: Path | None, folder: str, fid: str, before: str | None = None) -> tuple[str, dict] | None:
    """The newest report before `folder` (and, with `before`, dated no later than that day) with a finding `fid`, as
    (its folder, the finding): for an acceptance, the finding people saw when they decided."""
    if pdir is None:
        return None
    found = None
    for d in report_folders(pdir):
        if d.name == folder or (before and d.name[:10] > str(before)[:10]):
            continue
        for path in folder_reports(d):
            try:
                hit = next((f for f in load_json(path).get("findings", []) if f.get("id") == fid), None) if path.exists() else None
            except GradekitError:
                hit = None
            if hit:
                found = (d.name, hit)
                break
    return found


def not_the_same_finding(f: dict, earlier: tuple[str, dict] | None) -> str | None:
    """Why a finding isn't the one an earlier report had under its ID (another benchmark, worse, or other evidence).
    People accept the finding they saw; reusing its ID for another problem mustn't inherit the acceptance."""
    if earlier is None:
        return None
    where, e = earlier
    if e.get("benchmark_id") != f.get("benchmark_id"):
        return f"in {where} {f.get('id')} was a {e.get('benchmark_id')} finding, not {f.get('benchmark_id')}"
    if e.get("severity") in SEVERITIES and f.get("severity") in SEVERITIES and SEVERITIES.index(f["severity"]) > SEVERITIES.index(e["severity"]):
        return f"it's {f['severity']} now, and in {where} it was {e['severity']}"
    if withheld(e):   # a public copy: its evidence is withheld, so only its benchmark and severity can be compared
        return None
    if (f.get("evidence") or e.get("evidence")) and finding_similarity(f, e) < 0.5:   # same file alone is 0.35
        return f"its title and evidence don't match {f.get('id')} in {where} ({e.get('title')!r})"
    return None


def disposition_text(entry: dict) -> str:
    """What an accepted finding's `disposition` says: the entry's decision and reason."""
    decision, reason = str(entry.get("decision") or "").strip(), str(entry.get("reason") or entry.get("match") or "").strip()
    return f"{decision}: {reason}" if decision and reason else decision or reason


def load_disputes(pdir: Path | None) -> list[dict]:
    return read_list_file(pdir / DISPUTES_FILE, "disputes") if pdir else []


def answered_disputes(pdir: Path) -> set:
    """(finding ID, dispute date) pairs some report has answered."""
    out = set()
    for folder in report_folders(pdir):
        for f in folder_reports(folder):
            if not f.exists():
                continue
            try:
                r = load_json(f)
            except GradekitError:
                continue
            for fd in r.get("findings", []):
                ans = fd.get("dispute") or {}
                if ans.get("answer") and ans.get("disputed_on"):
                    out.add((fd.get("id"), ans["disputed_on"]))
    return out


def open_disputes(pdir: Path | None, report: dict | None = None) -> list[dict]:
    """Disputes no report has answered yet. With `report`, also count its own answers (it may be the one answering)."""
    if pdir is None:
        return []
    done = answered_disputes(pdir)
    for fd in (report or {}).get("findings", []):
        ans = fd.get("dispute") or {}
        if ans.get("answer") and ans.get("disputed_on"):
            done.add((fd.get("id"), ans["disputed_on"]))
    return [d for d in load_disputes(pdir) if (d.get("finding_id"), d.get("date")) not in done]


ACCEPT_HINT = "`report finding accept REPORT ID`: it copies the people's entry from dispositions.json"
WITHDRAW_HINT = "`report finding answer REPORT ID --withdraw --note …` (disputes come from people, in disputes.json)"
