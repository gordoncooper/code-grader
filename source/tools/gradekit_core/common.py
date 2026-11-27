"""Shared helpers: paths and constants, errors, JSON and TOML in and out, versions, finding text, and `emit`."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore


SUITE_DIR = Path(__file__).resolve().parents[2]   # this file is tools/gradekit_core/common.py
CATALOG_PATH = SUITE_DIR / "rubric" / "catalog.json"
DEFAULTS_PATH = SUITE_DIR / "config" / "defaults.toml"
SCHEMA_PATH = SUITE_DIR / "schema" / "report.schema.json"          # format 5: what this kit writes and reads
REPORT_FORMAT = 5
GLOSSARY_PATH = SUITE_DIR / "rubric" / "glossary.json"
PROJECT_FILE, DECISIONS_FILE, DISPOSITIONS_FILE = "project.toml", "decisions.json", "dispositions.json"
OPEN_STATUSES = {"new", "noticed", "open", "regressed"}
FINDING_STATUSES = ["new", "noticed", "open", "fixed", "regressed", "accepted", "withdrawn"]   # noticed, withdrawn: format 5
DISPUTES_FILE = "disputes.json"
GAP_STATUSES = ["new", "open", "fixed", "regressed", "accepted"]
SEVERITIES = ["minor", "major", "critical"]
HEAT = {"cold": 0, "normal": 1, "hot": 2}


# =========================================================================== helpers

class GradekitError(Exception):
    """Raised for any user-facing problem; the CLI prints it, the web API returns it."""


# What a command says about its work as it goes (e.g. each line it cited) waits here until the command succeeds, so a
# command that fails never looks as if it half-worked. `emit` prints it; a failure drops it and says nothing was saved.
PENDING_NOTES: list[str] = []


def say_later(msg: str) -> None:
    PENDING_NOTES.append(msg)


def die(msg: str, code: int = 1):
    if PENDING_NOTES:
        n = len(PENDING_NOTES)
        PENDING_NOTES.clear()
        msg += f"\n(nothing was saved: the {plural(n, 'citation')} checked so far weren't written either; fix this and run it again)"
    raise GradekitError(msg)


JSON_KINDS = {dict: "an object", list: "a list", str: "a string", int: "a number", float: "a number", bool: "true or false",
              type(None): "null"}


def _finite_number(text: str) -> float:
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"the number {text} is too large for JSON")
    return value


def _not_json(name: str):
    raise ValueError(f"{name} isn't valid JSON")


def load_json(path, want: type | tuple = dict):
    """A JSON file's content. Every file the kit reads holds an object ({…}) unless `want` says otherwise, and anything
    else is refused here, so no command trips over a report that's a list or a string. NaN, Infinity and numbers too
    large to store are refused too: the kit's own JSON output must stay JSON."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh, parse_float=_finite_number, parse_constant=_not_json)
    except FileNotFoundError:
        die(f"file not found: {path}")
    except IsADirectoryError:
        die(f"{path} is a folder, not a JSON file")
    except UnicodeDecodeError as exc:
        die(f"{path} isn't UTF-8 text: {exc}")
    except ValueError as exc:   # json.JSONDecodeError is one
        die(f"{path} is not valid JSON: {exc}")
    except RecursionError:
        die(f"{path} is nested too deeply to read")
    if want and not isinstance(data, want):
        should = " or ".join(dict.fromkeys(JSON_KINDS[t] for t in (want if isinstance(want, tuple) else (want,))))
        die(f"{path} holds {JSON_KINDS.get(type(data), type(data).__name__)}, but should hold {should}")
    return data


def write_json(path, data: dict) -> None:
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        die(f"not writing {path}: it would hold a number JSON can't store (NaN or Infinity): {exc}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def load_toml(path) -> dict:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        die(f"file not found: {path}")
    return parse_toml(data.decode("utf-8"), str(path))


def parse_toml(text: str, name: str = "TOML") -> dict:
    if tomllib is None:
        die("reading TOML needs Python 3.11+ (or `pip install tomli`)")
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        die(f"{name} is not valid TOML: {exc}")


def load_catalog() -> dict:
    """rubric/catalog.json as it is on disk. The engine reads it once, as RUBRIC."""
    return load_json(CATALOG_PATH)


class Rubric:
    """The benchmarks, from rubric/catalog.json, which `gradekit rubric --write` makes from the rubric files."""

    def __init__(self, catalog: dict):
        self.catalog = catalog
        self.pillars = list(catalog["pillars"])
        self.benchmarks = catalog["benchmarks"]
        self.by_id = {b["id"]: b for b in self.benchmarks}
        self.ids = list(self.by_id)
        self.names = {b["id"]: b["name"] for b in self.benchmarks}
        # What the rubric files state about benchmarks (the Scope, Re-grade and Sensitive fields, `automatic:` caps).
        self.repo_level = tuple(b["id"] for b in self.benchmarks if b.get("scope") == "repo")
        self.always_regrade = tuple(b["id"] for b in self.benchmarks if b.get("regrade") == "any source change")
        self.sensitive = [b["id"] for b in self.benchmarks if b.get("sensitive")]
        self.automatic_caps = {c["id"]: c["automatic"] for b in self.benchmarks for c in b.get("caps", []) if c.get("automatic")}


RUBRIC = Rubric(load_catalog())   # read once
PILLARS = RUBRIC.pillars


def major(version) -> str:
    return str(version).split(".")[0]


# Three versions, each with its own job:
# - the kit version (rubric/catalog.json): prompts, tools and report format, e.g. 6.0.0. Projects pin its major.
# - the scoring version (suite_version in config/defaults.toml): the rules that move scores. It's in every config
#   fingerprint. The kit has one set of rules, so a report graded under another scoring major is refused, never
#   recomputed under rules it wasn't graded with.
# - the report's own suite_version: the kit that wrote it. This kit reads format-5 reports from these majors:
READABLE_REPORT_MAJORS = ("5", "6")


def kit_version() -> str:
    return RUBRIC.catalog["suite_version"]


def scoring_version_of(report: dict) -> str:
    """The scoring rules a report was graded under: recorded since 5.0; before that the kit version said it."""
    return str((report.get("config") or {}).get("scoring_version") or report.get("suite_version") or "0")


def report_format(report: dict) -> int:
    """5 for reports this kit writes; 4 for suite 4.x reports, which have no schema_version. This kit reads format 5."""
    v = report.get("schema_version")
    return v if isinstance(v, int) else 4


def old_format_problem(report: dict) -> str | None:
    """Why this kit can't read a report, or None: suite 4.x reports (format 4) need the 4.x or 5.x kit."""
    if report_format(report) >= REPORT_FORMAT:
        return None
    v = report.get("suite_version")
    v = v if isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) else None
    older = v is not None and major(v) != "5"
    kits = (f"the {major(v)}.x or 5.x kit (the suite website's /v{major(v)}/ or /v5/ path)" if older
            else "the 5.x kit (the suite website's /v5/ path)")
    return (f"this report is format {report_format(report)}{f' (suite {v})' if v else ''}, and this kit ({kit_version()}) reads "
            f"format {REPORT_FORMAT} reports only. Open it with {kits}, or grade the project again with this kit")


def kit_scoring_version() -> str:
    """The scoring rules this kit grades under (config/defaults.toml)."""
    return str(load_toml(DEFAULTS_PATH).get("suite_version", "0"))


def load_report(path) -> dict:
    """A report this kit can read. An older one is refused, saying which kit reads it."""
    report = load_json(path)
    problem = old_format_problem(report)
    if problem:
        die(f"{path}: {problem}")
    return report


def fingerprint_of(f: dict) -> str:
    """The same problem gets the same fingerprint across reports: benchmark, files and quoted code (or, without
    code, the title's words). Wording of notes doesn't change it; moving the code doesn't either."""
    files = sorted(evidence_files(f.get("evidence", [])) | {repo_relative(p) for p in f.get("paths", []) or []})
    quotes = sorted({norm(ln) for ev in f.get("evidence", []) if ev.get("type") == "code"
                     for ln in str(ev.get("quote", "")).splitlines() if norm(ln)})
    body = [f.get("benchmark_id"), files, quotes or sorted(_tokens(f.get("title") or ""))]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest()[:12]


def withheld(f: dict) -> bool:
    return any(ev.get("type") == "withheld" for ev in f.get("evidence", []) or [])


def refresh_fingerprint(f: dict) -> None:
    """Set a finding's fingerprint from its evidence. A public copy's withheld finding keeps the one computed from
    the full report: the same problem stays recognizable, and nothing about it is revealed."""
    if not withheld(f):
        f["fingerprint"] = fingerprint_of(f)


def suite_pin(cfg: dict) -> str | None:
    v = (cfg.get("project") or {}).get("suite")
    return None if v in (None, "") else str(v).strip()


def pin_problem(cfg: dict) -> str | None:
    """A project pinned to another major can't get a report from this kit: the rules would change mid-cycle."""
    pin = suite_pin(cfg)
    if pin and pin != major(kit_version()):
        return (f"this project is pinned to suite {pin} (`suite = \"{pin}\"` in project.toml), but this kit is {kit_version()}. "
                f"Use a {pin}.x kit (the suite website's /v{pin}/ path, or a v{pin}.x release), or move the project to "
                f"{major(kit_version())}.x: people set `suite = \"{major(kit_version())}\"` in project.toml, in a pull request of its own, "
                "and the next report is a full grade. Scores aren't comparable across majors")
    return None


def level_num(level: str) -> int:
    return int(str(level).lstrip("L"))


def benchmarks_by_id(report: dict) -> dict:
    return {b.get("id"): b for b in report.get("benchmarks", [])}


def expected_weight(applicability: str, config_weight: int) -> int:
    if applicability == "limited":
        return min(config_weight, 1)
    if applicability == "not_applicable":
        return 0
    return config_weight


def all_text(obj) -> str:
    if isinstance(obj, dict):
        return " ".join(all_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(all_text(v) for v in obj)
    return str(obj) if obj is not None else ""


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def enforcement_items(b: dict) -> list[dict]:
    """A benchmark's enforcement as {note, evidence}. Format 5 stores it that way, like strengths; format 4 stored
    bare evidence objects, which this wraps."""
    out = []
    for e in b.get("enforcement") or []:
        if isinstance(e, dict) and "type" not in e and isinstance(e.get("evidence"), list):
            out.append(e)
        elif isinstance(e, dict):
            out.append({"note": e.get("note") or "", "evidence": [e]})
    return out


def iter_evidence(report: dict):
    """Yield (location, evidence, benchmark_id_or_None) for every evidence object."""
    for f in report.get("findings", []):
        for ev in f.get("evidence", []):
            yield f"finding {f.get('id')}", ev, f.get("benchmark_id")
    for b in report.get("benchmarks", []):
        for i, s in enumerate(b.get("strengths", [])):
            for ev in s.get("evidence", []):
                yield f"{b.get('id')} strength #{i + 1}", ev, b.get("id")
        for i, e in enumerate(enforcement_items(b)):
            for ev in e["evidence"]:
                yield f"{b.get('id')} enforcement #{i + 1}", ev, b.get("id")
    for feat in report.get("feature_inventory", []):
        for ev in feat.get("evidence", []) or []:
            yield f"feature '{feat.get('feature')}'", ev, None
    for i, flag in enumerate(report.get("integrity_flags", [])):
        for ev in flag.get("evidence", []):
            yield f"integrity flag #{i + 1}", ev, None


def repo_relative(path) -> str:
    """'./src/x.py' or '/src/x.py' -> 'src/x.py'. Keeps leading dots that belong to the name (.github/, .env)."""
    p = str(path).strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "project"


EXIT_INCOMPLETE = 5


def utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MAX_QUOTE_LINES = 3   # grader.md Part 5: a quote is 1-3 lines


def emit(args, result: dict, text: str) -> None:
    """Every command's output: text for people; with --json, main() wraps `result` in the envelope."""
    for note in PENDING_NOTES:
        print(note, file=sys.stderr)
    PENDING_NOTES.clear()
    args._result = result
    if text:
        print(text)


# ---------------------------------------------------------------- commands

# In a monorepo, what the whole repository shares (grader Part 9): the rubric's `Scope: repo` benchmarks.
REPO_LEVEL = RUBRIC.repo_level


def evidence_files(items) -> set[str]:
    out = set()
    for ev in items:
        if ev.get("type") == "code" and ev.get("file"):
            out.add(repo_relative(ev["file"]))
    return out


# ---------------------------------------------------------------- matching findings across reports

STOPWORDS = {"the", "and", "for", "not", "with", "are", "but", "has", "have", "into", "from", "this", "that", "when", "its",
             "can", "does", "per", "all", "any", "one", "only", "out", "too", "via", "without", "missing", "no"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", str(text).lower()) if len(w) >= 3 and w not in STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def finding_fingerprint(f: dict) -> dict:
    files = evidence_files(f.get("evidence", [])) | {repo_relative(p) for p in f.get("paths", []) or []}
    quotes = {norm(ln) for ev in f.get("evidence", []) if ev.get("type") == "code" for ln in str(ev.get("quote", "")).splitlines()
              if len(norm(ln)) >= 12}
    text = " ".join([f.get("title") or ""] + [str(ev.get(k) or "") for ev in f.get("evidence", []) for k in ("note", "searched")])
    return {"benchmark": f.get("benchmark_id"), "files": files, "quotes": quotes, "words": _tokens(text)}


def finding_similarity(a: dict, b: dict) -> float:
    fa, fb = finding_fingerprint(a), finding_fingerprint(b)
    if fa["benchmark"] != fb["benchmark"]:
        return 0.0
    score = 0.45 * _jaccard(fa["words"], fb["words"]) + 0.35 * _jaccard(fa["files"], fb["files"])
    score += 0.2 if fa["quotes"] & fb["quotes"] else 0.0
    if not fa["files"] and not fb["files"]:
        score += 0.2 * _jaccard(fa["words"], fb["words"])
    return round(min(score, 1.0), 2)


def git_out(cwd, *args, check=True) -> str:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        die(f"git {' '.join(args)}: {exc}")
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


# =========================================================================== run times

def started_arg(args, now: str) -> str:
    """run.started: --started if given (a UTC time no later than now), else now."""
    if not getattr(args, "started", None):
        return now
    stamp = utc_stamp(args.started)
    if stamp is None or "T" not in str(args.started):
        die(f"--started {args.started!r}: give a UTC time like 2026-11-08T14:05:00Z")
    if stamp > now:
        die(f"--started {stamp} is later than now ({now})")
    return stamp


def utc_stamp(value) -> str | None:
    """A 4.x run.date as a format-5 UTC timestamp: '2026-11-07' → '2026-11-07T00:00:00Z'."""
    import datetime
    s = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s + "T00:00:00Z"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        return s
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def dash(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer() and abs(v) >= 10:
        return str(int(v))
    return str(v)


def evidence_line(ev: dict) -> str:
    t = ev.get("type")
    note = f": {ev['note']}" if ev.get("note") else ""
    if t == "code":
        return f"`{ev.get('file')}:{ev.get('lines')}`{note}"
    if t == "command":
        return f"ran `{ev.get('command')}`{note}"
    if t == "absence":
        return f"searched for {ev.get('searched')} ({ev.get('method')}){note}"
    return "details withheld"
