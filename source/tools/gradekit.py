#!/usr/bin/env python3
"""gradekit: companion tool for the Code Grading Suite (v4).

Never trust a grader's arithmetic or citations; check them.

Configuration:
  init             Write a starter project.toml from a preset.
  resolve          Combine defaults + your configs into the effective config (weights, gates, zones…).
  presets          Compare weights and gates across presets.

Reports:
  validate         Check a report against the schema, the config and the suite's rules.
  verify-evidence  Confirm every code citation exists in the repo and the quote matches.
  rollup           Compute gates, zones, pillar/overall scores, targets, maturity and ranked priorities.
  stability        Merge several independent runs on one commit into a median consensus.
  diff             Compare two reports (score deltas, findings, regressions, divergence).
  calibrate        Compare a report against human-expected scores for a reference repo.
  redact           Strip hidden-check details so a report can be shared with improvers.
  rollup-repo      Combine per-component reports for a monorepo.

Writing a report (graders):
  report new       Start a report: all 35 benchmarks with weights and targets from the config.
  report cite      Print an evidence object for FILE:LINES with the exact quote.
  report finding   Add or update a finding (next free ID, quotes copied from the code).
  report score     Score a benchmark, or mark it limited / not applicable.
  report strength | enforcement | action | gap | feature | flag | ran | set
  report check     List what's missing or wrong; --write stores the rollup when it's complete.
  carry            Start the next report from the last one: IDs kept, citations moved to the new code.
  report match     Suggest which earlier finding each new one is, to keep its ID.
  doctor           Preflight: Python, kit, config, code, git and push access, the suite website.
  deliver          Hand back a finished report: pr (git steps printed, or run), save or return.
  index            Grading repos: projects/index.json, every project's latest score, history and decisions waiting.
  ci               Grading repos: check a pull request and write its summary comment and labels.
  glossary         The suite's terms and what they mean.
  render           Markdown from data: report.md, the PR title and body, the PR-check comment, the improvement log.

Projects: in a grading repo, pass --project NAME (folder projects/NAME/) and commands find the
project's settings, decisions, accepted findings and latest report themselves; `diff` compares
the latest two reports. --project-dir works for a project folder anywhere.
--config (repeatable) takes TOML files layered over config/defaults.toml in order, or one
effective-config JSON produced by `resolve --out`.

The website runs this same file in the browser (Pyodide) through web_api().

Python 3.11+ (uses tomllib); standard library only. Uses `jsonschema` when installed.
Every command takes --json: one JSON object on stdout, {ok, exit_code, command, result, text}
(with "error" when it failed), so agents never parse text.

Exit codes: 0 ok, 1 invalid/failed check/error, 2 regression (diff --fail-on-regression),
3 unstable runs (stability --strict), 4 calibration failed, 5 report not finished (report check),
64 bad arguments.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

SUITE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = SUITE_DIR / "rubric" / "catalog.json"
DEFAULTS_PATH = SUITE_DIR / "config" / "defaults.toml"
SCHEMA_PATH = SUITE_DIR / "schema" / "report.schema.json"          # format 5: what this kit writes
SCHEMA4_PATH = SUITE_DIR / "schema" / "report-4.schema.json"       # format 4: suite 4.x reports, still read
REPORT_FORMAT = 5
GLOSSARY_PATH = SUITE_DIR / "rubric" / "glossary.json"
PROJECT_FILE, DECISIONS_FILE, DISPOSITIONS_FILE = "project.toml", "decisions.json", "dispositions.json"
PILLARS = ["A", "B", "C", "D", "E", "F", "X"]
OPEN_STATUSES = {"new", "noticed", "open", "regressed"}
FINDING_STATUSES = ["new", "noticed", "open", "fixed", "regressed", "accepted", "withdrawn"]   # noticed, withdrawn: format 5
DISPUTES_FILE = "disputes.json"
GAP_STATUSES = ["new", "open", "fixed", "regressed", "accepted"]
SEVERITIES = ["minor", "major", "critical"]
HEAT = {"cold": 0, "normal": 1, "hot": 2}


# =========================================================================== helpers

class GradekitError(Exception):
    """Raised for any user-facing problem; the CLI prints it, the web API returns it."""


def die(msg: str, code: int = 1):
    raise GradekitError(msg)


def load_json(path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        die(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")


def write_json(path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


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
    return load_json(CATALOG_PATH)


def major(version) -> str:
    return str(version).split(".")[0]


# Three versions, each with its own job:
# - the kit version (rubric/catalog.json): prompts, tools and report format, e.g. 5.0.0. Projects pin its major.
# - the scoring version (suite_version in config/defaults.toml): the rules that move scores. It's in every config
#   fingerprint, and only reports with the same scoring major are compared for regressions. 5.0 keeps 4.2.0.
# - the report's own suite_version: the kit that wrote it. This kit reads reports from these majors:
READABLE_REPORT_MAJORS = ("4", "5")


def kit_version() -> str:
    return load_catalog()["suite_version"]


def scoring_version_of(report: dict) -> str:
    """The scoring rules a report was graded under: recorded since 5.0; before that the kit version said it."""
    return str((report.get("config") or {}).get("scoring_version") or report.get("suite_version") or "0")


def report_format(report: dict) -> int:
    """5 for reports this kit writes; 4 for suite 4.x reports, which have no schema_version."""
    v = report.get("schema_version")
    return v if isinstance(v, int) else 4


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
                f"{major(kit_version())}.x with `gradekit migrate`" + (" (a pull request of its own)" if int(pin) < int(major(kit_version())) else ""))
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


# =========================================================================== configuration

def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# Publishing settings never change scores, so they are not part of the config fingerprint.
PUBLISHING_DEFAULTS = {"public": True, "sensitive_benchmarks": ["A2"], "warn_at": "major"}

HASHED_KEYS = ("suite_version", "preset", "answers", "weights", "gates", "zones", "targets", "maturity", "priorities")


def config_hash(cfg: dict) -> str:
    """Fingerprint of everything that affects scoring. Project prose, dispositions and
    decisions are deliberately excluded: they change between cycles without re-weighting."""
    body = {k: cfg.get(k) for k in HASHED_KEYS}
    body["out_of_scope"] = (cfg.get("project") or {}).get("out_of_scope", [])
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def resolve_config(paths: list[str], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True, decisions: list | None = None, dispositions: list | None = None) -> dict:
    return resolve_layers([(str(p), load_toml(p)) for p in paths], component, preset_fallback, component_required,
                          decisions, dispositions)


def resolve_layers(layers: list[tuple[str, dict]], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True, decisions: list | None = None, dispositions: list | None = None) -> dict:
    catalog = load_catalog()
    ids = [b["id"] for b in catalog["benchmarks"]]
    names = {b["id"]: b["name"] for b in catalog["benchmarks"]}
    merged = load_toml(DEFAULTS_PATH)
    sources = [str(DEFAULTS_PATH.relative_to(SUITE_DIR))]
    for name, data in layers:
        merged = deep_merge(merged, data)
        sources.append(name)
    errors: list[str] = []
    warnings: list[str] = []

    scoring = load_toml(DEFAULTS_PATH).get("suite_version", "0")
    if major(merged.get("suite_version", "0")) != major(scoring):
        errors.append(f"config sets scoring version {merged.get('suite_version')}, but this kit scores with {scoring} "
                      "(suite_version belongs to config/defaults.toml; remove it from your config)")

    project = merged.get("project", {}) or {}
    pin = project.get("suite")
    if pin not in (None, "") and not re.fullmatch(r"\d+", str(pin).strip()):
        errors.append(f"project.suite is the suite's major version, e.g. \"{major(catalog['suite_version'])}\"; got {pin!r}")
    comp = None
    if component:
        comps = {c.get("name"): c for c in merged.get("components", []) or []}
        if component not in comps:
            if component_required:
                errors.append(f"unknown component '{component}' (known: {', '.join(comps) or 'none'})")
            else:
                warnings.append(f"report names component '{component}', which the config doesn't define; using project settings")
        else:
            comp = comps[component]

    presets = merged.get("presets", {})
    preset = (comp or {}).get("preset") or project.get("preset") or preset_fallback or "default"
    if preset not in presets:
        errors.append(f"unknown preset '{preset}' (known: {', '.join(presets)})")
        preset_answers = {}
    else:
        preset_answers = presets[preset].get("answers", {}) or {}

    questions = merged.get("questions", {})
    project_answers = merged.get("answers", {}) or {}
    comp_answers = (comp or {}).get("answers", {}) or {}
    for src_name, src in (("project [answers]", project_answers), ("component answers", comp_answers), (f"preset {preset}", preset_answers)):
        for q in src:
            if q not in questions:
                errors.append(f"{src_name}: unknown question '{q}'")

    answers: dict[str, dict] = {}
    for q, qdef in questions.items():
        if q in comp_answers:
            a, how = comp_answers[q], "component"
        elif q in project_answers:
            a, how = project_answers[q], "project"
        elif q in preset_answers:
            a, how = preset_answers[q], f"preset:{preset}"
        else:
            a, how = qdef.get("default"), "default"
        opts = qdef.get("options", {})
        if a not in opts:
            errors.append(f"question '{q}': unknown answer '{a}' (options: {', '.join(opts)})")
            continue
        answers[q] = {"answer": a, "source": how, "label": opts[a].get("label", a)}
        for bid in list(opts[a].get("effects", {})) + list(opts[a].get("gates", [])):
            if bid not in ids:
                errors.append(f"question '{q}' option '{a}': unknown benchmark '{bid}'")

    wcfg = merged.get("weights", {})
    wmin, wmax = int(wcfg.get("min", 1)), int(wcfg.get("max", 3))
    base = wcfg.get("base", {})
    overrides = dict(wcfg.get("overrides", {}) or {})
    overrides.update(((comp or {}).get("weights", {}) or {}).get("overrides", {}) or {})
    weights: dict[str, dict] = {}
    for bid in ids:
        if bid not in base:
            errors.append(f"weights.base is missing {bid}")
            continue
        b = int(base[bid])
        trace = []
        total = b
        for q, ans in answers.items():
            delta = questions[q]["options"][ans["answer"]].get("effects", {}).get(bid, 0)
            if delta:
                trace.append({"because": f"{q}={ans['answer']}", "delta": delta})
                total += delta
        clamped = max(wmin, min(wmax, total))
        entry = {"name": names[bid], "base": b, "trace": trace, "raw": total, "weight": clamped,
                 "clamped": clamped != total, "override": None}
        if bid in overrides:
            ov = overrides[bid]
            if not isinstance(ov, dict) or "weight" not in ov:
                errors.append(f"weights.overrides.{bid} must look like {{ weight = 3, reason = \"...\" }}")
            else:
                if not str(ov.get("reason", "")).strip():
                    errors.append(f"weights.overrides.{bid} needs a reason")
                w = int(ov["weight"])
                if not 0 <= w <= wmax:
                    errors.append(f"weights.overrides.{bid}: weight {w} outside 0..{wmax}")
                entry["override"] = {"weight": w, "reason": ov.get("reason", "")}
                entry["weight"] = w
        weights[bid] = entry
    for bid in overrides:
        if bid not in ids:
            errors.append(f"weights.overrides: unknown benchmark '{bid}'")

    gcfg = merged.get("gates", {})
    gate_why: dict[str, list[str]] = {}
    for bid in gcfg.get("always", []):
        gate_why.setdefault(bid, []).append("always")
    for q, ans in answers.items():
        for bid in questions[q]["options"][ans["answer"]].get("gates", []):
            gate_why.setdefault(bid, []).append(f"{q}={ans['answer']}")
    for bid in gcfg.get("extra", []) + ((comp or {}).get("gates", {}) or {}).get("extra", []):
        gate_why.setdefault(bid, []).append("extra")
    for bid in gcfg.get("exclude", []):
        if bid in ("A1", "A2"):
            warnings.append(f"gate {bid} excluded: correctness/security can now be averaged away. Be sure.")
        gate_why.pop(bid, None)
    for bid in gate_why:
        if bid not in ids:
            errors.append(f"gates: unknown benchmark '{bid}'")

    zs = merged.get("zone_settings", {})
    zones = list((comp or {}).get("zones", []) or []) + list(merged.get("zones", []) or [])
    for z in zones:
        if z.get("criticality") not in HEAT:
            errors.append(f"zone '{z.get('name')}': criticality must be hot, normal or cold")
        if not z.get("paths"):
            errors.append(f"zone '{z.get('name')}': needs at least one path pattern")
    if zs.get("default", "normal") not in HEAT:
        errors.append("zone_settings.default must be hot, normal or cold")

    targets = copy.deepcopy(merged.get("targets", {}))
    for bid in (targets.get("overrides") or {}):
        if bid not in ids:
            errors.append(f"targets.overrides: unknown benchmark '{bid}'")
    mode = targets.get("mode", "proportional")
    if not re.fullmatch(r"proportional|maximal|level:L[0-9]", str(mode)):
        errors.append(f"targets.mode '{mode}' must be proportional, maximal or level:L<n>")

    if merged.get("dispositions") or merged.get("decisions"):
        warnings.append("project.toml contains [[dispositions]] or [[decisions]]; these now live in "
                        "dispositions.json and decisions.json next to it, and are ignored here")
    dispositions = list(dispositions or [])
    for i, d in enumerate(dispositions, 1):
        if not (d.get("finding_id") or d.get("match")):
            errors.append(f"dispositions #{i}: needs finding_id or match")
        if not str(d.get("reason", "")).strip():
            errors.append(f"dispositions #{i}: needs a reason")
    decisions = list(decisions or [])
    for i, d in enumerate(decisions, 1):
        if not d.get("action_id"):
            errors.append(f"decisions #{i}: needs action_id")
        if not isinstance(d.get("approved"), bool):
            errors.append(f"decisions #{i} ({d.get('action_id')}): approved must be true or false")
    review = {"allow_agent_decisions": False, **(merged.get("review", {}) or {})}
    publishing = {**PUBLISHING_DEFAULTS, **(merged.get("publishing", {}) or {})}
    if not isinstance(publishing.get("public"), bool):
        errors.append("publishing.public must be true or false")
    if publishing.get("warn_at") not in SEVERITIES:
        errors.append(f"publishing.warn_at must be one of {', '.join(SEVERITIES)}")
    for bid in publishing.get("sensitive_benchmarks") or []:
        if bid not in ids:
            errors.append(f"publishing.sensitive_benchmarks: unknown benchmark '{bid}'")

    if errors:
        die(f"{len(errors)} configuration error(s):\n" + "\n".join(f"  - {e}" for e in errors))

    cfg = {
        "suite_version": merged.get("suite_version"),
        "generated_by": "gradekit.py resolve",
        "sources": sources,
        "project": project,
        "component": ({k: comp.get(k) for k in ("name", "path", "weight")} if comp else None),
        "preset": preset,
        "answers": answers,
        "weights": weights,
        "gates": {"benchmarks": sorted(gate_why), "why": gate_why,
                  "hard_floor": gcfg.get("hard_floor", 3), "overall_cap": gcfg.get("overall_cap", 4.0)},
        "zones": {"list": zones, "default": zs.get("default", "normal"),
                  "severity_shift": zs.get("severity_shift", {"hot": 1, "normal": 0, "cold": -1}),
                  "never_downgrade": zs.get("never_downgrade", ["A2"]),
                  "priority_multiplier": zs.get("priority_multiplier", {"hot": 2.0, "normal": 1.0, "cold": 0.5})},
        "targets": targets,
        "maturity": merged.get("maturity", {}),
        "priorities": merged.get("priorities", {}),
        "dispositions": dispositions,
        "decisions": decisions,
        "review": review,
        "publishing": publishing,
        "warnings": warnings,
    }
    cfg["hash"] = config_hash(cfg)
    return cfg


def read_list_file(path: Path, key: str) -> list:
    """decisions.json / dispositions.json: {"decisions": [...]} or a bare list. Missing file = empty."""
    if not path.exists():
        return []
    data = load_json(path)
    items = data.get(key, []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        die(f"{path}: expected a list under '{key}'")
    return items


def parse_list_text(text: str | None, key: str, name: str) -> list:
    if not text or not str(text).strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"{name} is not valid JSON: {exc}")
    items = data.get(key, []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        die(f"{name}: expected a list under '{key}'")
    return items


def project_dir_from_args(args) -> Path | None:
    """--project-dir PATH, or --project NAME (inside --grading-repo, default: current folder),
    or the current folder if it contains a project.toml."""
    if getattr(args, "project_dir", None):
        return Path(args.project_dir)
    if getattr(args, "project", None):
        return Path(getattr(args, "grading_repo", None) or ".") / "projects" / args.project
    if Path(PROJECT_FILE).exists():
        return Path(".")
    return None


def org_for(pdir: Path) -> Path | None:
    """org.toml at the root of the grading repo (two levels above projects/<name>/)."""
    full = pdir.resolve()
    if full.parent.name == "projects" and (full.parent.parent / "org.toml").exists():
        return full.parent.parent / "org.toml"
    return None


def order_report_folders(folders: list[str], run_dates: dict | None = None) -> tuple[list[str], list[str]]:
    """Report folders oldest first, and the folders whose run.date is still needed to order them.
    Only reports sharing a day need their run.date read (the folder name orders the rest)."""
    by_day: dict[str, list[str]] = {}
    for f in folders:
        by_day.setdefault(f[:10], []).append(f)
    rd = run_dates or {}
    need = [f for group in by_day.values() if len(group) > 1 for f in group if f not in rd]
    return sorted(folders, key=lambda f: (f[:10], str(rd.get(f) or ""), f)), need


def run_date_of(text: str | None) -> str:
    try:
        return str((json.loads(text or "").get("run") or {}).get("date") or "")
    except (ValueError, AttributeError):
        return ""


def report_folders(pdir: Path) -> list[Path]:
    root = pdir / "reports"
    if not root.is_dir():
        return []
    found = {d.name: d for d in root.iterdir() if d.is_dir() and (d / "report.json").exists()}
    _, need = order_report_folders(list(found))
    dates = {f: run_date_of((found[f] / "report.json").read_text(encoding="utf-8", errors="replace")) for f in need}
    return [found[f] for f in order_report_folders(list(found), dates)[0]]


def load_config(args, report: dict | None = None, quiet: bool = False) -> dict:
    paths = list(getattr(args, "config", None) or [])
    comp = getattr(args, "component", None)
    required = comp is not None
    if report and not comp:
        comp = (report.get("component") or {}).get("name")
        if comp == "repo":
            comp = None
    pdir = project_dir_from_args(args)
    decisions = read_list_file(pdir / DECISIONS_FILE, "decisions") if pdir else []
    dispositions = read_list_file(pdir / DISPOSITIONS_FILE, "dispositions") if pdir else []
    if len(paths) == 1 and paths[0].endswith(".json"):
        cfg = load_json(paths[0])
        if cfg.get("hash") != config_hash(cfg):
            die(f"{paths[0]} has been edited after it was generated (hash mismatch); re-run resolve")
        if pdir:
            cfg["decisions"], cfg["dispositions"] = decisions, dispositions
        return cfg
    if any(p.endswith(".json") for p in paths):
        die("--config takes either TOML files or a single effective-config JSON, not both")
    fallback = ((report or {}).get("config") or {}).get("preset")
    if not paths and pdir and (pdir / PROJECT_FILE).exists():
        org = org_for(pdir)
        paths = ([str(org)] if org else []) + [str(pdir / PROJECT_FILE)]
        if not quiet:
            print(f"note: using {' + '.join(paths)}")
    elif not paths and not quiet:
        print(f"note: no project found (use --project NAME or --config FILE); using suite defaults with preset '{fallback or 'default'}'")
    return resolve_config(paths, component=comp, preset_fallback=fallback, component_required=required,
                          decisions=decisions, dispositions=dispositions)


# =========================================================================== zones & severity

def repo_relative(path) -> str:
    """'./src/x.py' or '/src/x.py' -> 'src/x.py'. Keeps leading dots that belong to the name (.github/, .env)."""
    p = str(path).strip()
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def glob_to_regex(pattern: str) -> re.Pattern:
    p = repo_relative(pattern)
    if p.endswith("/"):
        p += "**"
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += r"(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += r".*"
            i += 2
        elif p[i] == "*":
            out += r"[^/]*"
            i += 1
        elif p[i] == "?":
            out += r"[^/]"
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile(rf"^{out}$")


def zone_for_path(path: str, cfg: dict) -> tuple[str | None, str]:
    path = repo_relative(path)
    for z in cfg["zones"]["list"]:
        for pat in z.get("paths", []):
            if glob_to_regex(pat).match(path):
                return z.get("name"), z.get("criticality")
    return None, cfg["zones"]["default"]


def finding_zone(finding: dict, cfg: dict) -> tuple[str | None, str]:
    """The hottest zone among the files a finding cites (code evidence + `paths`)."""
    files = [ev.get("file") for ev in finding.get("evidence", []) if ev.get("type") == "code" and ev.get("file")]
    files += list(finding.get("paths", []) or [])
    if not files:
        return None, cfg["zones"]["default"]
    return max((zone_for_path(f, cfg) for f in files), key=lambda z: HEAT[z[1]])


def effective_severity(finding: dict, criticality: str, cfg: dict) -> str:
    sev = finding.get("severity", "minor")
    if sev not in SEVERITIES:
        return sev
    shift = int(cfg["zones"]["severity_shift"].get(criticality, 0))
    if shift < 0 and finding.get("benchmark_id") in cfg["zones"]["never_downgrade"]:
        shift = 0
    idx = max(0, min(len(SEVERITIES) - 1, SEVERITIES.index(sev) + shift))
    return SEVERITIES[idx]


def analyze_findings(report: dict, cfg: dict) -> dict:
    out = {}
    for f in report.get("findings", []):
        zname, crit = finding_zone(f, cfg)
        out[f.get("id")] = {"zone": zname, "criticality": crit, "severity": f.get("severity"),
                            "effective_severity": effective_severity(f, crit, cfg),
                            "status": f.get("status"), "benchmark_id": f.get("benchmark_id")}
    return out


# =========================================================================== validate

def validate_report(report: dict, cfg: dict, catalog: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        import jsonschema  # type: ignore

        validator = jsonschema.Draft202012Validator(load_json(SCHEMA_PATH if report_format(report) >= 5 else SCHEMA4_PATH))
        for err in sorted(validator.iter_errors(report), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"schema: {loc}: {err.message}")
    except ImportError:
        warnings.append("jsonschema not installed; structural schema check skipped (semantic checks still run)")
        for key in ("suite_version", "mode", "run", "config", "benchmarks", "findings"):
            if key not in report:
                errors.append(f"missing required field '{key}'")
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
        if f.get("status") == "accepted":
            disp = cfg.get("dispositions", []) or []
            if not any(d.get("finding_id") == fid for d in disp) and not any(d.get("match") for d in disp):
                warnings.append(f"finding {fid} is 'accepted' but no entry in dispositions.json covers it")
        if f.get("disposition") and f.get("status") != "accepted":
            warnings.append(f"finding {fid}: has a disposition but status is '{f.get('status')}'")
        if report_format(report) >= 5:
            if withheld(f):
                pass   # computed from the full report, before its evidence was withheld
            elif f.get("fingerprint") and f["fingerprint"] != fingerprint_of(f):
                errors.append(f"finding {fid}: fingerprint {f['fingerprint']} doesn't match its evidence (gradekit writes it: "
                              "`report check --write` or `rollup --write`)")
            elif not f.get("fingerprint"):
                warnings.append(f"finding {fid}: no fingerprint yet (`report check --write` or `rollup --write` adds it)")
    if (report_format(report) >= 5 and report.get("rollup") and not report.get("migrated")
            and not str((report.get("run") or {}).get("model") or "").strip()):
        errors.append("run.model is empty: a finished report records the model that graded it (`report set REPORT run.model NAME`)")
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
        if bid in gates and app != "full":
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
            if score <= 6 and not b.get("finding_ids") and not b.get("carried_forward"):
                warnings.append(f"{bid}: score {score} but no findings explain what is wrong")
            for w in over_limit(b, limits.get(bid)):
                msg = f"{bid}: score {score} is above its limit of {w['max']} ({w['why']})"
                (errors if limits_enforced(report) else warnings).append(msg)
            for entry in b.get("caps_applied", []) or []:
                if resolve_cap(entry, bid, caps_) is None:
                    warnings.append(f"{bid}: caps_applied entry {entry!r} isn't a rubric cap (use its ID, e.g. {bid}-cap-1)")
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
    for loc, ev, _ in iter_evidence(report):
        if ev.get("type") == "withheld" and loc.removeprefix("finding ") not in sens:
            errors.append(f"{loc}: withheld evidence is only for findings marked sensitive (redact adds it; graders cite real evidence)")
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
    report = load_json(args.report)
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


# =========================================================================== verify-evidence

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


def cmd_verify_evidence(args) -> int:
    report = load_json(args.report)
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


# =========================================================================== rollup

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
    tw = sum(w for _, w in items)
    return round(sum(s * w for s, w in items) / tw, 1) if tw else None


# --------------------------------------------------------------- score limits
# Each benchmark's highest allowed score, and why. In format-5 reports a score above it is an error.

CRITICAL_MAX, NO_STRENGTH_MAX, NO_ENFORCEMENT_MAX = 5, 8, 9
AUTO_CAPS = {"D2-cap-1": "open critical gap"}   # caps whose condition is in the report's own data


def catalog_caps(catalog: dict | None = None) -> dict:
    """{cap ID: {id, when, max, benchmark}} from the catalog (the rubric's "Caps:" lines)."""
    catalog = catalog or load_catalog()
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
        crit = [fid for fid in b.get("finding_ids", []) if fz.get(fid, {}).get("effective_severity") == "critical"
                and fz.get(fid, {}).get("status") in OPEN_STATUSES]
        if crit:
            why.append({"kind": "critical", "max": CRITICAL_MAX, "why": f"open critical finding {', '.join(crit)}"})
        for entry in b.get("caps_applied", []) or []:
            c = resolve_cap(entry, bid, caps)
            if c:
                why.append({"kind": "cap", "max": c["max"], "why": (f"{c['id']}: " if c["id"] else "") + c["when"]})
        for f in open_:
            c = caps.get(f.get("cap") or "")
            if c and c["benchmark"] == bid:
                why.append({"kind": "cap", "max": c["max"], "why": f"{c['id']}: {c['when']} ({f.get('id')})"})
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


def limits_enforced(report: dict) -> bool:
    """Format-5 reports are held to their limits; 4.x reports (and migrated ones, graded under 4.x) get warnings."""
    return report_format(report) >= 5 and not report.get("migrated")


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
    for b in report.get("benchmarks", []):
        if b.get("applicability") == "not_applicable" or not isinstance(b.get("score"), int):
            continue
        tv = targets.get(b["id"])
        for act in b.get("path_to_target", []):
            resolved = [fz[f] for f in act.get("resolves", []) if f in fz]
            heat = max((r["criticality"] for r in resolved), key=lambda c: HEAT[c], default=cfg["zones"]["default"])
            gain = max(0, min(act.get("expected_new_score", b["score"]), tv if tv is not None else 10) - b["score"])
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


def apply_rollup(report: dict, cfg: dict) -> dict:
    if report_format(report) >= 5:
        for f in report.get("findings", []):
            refresh_fingerprint(f)
    roll = compute_rollup(report, cfg)
    report["rollup"] = roll
    for b in report.get("benchmarks", []):
        b["target"] = roll["targets"].get(b.get("id"))
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
    report = load_json(args.report)
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


# =========================================================================== stability

def compute_consensus(runs: list[dict], cfg: dict) -> dict:
    if len(runs) < 2:
        die("need at least two runs")
    notes = []
    commits = {r.get("run", {}).get("commit") for r in runs}
    if len(commits) > 1:
        notes.append(f"runs graded different commits: {sorted(map(str, commits))}")
    hashes = {(r.get("config") or {}).get("hash") for r in runs}
    if len(hashes) > 1:
        notes.append(f"runs used different configs: {sorted(map(str, hashes))}")
    ids = [b["id"] for b in load_catalog()["benchmarks"]]
    medians, unstable, rows = {}, [], []
    for bid in ids:
        entries = [benchmarks_by_id(r).get(bid, {}) for r in runs]
        apps = [e.get("applicability", "not_applicable") for e in entries]
        scores = [e.get("score") for e in entries]
        majority_na = apps.count("not_applicable") > len(runs) / 2
        nums = [x for x in scores if isinstance(x, int)]
        med = None if majority_na or not nums else statistics.median_low(nums)
        spread = (max(nums) - min(nums)) if nums else 0
        split = len(set(apps)) > 1
        flag = spread > 1 or split
        if flag:
            unstable.append(bid)
        applicable = [a for a in apps if a != "not_applicable"]
        maj_app = "not_applicable" if majority_na else statistics.mode(applicable)
        medians[bid] = {"median": med, "applicability": maj_app, "scores": scores,
                        "applicability_votes": apps, "spread": spread, "unstable": flag}
        rows.append({"id": bid, "scores": scores, "median": med, "spread": spread, "unstable": flag, "split": split})

    def distance(r):
        bb = benchmarks_by_id(r)
        return sum(abs(bb.get(b, {}).get("score") - m["median"]) for b, m in medians.items()
                   if isinstance(bb.get(b, {}).get("score"), int) and m["median"] is not None)

    base_idx = min(range(len(runs)), key=lambda i: distance(runs[i]))
    consensus = copy.deepcopy(runs[base_idx])
    for b in consensus.get("benchmarks", []):
        m = medians.get(b.get("id"))
        if not m:
            continue
        if m["applicability"] == "not_applicable":
            b.update(applicability="not_applicable", score=None, confidence=None)
            b["applicability_reason"] = b.get("applicability_reason") or "majority of runs judged not applicable"
        else:
            if b.get("applicability") == "not_applicable":
                b["applicability"] = m["applicability"]
                b["applicability_reason"] = b.get("applicability_reason") or "consensus of other runs"
                b["confidence"] = "low"
            b["score"] = m["median"]
            b["config_weight"] = cfg["weights"][b["id"]]["weight"]
            b["weight"] = expected_weight(b["applicability"], b["config_weight"])
    overall_by_run = [compute_rollup(r, cfg)["overall_score"] for r in runs]
    consensus["stability"] = {"runs": len(runs), "base_run_index": base_idx + 1,
                              "method": "median_low of integer scores; majority vote on applicability",
                              "overall_by_run": overall_by_run, "unstable_benchmarks": unstable, "per_benchmark": medians}
    roll = apply_rollup(consensus, cfg)
    return {"report": consensus, "rows": rows, "unstable": unstable, "overall_by_run": overall_by_run,
            "notes": notes, "rollup": roll}


def cmd_stability(args) -> int:
    runs = [load_json(p) for p in args.reports]
    cfg = load_config(args, runs[0])
    res = compute_consensus(runs, cfg)
    for n in res["notes"]:
        print(f"warning: {n}")
    print(f"{'ID':<4} {'scores':<20} {'median':>6} {'spread':>6}")
    for r in res["rows"]:
        sc = ",".join("–" if x is None else str(x) for x in r["scores"])
        mark = ("  ← unstable" + (" (applicability split)" if r["split"] else "")) if r["unstable"] else ""
        print(f"{r['id']:<4} {sc:<20} {('–' if r['median'] is None else r['median']):>6} {r['spread']:>6}{mark}")
    roll = res["rollup"]
    print(f"\noverall by run: {res['overall_by_run']}  → consensus {roll['overall_score']} ({roll['maturity']['current_level']})")
    print(f"unstable benchmarks: {', '.join(res['unstable']) or 'none'}  (spread > 1 or applicability split: tighten their rubric wording)")
    if args.out:
        write_json(args.out, res["report"])
        print(f"wrote consensus report to {args.out}")
    args._result = {"rows": res["rows"], "unstable": res["unstable"], "overall_by_run": res["overall_by_run"], "notes": res["notes"],
                    "consensus_overall": roll["overall_score"], "consensus_level": roll["maturity"]["current_level"], "written": args.out}
    return 3 if (args.strict and res["unstable"]) else 0


# =========================================================================== diff

def compute_diff(old: dict, new: dict, cfg_old: dict, cfg_new: dict) -> dict:
    regressions, notes = [], []
    same_major = major(scoring_version_of(old)) == major(scoring_version_of(new))
    oh, nh = (old.get("config") or {}).get("hash"), (new.get("config") or {}).get("hash")
    if oh != nh:
        notes.append(f"reports used different configs ({oh} → {nh}); weights may differ, so overall and maturity "
                     "changes can come from re-weighting, not code changes")
    r_old, r_new = compute_rollup(old, cfg_old), compute_rollup(new, cfg_new)
    if not same_major:
        notes.append(f"scoring versions differ ({scoring_version_of(old)} → {scoring_version_of(new)}); score deltas are not "
                     "comparable and are not used for regressions")
    ob, nb = benchmarks_by_id(old), benchmarks_by_id(new)
    changes = []
    for bid in [b["id"] for b in load_catalog()["benchmarks"]]:
        so, sn = ob.get(bid, {}).get("score"), nb.get(bid, {}).get("score")
        if so != sn:
            changes.append({"id": bid, "old": so, "new": sn})
            if same_major and isinstance(so, int) and isinstance(sn, int) and sn < so:
                regressions.append(f"{bid} dropped {so} → {sn}")
            if same_major and isinstance(so, int) and sn is None:
                notes.append(f"{bid} went from {so} to N/A; check the applicability reason")
        go = set(ob.get(bid, {}).get("gaming_flags", []) or [])
        for gflag in sorted(set(nb.get(bid, {}).get("gaming_flags", []) or []) - go):
            regressions.append(f"{bid} new gaming flag: {gflag}")
    lo, ln = r_old["maturity"]["current_level"], r_new["maturity"]["current_level"]
    if level_num(ln) < level_num(lo):
        regressions.append(f"maturity dropped {lo} → {ln}")
    newly_failed = {g["benchmark_id"] for g in r_new["gates"] if g["status"] == "failed"} - \
                   {g["benchmark_id"] for g in r_old["gates"] if g["status"] == "failed"}
    for bid in sorted(newly_failed):
        regressions.append(f"gate {bid} newly failed")
    of = {f["id"]: f for f in old.get("findings", [])}
    nf = {f["id"]: f for f in new.get("findings", [])}
    nz = r_new["finding_zones"]

    def brief(i):
        return {"id": i, "title": nf[i].get("title"), "severity": nf[i].get("severity"),
                "effective_severity": nz.get(i, {}).get("effective_severity", nf[i].get("severity")),
                "zone": nz.get(i, {}).get("criticality", "normal")}
    # New means not in the baseline. A finding carried over unchanged keeps whatever status it had
    # (PR checks copy untouched findings as-is), so status "new" alone doesn't make it new.
    new_ids = [brief(i) for i in nf if i not in of]
    fixed = [brief(i) for i, f in nf.items() if f.get("status") == "fixed" and of.get(i, {}).get("status") != "fixed"]
    regressed = [brief(i) for i, f in nf.items() if f.get("status") == "regressed"]
    # A problem first seen at the baseline's commit (or a PR's base commit) existed before this change:
    # report it, but don't count it against the change.
    before = [c for c in (old.get("run", {}).get("commit"), new.get("run", {}).get("base_commit")) if c]

    def pre_existing(i):
        if nf[i].get("status") == "noticed":   # format 5 says so directly
            return True
        seen = str(nf[i].get("first_seen_commit") or "")
        return bool(seen) and any(seen.startswith(c) or c.startswith(seen) for c in before)

    for f in new_ids:
        f["pre_existing"] = pre_existing(f["id"])
        if f["pre_existing"]:
            notes.append(f"pre-existing problem first recorded now (not caused by this change): {f['id']} "
                         f"({f['effective_severity']}, {f['zone']} zone): {f['title']}")
        elif f["effective_severity"] in ("critical", "major"):
            regressions.append(f"new {f['effective_severity']} finding {f['id']} ({f['zone']} zone): {f['title']}")
    for f in regressed:
        regressions.append(f"finding regressed {f['id']}: {f['title']}")
    for i, f in nf.items():
        if f.get("status") == "withdrawn" and of.get(i, {}).get("status") != "withdrawn":
            notes.append(f"withdrawn after a dispute: {i} ({(f.get('dispute') or {}).get('note') or 'no note'})")
    for i, f in of.items():
        if i not in nf and f.get("status") in OPEN_STATUSES:
            notes.append(f"open finding {i} disappeared without a 'fixed' status (finding IDs must be stable)")
    if new.get("integrity_flags"):
        regressions.append(f"{len(new['integrity_flags'])} integrity flag(s) in the new report")
    ho, hn = old.get("holdout", {}) or {}, new.get("holdout", {}) or {}
    hold = None
    if ho.get("run") and hn.get("run") and ho.get("pass_rate") is not None and hn.get("pass_rate") is not None:
        hold = {"old": ho["pass_rate"], "new": hn["pass_rate"]}
        if hn["pass_rate"] < ho["pass_rate"]:
            regressions.append(f"hidden-check pass rate dropped {ho['pass_rate']:.0%} → {hn['pass_rate']:.0%}")
            if (r_new["overall_score"] or 0) - (r_old["overall_score"] or 0) >= 0.5:
                notes.append("DIVERGENCE: visible scores rose while hidden checks fell; suspect the code is being "
                             "tuned to the rubric. Review the changes by hand before trusting these scores.")
    return {"from_commit": old.get("run", {}).get("commit"), "to_commit": new.get("run", {}).get("commit"),
            "mode": new.get("mode"), "score_changes": changes,
            "overall": {"old": r_old["overall_score"], "new": r_new["overall_score"]},
            "maturity": {"old": lo, "new": ln},
            "findings": {"new": new_ids, "fixed": fixed, "regressed": regressed},
            "holdout": hold, "regressions": regressions, "notes": notes,
            "verdict": "FAIL" if regressions else "PASS"}


def cmd_diff(args) -> int:
    old, new = load_json(args.old), load_json(args.new)
    cfg_new = load_config(args, new)
    if args.old_config:
        ns = argparse.Namespace(config=args.old_config, component=getattr(args, "component", None))
        cfg_old = load_config(ns, old, quiet=True)
    else:
        cfg_old = cfg_new
    d = compute_diff(old, new, cfg_old, cfg_new)
    print(f"{d['from_commit']} → {d['to_commit']}  (mode: {d['mode']})")
    print("\nScore changes:" if d["score_changes"] else "\nScore changes: none")
    for c in d["score_changes"]:
        print(f"  {c['id']}: {'–' if c['old'] is None else c['old']} → {'–' if c['new'] is None else c['new']}")
    print(f"Overall: {d['overall']['old']} → {d['overall']['new']}   Maturity: {d['maturity']['old']} → {d['maturity']['new']}")
    fs = d["findings"]
    print(f"\nFindings: {len(fs['new'])} new, {len(fs['fixed'])} fixed, {len(fs['regressed'])} regressed")
    for f in fs["new"]:
        print(f"  new       {f['id']} [{f['effective_severity']}, {f['zone']}] {f['title']}")
    for f in fs["fixed"]:
        print(f"  fixed     {f['id']} {f['title']}")
    for f in fs["regressed"]:
        print(f"  regressed {f['id']} {f['title']}")
    if d["holdout"]:
        print(f"Hidden checks: {d['holdout']['old']:.0%} → {d['holdout']['new']:.0%}")
    for n in d["notes"]:
        print(f"note: {n}")
    if d["regressions"]:
        print("\nREGRESSIONS:")
        for r in d["regressions"]:
            print(f"  - {r}")
    print(f"\nverdict: {d['verdict']}")
    args._result = d
    return 2 if (args.fail_on_regression and d["regressions"]) else 0


# =========================================================================== calibrate / redact / rollup-repo

def cmd_calibrate(args) -> int:
    report, exp = load_json(args.report), load_json(args.expected)
    crit = {"within_tolerance_pct": 90, "mae_max": 0.75, **exp.get("criteria", {})}
    bb = benchmarks_by_id(report)
    total = within = 0
    errs, mism, deltas = [], [], []
    print(f"{'ID':<4} {'expected':>8} {'actual':>6} {'Δ':>4}")
    for bid, e in sorted(exp.get("expected", {}).items()):
        b = bb.get(bid, {})
        actual = b.get("score")
        if e.get("applicability") and e["applicability"] != b.get("applicability"):
            mism.append(f"{bid}: expected {e['applicability']}, got {b.get('applicability')}")
        if e.get("score") is None or actual is None:
            continue
        tol = e.get("tolerance", 1)
        d = actual - e["score"]
        total += 1
        within += abs(d) <= tol
        errs.append(abs(d))
        deltas.append(d)
        print(f"{bid:<4} {e['score']:>8} {actual:>6} {d:>+4}" + ("" if abs(d) <= tol else "  ← outside tolerance"))
    if not total:
        die("no comparable benchmarks")
    pct, mae, bias = 100 * within / total, sum(errs) / total, sum(deltas) / total
    for m in mism:
        print(f"applicability mismatch: {m}")
    ok = pct >= crit["within_tolerance_pct"] and mae <= crit["mae_max"] and not mism
    print(f"\nwithin tolerance: {pct:.0f}% (need ≥ {crit['within_tolerance_pct']}%)  MAE: {mae:.2f} (need ≤ {crit['mae_max']})  "
          f"bias: {bias:+.2f} ({'grader runs generous' if bias > 0.25 else 'grader runs harsh' if bias < -0.25 else 'no clear bias'})")
    print("calibration: PASS" if ok else "calibration: FAIL")
    args._result = {"pass": ok, "within_tolerance_pct": round(pct, 1), "mae": round(mae, 3), "bias": round(bias, 3),
                    "compared": total, "applicability_mismatches": mism, "criteria": crit}
    return 0 if ok else 4


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("private_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


# =========================================================================== publishing
# A grading repo may be public. Findings marked "sensitive": true (usually security issues) keep
# everything scoring needs (id, benchmark, severity, status and the files they concern, so zones,
# gates, scores and priorities come out the same) and lose what would help an attacker: the title,
# quotes, commands and the wording of the actions that fix them. The full report is kept privately.

WITHHELD_NOTE = "Details withheld from the public report; whoever ran the grade has the private copy."
FINDING_KEEP = ("id", "benchmark_id", "severity", "status", "first_seen_commit", "disposition", "fingerprint")
LEAK_MIN = 12        # shortest withheld string worth searching for
LEAK_LINE_MIN = 24   # lines of a withheld quote searched for on their own


def sensitive_ids(report: dict) -> set[str]:
    return {f.get("id") for f in report.get("findings", []) if f.get("sensitive") is True}


def _withheld_text(f: dict) -> list[tuple[str, bool]]:
    """(text, is_quoted_code) pairs worth searching for. Quoted code is only a leak outside other
    findings' own quotes: another finding may cite the same public line for an unrelated reason."""
    out = [(f.get("title"), False), (f.get("disposition_concern"), False)]
    for ev in f.get("evidence", []):
        for key in ("quote", "excerpt", "command", "note", "searched"):
            val = ev.get(key)
            quoted = key in ("quote", "excerpt")
            out.append((val, quoted))
            if quoted and isinstance(val, str):
                out += [(ln, True) for ln in val.splitlines() if len(norm(ln)) >= LEAK_LINE_MIN]
    return [(norm(t), q) for t, q in out if isinstance(t, str) and len(norm(t)) >= LEAK_MIN and t != WITHHELD_NOTE]


def _without_quotes(obj):
    if isinstance(obj, dict):
        return {k: _without_quotes(v) for k, v in obj.items() if k not in ("quote", "excerpt")}
    if isinstance(obj, list):
        return [_without_quotes(v) for v in obj]
    return obj


def _ids_text(ids) -> str:
    ids = sorted(ids)
    return ("issue " if len(ids) == 1 else "issues ") + ", ".join(ids)


def redact_report(report: dict, catalog: dict | None = None) -> tuple[dict, list[str]]:
    """The copy of a report that is safe to publish, and any places where withheld text still shows."""
    names = {b["id"]: b["name"] for b in (catalog or load_catalog())["benchmarks"]}
    public = strip_private(copy.deepcopy(report))
    if "holdout" in public:
        public["holdout"]["private_details"] = "[redacted]"
    ids = sensitive_ids(report)
    secrets: list[tuple[str, str, bool]] = []
    findings = []
    for f in public.get("findings", []):
        if f.get("id") not in ids:
            findings.append(f)
            continue
        secrets += [(f["id"], t, q) for t, q in _withheld_text(f)]
        files = [repo_relative(ev["file"]) for ev in f.get("evidence", []) if ev.get("type") == "code" and ev.get("file")]
        paths = list(dict.fromkeys(list(f.get("paths", []) or []) + files))
        swap = {"title": f"{names.get(f.get('benchmark_id'), f.get('benchmark_id'))} issue (details withheld)",
                "evidence": [{"type": "withheld", "note": WITHHELD_NOTE}], "sensitive": True}
        if paths:
            swap["paths"] = paths
        g = {k: swap.get(k, v) for k, v in f.items() if k in FINDING_KEEP or k in swap}
        g.update({k: v for k, v in swap.items() if k not in g})
        findings.append(g)
    if "findings" in public:
        public["findings"] = findings

    reworded: dict[str, dict] = {}
    for b in public.get("benchmarks", []):
        for act in b.get("path_to_target", []) or []:
            hit = ids.intersection(act.get("resolves", []) or [])
            if not hit:
                continue
            for key in ("action", "decision_question"):
                if isinstance(act.get(key), str):
                    secrets.append((f"action {act.get('id')}", norm(act[key]), False))
            act["action"] = f"Fix withheld {_ids_text(hit)}. The private copy has the details."
            if act.get("decision_question"):
                act["decision_question"] = f"Approve the planned fix for withheld {_ids_text(hit)}? The private copy has the details."
            reworded[act.get("id")] = {"action": act["action"], "decision_question": act.get("decision_question"),
                                       "why_first": f"Fixes withheld {_ids_text(hit)}."}

    def patch(obj):
        if isinstance(obj, dict):
            new = reworded.get(obj.get("action_id")) if isinstance(obj.get("action_id"), str) else None
            for k, v in obj.items():
                obj[k] = new[k] if new and k in new and k in ("action", "decision_question", "why_first") else patch(v)
            return obj
        if isinstance(obj, list):
            return [patch(v) for v in obj]
        return obj
    for key in ("top_priorities", "rollup"):
        if public.get(key):
            public[key] = patch(public[key])
    public["publishing"] = {"redacted": True, "withheld": sorted(ids)}

    leaks: list[str] = []
    if secrets:
        places = [(f"benchmark {b.get('id')}", b) for b in public.get("benchmarks", [])]
        places += [(f"finding {f.get('id')}", f) for f in public.get("findings", []) if f.get("id") not in ids]
        places += [(k, v) for k, v in public.items() if k not in ("benchmarks", "findings")]
        texts = [(where, norm(all_text(v)), norm(all_text(_without_quotes(v)))) for where, v in places]
        for owner, secret, quoted in dict.fromkeys(secrets):
            for where, text, prose in texts:
                if secret in (prose if quoted else text):
                    leaks.append(f"{owner}: withheld text still appears in {where}: \"{secret[:60]}{'…' if len(secret) > 60 else ''}\"")
    return public, leaks


def publish_problems(report: dict, require_redacted: bool = True) -> list[str]:
    """Reasons a report is not yet safe to commit to a public grading repo."""
    errors = []
    if require_redacted and not (report.get("publishing") or {}).get("redacted"):
        errors.append("not redacted: run `gradekit redact --in-place` on it first")
    for f in report.get("findings", []):
        if f.get("sensitive") is True and any(ev.get("type") != "withheld" for ev in f.get("evidence", [])):
            errors.append(f"finding {f.get('id')} is sensitive but still carries its evidence")
    private = (report.get("holdout") or {}).get("private_details")
    if isinstance(private, list) and private:
        errors.append("holdout.private_details still lists hidden-check results")
    rest = copy.deepcopy(report)
    (rest.get("holdout") or {}).pop("private_details", None)
    if strip_private(rest) != rest:
        errors.append("report still has private_* fields")
    return errors


def private_path(path: str) -> str:
    return re.sub(r"\.json$", "", path) + ".private.json"


def cmd_redact(args) -> int:
    report = load_json(args.report)
    if (report.get("publishing") or {}).get("redacted"):
        die(f"{args.report} is already redacted" + (f"; the full report is {private_path(args.report)}" if args.in_place else ""))
    public, leaks = redact_report(report)
    if leaks:
        for leak in leaks:
            print(f"LEAK: {leak}")
        print("\nnothing written. Reword those places generically (or name only the finding ID) and run redact again.")
        args._result = {"leaks": leaks, "written": []}
        return 1
    withheld = public["publishing"]["withheld"]
    if args.in_place:
        priv = private_path(args.report)
        write_json(priv, report)
        write_json(args.report, public)
        written = {"public": args.report, "private": priv}
        print(f"wrote the full report to {priv}\nwrote the public report to {args.report}")
        print(f"keep {Path(priv).name} out of the repo (grading repos ignore *.private.json); hand it to whoever fixes the code.")
    else:
        out = args.out or re.sub(r"\.json$", "", args.report) + ".shared.json"
        write_json(out, public)
        print(f"wrote redacted report to {out}")
        written = {"public": out}
    args._result = {"leaks": [], "withheld": withheld, "written": written}
    print(f"withheld {len(withheld)} sensitive finding(s)" + (f": {', '.join(withheld)}" if withheld else ""))
    return 0


def repo_rollup(paths: list) -> dict:
    """The repo-wide result of a monorepo's reports: overall weighted by component weight, maturity the lowest."""
    rows = []
    for path in paths:
        r = load_json(path)
        roll = r.get("rollup")
        if not roll:
            die(f"{path} has no rollup; run `gradekit report check --write` (or `rollup --write`) on it first")
        comp = r.get("component") or {}
        if comp.get("name") == "repo":
            continue
        rows.append({"component": comp.get("name") or Path(path).stem, "weight": comp.get("weight", 1) or 1,
                     "preset": (r.get("config") or {}).get("preset"), "overall": roll["overall_score"],
                     "level": roll["maturity"]["current_level"], "failed_gates": [g["benchmark_id"] for g in roll["gates"] if g["status"] == "failed"]})
    if not rows:
        die("no component reports (components/NAME.json) to combine")
    scored = [(x["overall"], x["weight"]) for x in rows if x["overall"] is not None]
    tw = sum(w for _, w in scored)
    overall = round(sum(s * w for s, w in scored) / tw, 1) if tw else None
    lowest = min(rows, key=lambda x: level_num(x["level"]))
    return {"computed_by": "gradekit.py rollup-repo", "overall_score": overall, "maturity": lowest["level"],
            "limited_by": lowest["component"], "components": rows}


def component_reports(folder: Path) -> list[Path]:
    """A report folder's components/NAME.json (never the private copies)."""
    d = folder / "components"
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".private.json")) if d.is_dir() else []


def folder_reports(folder: Path) -> list[Path]:
    return [folder / "report.json", *component_reports(folder)]


def cmd_rollup_repo(args) -> int:
    if len(args.reports) == 1 and Path(args.reports[0]).is_dir():
        folder = Path(args.reports[0])
        if not (folder / "components").is_dir():
            die(f"{folder} has no components/ folder")
        summary = repo_rollup(folder_reports(folder)[1:])
        if args.write:
            main_path = folder / "report.json"
            r = load_json(main_path)
            r["repo_rollup"] = summary
            write_json(main_path, r)
            print(f"stored the repo-wide result in {main_path} (repo_rollup)")
        for x in summary["components"]:
            print(f"{x['component']:<20} {x['weight']:>6} {str(x['overall']):>7} {x['level']}")
        print(f"\nrepo overall (component-weighted): {summary['overall_score']}; maturity (lowest component): {summary['maturity']}")
        args._result = {**summary, "written": str(folder / "report.json") if args.write else None}
        return 0
    rows = []
    for path in args.reports:
        r = load_json(path)
        roll = r.get("rollup")
        if not roll:
            die(f"{path} has no rollup; run `gradekit rollup --write` on it first (with its component's config)")
        comp = r.get("component") or {}
        rows.append({"component": comp.get("name") or Path(path).stem, "weight": comp.get("weight", 1),
                     "preset": (r.get("config") or {}).get("preset"), "overall": roll["overall_score"],
                     "level": roll["maturity"]["current_level"], "failed_gates": [g["benchmark_id"] for g in roll["gates"] if g["status"] == "failed"]})
    scored = [(x["overall"], x["weight"]) for x in rows if x["overall"] is not None]
    tw = sum(w for _, w in scored)
    overall = round(sum(s * w for s, w in scored) / tw, 1) if tw else None
    lowest = min(rows, key=lambda x: level_num(x["level"]))
    print(f"{'component':<20} {'preset':<14} {'weight':>6} {'overall':>7} level")
    for x in rows:
        fg = f"  failed gates: {', '.join(x['failed_gates'])}" if x["failed_gates"] else ""
        print(f"{x['component']:<20} {str(x['preset']):<14} {x['weight']:>6} {str(x['overall']):>7} {x['level']}{fg}")
    print(f"\nrepo overall (component-weighted): {overall}")
    print(f"repo maturity (lowest component): {lowest['level']}  ← limited by '{lowest['component']}'")
    summary = {"computed_by": "gradekit.py rollup-repo", "overall_score": overall,
               "maturity": lowest["level"], "limited_by": lowest["component"], "components": rows}
    if args.out:
        write_json(args.out, summary)
        print(f"wrote {args.out}")
    args._result = {**summary, "written": args.out}
    return 0


# =========================================================================== config commands

def cmd_resolve(args) -> int:
    cfg = load_config(args)
    if args.explain:
        bid = args.explain.upper()
        w = cfg["weights"].get(bid)
        if not w:
            die(f"unknown benchmark {bid}")
        print(f"{bid} {w['name']}")
        print(f"  base weight            {w['base']}")
        for t in w["trace"]:
            print(f"  {t['delta']:+d}  because {t['because']}")
        if w["clamped"]:
            lo_hi = "max" if w["raw"] > w["base"] else "min"
            print(f"  = {w['raw']}, clamped to the {lo_hi} weight")
        if w["override"]:
            print(f"  override → {w['override']['weight']}  ({w['override']['reason']})")
        print(f"  final weight           {w['weight']}")
        if bid in cfg["gates"]["benchmarks"]:
            print(f"  GATE because: {', '.join(cfg['gates']['why'][bid])}")
        args._result = {"benchmark": bid, **w, "gate": bid in cfg["gates"]["benchmarks"],
                        "gate_why": cfg["gates"]["why"].get(bid, [])}
        return 0
    comp = f" · component {cfg['component']['name']}" if cfg.get("component") else ""
    print(f"Effective config {cfg['hash']} · preset {cfg['preset']}{comp}")
    print(f"Sources: {' → '.join(cfg['sources'])}\n")
    print("Answers:")
    for q, a in cfg["answers"].items():
        print(f"  {q:<17} {a['answer']:<16} ({a['source']})")
    print("\nWeights (base → final):")
    for pid in PILLARS:
        items = [(bid, w) for bid, w in cfg["weights"].items() if bid.startswith(pid)]
        cells = []
        for bid, w in items:
            mark = "*" if w["override"] else ("↑" if w["weight"] > w["base"] else "↓" if w["weight"] < w["base"] else " ")
            cells.append(f"{bid} {w['weight']}{mark}")
        print("  " + "  ".join(cells))
    print("  (↑/↓ changed by answers, * explicit override; `resolve --explain ID` shows why)")
    print("\nGates: " + ", ".join(f"{b} ({'/'.join(cfg['gates']['why'][b])})" for b in cfg["gates"]["benchmarks"]))
    print(f"  any gate ≤ {cfg['gates']['hard_floor']} caps overall at {cfg['gates']['overall_cap']}")
    if cfg["zones"]["list"]:
        print("\nZones (first match wins):")
        for z in cfg["zones"]["list"]:
            print(f"  {z.get('criticality'):<6} {z.get('name', ''):<14} {', '.join(z.get('paths', []))}")
    else:
        print(f"\nZones: none defined (all code is '{cfg['zones']['default']}')")
    t = cfg["targets"]
    print(f"\nTargets: {t.get('mode')}" + (f" · overrides {t.get('overrides')}" if t.get("overrides") else ""))
    for w in cfg.get("warnings", []):
        print(f"warning: {w}")
    if args.out:
        write_json(args.out, cfg)
        print(f"\nwrote {args.out}")
    args._result = {"config": cfg, "written": args.out}
    return 0


def cmd_presets(args) -> int:
    defaults = load_toml(DEFAULTS_PATH)
    for extra in args.config or []:
        defaults = deep_merge(defaults, load_toml(extra))
    names = list(defaults["presets"])
    # Org-level configs (if any) are layered in; each preset is then applied with no project answers.
    cfgs = {n: resolve_config(list(args.config or []), preset_fallback=n) for n in names}
    catalog = load_catalog()
    short = {"default": "Default", "service": "Service", "web_app": "Web app", "library": "Library",
             "oss_library": "OSS lib", "cli": "CLI", "internal_tool": "Internal", "prototype": "Prototype"}
    if args.markdown:
        print("| ID | Benchmark | Base | " + " | ".join(short.get(n, n) for n in names) + " |")
        print("|---|---|:-:|" + ":-:|" * len(names))
        for b in catalog["benchmarks"]:
            bid = b["id"]
            cells = []
            for n in names:
                w = cfgs[n]["weights"][bid]["weight"]
                g = "**" if bid in cfgs[n]["gates"]["benchmarks"] else ""
                cells.append(f"{g}{w}{g}")
            print(f"| {bid} | {b['name']} | {defaults['weights']['base'][bid]} | " + " | ".join(cells) + " |")
        print("\n**Bold** = gate for that preset.")
    else:
        print(f"{'ID':<4} {'base':>4} " + " ".join(f"{short.get(n, n)[:9]:>9}" for n in names))
        for b in catalog["benchmarks"]:
            bid = b["id"]
            cells = []
            for n in names:
                w = cfgs[n]["weights"][bid]["weight"]
                cells.append(f"{str(w) + ('g' if bid in cfgs[n]['gates']['benchmarks'] else ' '):>9}")
            print(f"{bid:<4} {defaults['weights']['base'][bid]:>4} " + " ".join(cells))
        print("\n(g = gate)")
    args._result = {"presets": names, "weights": {n: {b["id"]: cfgs[n]["weights"][b["id"]]["weight"] for b in catalog["benchmarks"]} for n in names},
                    "gates": {n: cfgs[n]["gates"]["benchmarks"] for n in names}}
    return 0


# =========================================================================== project.toml rendering

def toml_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", str(k)) else json.dumps(str(k), ensure_ascii=False)


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v if x is not None) + "]"
    if isinstance(v, dict):
        items = [f"{toml_key(k)} = {toml_value(x)}" for k, x in v.items() if x is not None]
        return "{ " + ", ".join(items) + " }" if items else "{}"
    raise GradekitError(f"can't write {type(v).__name__} to TOML")


def _emit_table(name: str, table: dict, out: list[str], array: bool = False) -> None:
    scalars = {k: v for k, v in table.items() if v is not None and not isinstance(v, dict)
               and not (isinstance(v, list) and v and all(isinstance(x, dict) for x in v))}
    out.append(f"[[{name}]]" if array else f"[{name}]")
    width = max([len(toml_key(k)) for k in scalars] + [1])
    for k, v in scalars.items():
        out.append(f"{toml_key(k):<{width}} = {toml_value(v)}")
    out.append("")
    for k, v in table.items():
        if isinstance(v, dict):
            _emit_table(f"{name}.{toml_key(k)}", v, out)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                _emit_table(f"{name}.{toml_key(k)}", item, out, array=True)


PROJECT_HEADER = """# Code Grading Suite (v{version}): project configuration
# People own this file. Agents read it but don't change it.
# Answers to decision questions go in decisions.json, accepted findings in dispositions.json.
# Check it with:  python3 SUITE_DIR/tools/gradekit.py resolve --config {path}
# Or use the "Set up a project" page on the suite's website.
"""


def render_project_toml(data: dict, defaults: dict | None = None, path: str = "project.toml") -> str:
    """Write a project config in the suite's standard layout, with helpful comments."""
    defaults = defaults or load_toml(DEFAULTS_PATH)
    d = copy.deepcopy(data or {})
    out = [PROJECT_HEADER.format(version=load_catalog()["suite_version"], path=path)]

    proj = d.pop("project", {}) or {}
    hints = {"preset": " | ".join(defaults.get("presets", {})),
             "code_repo": "where the code lives (informational)",
             "path": "monorepos: the subfolder this project covers",
             "maturity_target": "prototype | internal tool | production | public open source",
             "out_of_scope": "paths the grader skips, e.g. \"vendor/**\"",
             "suite": "the suite's major version for this project; tools won't write its reports with another"}
    order = ["name", "description", "code_repo", "path", "preset", "suite", "languages", "users", "maturity_target", "scope", "out_of_scope"]
    out.append("[project]")
    keys = [k for k in order if k in proj] + [k for k in proj if k not in order]
    width = max([len(k) for k in keys] + [15])
    for k in keys:
        if proj[k] is None:
            continue
        hint = f"   # {hints[k]}" if k in hints else ""
        out.append(f"{toml_key(k):<{width}} = {toml_value(proj[k])}{hint}")
    out.append("")

    answers = d.pop("answers", {}) or {}
    questions = defaults.get("questions", {})
    out.append("# Answers override the preset. Each one moves specific weights; see `gradekit resolve --explain ID`.")
    out.append("[answers]")
    for q in list(questions) + [q for q in answers if q not in questions]:
        if q not in answers:
            continue
        qd = questions.get(q, {})
        opts = " | ".join(qd.get("options", {}))
        comment = f"   # {qd.get('prompt', '')} ({opts})" if qd else ""
        out.append(f"{toml_key(q):<17} = {toml_value(answers[q])}{comment}")
    out.append("")

    zones = d.pop("zones", []) or []
    out.append("# Zones: the first match wins, so list specific zones first.")
    out.append("# hot = matters most (money, auth, data writes); cold = matters least (scripts, examples).")
    if zones:
        out.append("")
        for z in zones:
            _emit_table("zones", {k: z.get(k) for k in ("name", "paths", "criticality", "why") if z.get(k) is not None}
                        | {k: v for k, v in z.items() if k not in ("name", "paths", "criticality", "why")}, out, array=True)
    else:
        out += ["# [[zones]]", '# name        = "payments"', '# paths       = ["src/payments/**"]',
                '# criticality = "hot"', '# why         = "Moves money"', ""]

    targets = d.pop("targets", {}) or {}
    out.append("# Where improving agents stop: proportional (default) | maximal | level:L3")
    out.append("[targets]")
    out.append(f"mode = {toml_value(targets.get('mode', 'proportional'))}")
    if targets.get("overrides"):
        out.append(f"overrides = {toml_value(targets['overrides'])}")
    else:
        out.append("# overrides = { F4 = 10 }")
    for k, v in targets.items():
        if k not in ("mode", "overrides"):
            out.append(f"{toml_key(k)} = {toml_value(v)}")
    out.append("")

    weights = d.pop("weights", {}) or {}
    ov = weights.pop("overrides", {}) or {}
    out.append("# Explicit weight overrides (each needs a reason).")
    if ov:
        out.append("[weights.overrides]")
        for k, v in ov.items():
            out.append(f"{toml_key(k)} = {toml_value(v)}")
        out.append("")
    else:
        out += ["# [weights.overrides]", '# F4 = { weight = 3, reason = "Contractual p99 latency SLA" }', ""]
    for k, v in weights.items():
        if isinstance(v, dict):
            _emit_table(f"weights.{toml_key(k)}", v, out)

    gates = d.pop("gates", {}) or {}
    if gates:
        _emit_table("gates", gates, out)
    else:
        out += ["# Extra gates for this project, or (rarely) remove one:", "# [gates]", '# extra   = ["C4"]', "# exclude = []", ""]

    review = d.pop("review", None)
    if review:
        _emit_table("review", review, out)
    else:
        out += ["# Let agent reviewers approve decision questions (default: humans only):", "# [review]",
                "# allow_agent_decisions = true", ""]

    publishing = d.pop("publishing", None)
    if publishing:
        _emit_table("publishing", publishing, out)
    else:
        out += ["# Only trusted people can read this grading repo, so security details may stay in reports",
                "# (default: treat it as public and withhold them):", "# [publishing]", "# public = false", ""]

    for comp in d.pop("components", []) or []:
        _emit_table("components", comp, out, array=True)

    d.pop("dispositions", None)  # these live in dispositions.json / decisions.json, never in project.toml
    d.pop("decisions", None)

    for k, v in d.items():  # anything else (org-style overrides) is written generically
        if isinstance(v, dict):
            _emit_table(toml_key(k), v, out)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                _emit_table(toml_key(k), item, out, array=True)
        elif v is not None:
            out.insert(1, f"{toml_key(k)} = {toml_value(v)}")
    text = "\n".join(out).rstrip() + "\n"
    parse_toml(text, "generated project.toml")  # never hand out a file that doesn't parse
    return text


def starter_json(key: str) -> str:
    notes = {"decisions": "Answers to decision questions from grading reports. Append new entries; never edit old ones. "
                          "The newest answer to a question wins.",
             "dispositions": "Findings accepted as-is (e.g. won't fix). The grader marks them 'accepted' and they stop "
                             "lowering scores. Append new entries; never edit old ones."}
    return json.dumps({"_about": notes[key], key: []}, indent=2) + "\n"


def append_entries(text: str | None, key: str, entries: list[dict]) -> str:
    """Append entries to decisions.json / dispositions.json text, keeping everything already there."""
    if text and text.strip():
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            die(f"the existing {key}.json is not valid JSON: {exc}")
        if isinstance(data, list):
            data = {key: data}
    else:
        data = json.loads(starter_json(key))
    data.setdefault(key, [])
    data[key].extend(entries)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


GRADING_REPO_README = """# Grading

Grading reports for our codebases, produced with the Code Grading Suite.

```
projects/
└── <project>/                 one folder per graded codebase
    ├── project.toml           settings: preset, answers, zones, targets   (people)
    ├── decisions.json         answers to decision questions               (people)
    ├── dispositions.json      findings accepted as-is                     (people)
    └── reports/
        └── <date>-<commit>/   one folder per report                        (graders, via pull request)
            ├── report.json
            ├── report.md
            └── report.private.json   full report with security details   (never committed)
```

- Graders open a pull request per report, on a branch named `report/<project>/<date>-<commit>`.
- Decision answers go on that same pull request, or in a follow-up `decisions/<project>/<date>` pull request.
- `org.toml` at the root (optional) holds house rules shared by every project.
- Pull requests are checked by `gradekit ci` if the repo has the grading check (`gradekit init --ci github|gitlab`): one
  new report folder, or settings changes, per pull request; decisions and dispositions are append-only.
- `projects/index.json` lists every project's latest score, history and decisions waiting. It's made by `gradekit index`
  (CI rebuilds it after merges); don't edit it.
- This repo may be public. Before committing a report, graders run `gradekit redact --in-place`, which withholds
  the details of sensitive (security) findings, and `gradekit validate --publish`. The full report stays out of
  the repo as `report.private.json`.
"""

PRIVATE_IGNORE = "*.private.json"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "project"


CI_DIR = SUITE_DIR / "ci"


def install_ci(root: Path, host: str, site: str | None, force: bool = False) -> Path:
    """Add the grading check to a grading repo. Returns the file written."""
    text = (CI_DIR / f"{host}-grading.yml").read_text(encoding="utf-8")
    if site:
        text = text.replace("__SUITE_SITE__", site.rstrip("/"))
    if host == "github":
        dest = root / ".github" / "workflows" / "grading.yml"
    else:
        dest = root / ".gitlab-ci.yml"
        if dest.exists() and "grading-check:" not in dest.read_text(encoding="utf-8"):
            dest = root / ".gitlab" / "grading.yml"
            print(f"note: .gitlab-ci.yml exists; add this to it:\n  include:\n    - local: .gitlab/grading.yml")
    if dest.exists() and not force:
        print(f"{dest} exists; left as it is (use --force to replace it)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    print(f"wrote {dest}" + ("" if site else "  (set SUITE_SITE in the CI settings: your suite website's address)"))
    return dest


def cmd_init(args) -> int:
    defaults = load_toml(DEFAULTS_PATH)
    if args.preset not in defaults["presets"]:
        die(f"unknown preset '{args.preset}' (known: {', '.join(defaults['presets'])})")
    preset_answers = defaults["presets"][args.preset].get("answers", {}) or {}
    given = {}
    for kv in args.answer or []:
        if "=" not in kv:
            die(f"--answer must look like question=option, got '{kv}'")
        k, v = kv.split("=", 1)
        given[k.strip()] = v.strip()
    for q in given:
        if q not in defaults["questions"]:
            die(f"unknown question '{q}'")
    name = slug(args.project or args.name)
    answers = {q: given.get(q, preset_answers.get(q, qd.get("default"))) for q, qd in defaults["questions"].items()}
    proj = {"name": name, "description": "<what it is, in one sentence>"}
    if args.code_repo:
        proj["code_repo"] = args.code_repo
    if args.path:
        proj["path"] = args.path
    proj.update({"preset": args.preset, "suite": major(load_catalog()["suite_version"]),
                 "languages": "<e.g. Python 3.12, FastAPI, Postgres>", "users": "<who uses it>",
                 "maturity_target": "<choose one>", "scope": "<stated scope or link to requirements>", "out_of_scope": []})
    data = {"project": proj, "answers": answers}
    if args.project:
        root = Path(args.grading_repo or ".")
        pdir = root / "projects" / name
        out = pdir / PROJECT_FILE
    else:
        root, pdir, out = None, None, Path(args.out)
    if out.exists() and not args.force:
        die(f"{out} exists (use --force to overwrite)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_project_toml(data, defaults, path=str(out)), encoding="utf-8")
    print(f"wrote {out}")
    if pdir is not None:
        for fname, key in ((DECISIONS_FILE, "decisions"), (DISPOSITIONS_FILE, "dispositions")):
            if not (pdir / fname).exists():
                (pdir / fname).write_text(starter_json(key), encoding="utf-8")
                print(f"wrote {pdir / fname}")
        (pdir / "reports").mkdir(exist_ok=True)
        keep = pdir / "reports" / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
        if not (root / "README.md").exists():
            (root / "README.md").write_text(GRADING_REPO_README, encoding="utf-8")
            print(f"wrote {root / 'README.md'}")
        ignore = root / ".gitignore"
        lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
        if PRIVATE_IGNORE not in lines:
            ignore.write_text("\n".join(lines + ["# full reports with withheld security details; never commit them", PRIVATE_IGNORE]) + "\n",
                              encoding="utf-8")
            print(f"{'updated' if lines else 'wrote'} {ignore}")
    ci_file = None
    if getattr(args, "ci", None):
        if root is None:
            die("--ci needs --project (it sets up a grading repo)")
        ci_file = install_ci(root, args.ci, args.site, args.force)
    print(f"next: edit {out}, then run: gradekit resolve " + (f"--project {name}" if pdir else f"--config {out}"))
    args._result = {"project": name, "project_toml": str(out), "project_dir": str(pdir) if pdir else None,
                    "ci": str(ci_file) if ci_file else None}
    return 0


# =========================================================================== report authoring
# Graders build reports with these commands instead of typing JSON: weights, targets, quotes and
# IDs all come from the tool. Every command re-normalizes the report against the effective config.

EXIT_INCOMPLETE = 5
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


def utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def blank_benchmark(b: dict, cfg: dict) -> dict:
    cw = cfg["weights"][b["id"]]["weight"]
    return {"id": b["id"], "name": b["name"], "pillar": b["pillar"], "applicability": "full", "applicability_reason": None,
            "config_weight": cw, "weight": cw, "weight_note": None, "score": None, "confidence": None,
            "carried_forward": False, "caps_applied": [], "finding_ids": [], "strengths": [], "enforcement": [],
            "gaming_flags": [], "target": None, "path_to_target": [], "previous_score": None, "change_explanation": None}


def normalize_report(report: dict, cfg: dict, catalog: dict | None = None) -> dict:
    """Fill everything the tool knows: every benchmark (catalog order), names, pillars, weights, targets
    and finding_ids. Never touches a grader's judgments (scores, findings, evidence, prose)."""
    catalog = catalog or load_catalog()
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
        if report_format(report) >= 5:
            refresh_fingerprint(f)
    for bid, tv in compute_targets(report, cfg).items():
        if bid in by_id:
            by_id[bid]["target"] = tv
    return report


def project_dir_for_report(path) -> Path | None:
    """projects/NAME/reports/<folder>/report.json (or …/<folder>/runs/run-N.json) → projects/NAME."""
    p = Path(path).resolve().parent
    for cand in (p.parent, p.parent.parent):
        if cand.name == "reports" and (cand.parent / PROJECT_FILE).exists():
            return cand.parent
    return None


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
    quote = "\n".join(lines[start - 1:end]).strip("\n")
    if not quote.strip():
        die(f"{rel}:{start}-{end} is blank; cite the lines that show the problem")
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


def evidence_from_args(args, required: bool = False) -> list[dict]:
    out = []
    note = getattr(args, "note", None)
    cites = getattr(args, "cite", None) or []
    if cites:
        read = repo_reader(getattr(args, "repo", None))
        out += [cite(c, read, note) for c in cites]
    if getattr(args, "command", None):
        excerpt = read_text_arg(getattr(args, "excerpt", None))
        if not (excerpt or "").strip():
            die("--command needs --excerpt (the relevant output; '@file' or '-' for stdin)")
        out.append({"type": "command", "command": args.command, "excerpt": excerpt.strip("\n"), **({"note": note} if note else {})})
    if getattr(args, "absence", None):
        if not getattr(args, "method", None):
            die("--absence needs --method (how you searched)")
        out.append({"type": "absence", "searched": args.absence, "method": args.method, **({"note": note} if note else {})})
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


def emit(args, result: dict, text: str) -> None:
    """Every command's output: text for people; with --json, main() wraps `result` in the envelope."""
    args._result = result
    if text:
        print(text)


# ---------------------------------------------------------------- commands

REPO_LEVEL = ("B3", "E3", "E4", "F2", "F6", "X6")   # in a monorepo, what the whole repository shares (grader Part 9)


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
    catalog = load_catalog()
    previous = {}
    if pdir:
        rel_name = f"components/{slug(comp)}.json" if comp else "report.json"
        older = [f for f in report_folders(pdir) if (f / rel_name).exists() and (f / rel_name).resolve() != out.resolve()]
        if older:
            previous = benchmarks_by_id(load_json(older[-1] / rel_name))
    project = (cfg.get("project") or {}).get("name") or (pdir.name if pdir else None)
    report = {
        "schema_version": REPORT_FORMAT, "suite_version": catalog["suite_version"], "mode": args.mode,
        "run": {"project": project, "commit": commit, "base_commit": args.base_commit, "started": now, "date": now,
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
    report = load_json(args.report)
    cfg = authoring_config(args, report)
    return report, cfg


def save_edit(args, report: dict, cfg: dict) -> None:
    normalize_report(report, cfg)
    write_json(args.report, report)


def cmd_report_cite(args) -> int:
    ev = cite(args.spec, repo_reader(args.repo), args.note)
    args._result = ev
    print(json.dumps(ev, indent=None if args.compact else 2, ensure_ascii=False))
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
    if args.status == "noticed" and report_format(report) < 5:
        die("status 'noticed' needs a format-5 report (suite 5.x); in this 4.x report, use 'new' with --first-seen BASE_COMMIT")
    seen = args.first_seen or ((run.get("base_commit") or run.get("commit")) if args.status == "noticed" else run.get("commit"))
    f = {"id": fid, "benchmark_id": bid, "title": args.title, "severity": args.severity, "status": args.status,
         "first_seen_commit": seen,
         "evidence": evidence_from_args(args, required=True), "disposition": None, "disposition_concern": None}
    if args.paths:
        f["paths"] = [repo_relative(p) for p in args.paths]
    if args.sensitive:
        f["sensitive"] = True
    if args.cap:
        f["cap"] = finding_cap_or_die(args.cap, bid, report)
    report["findings"].append(f)
    save_edit(args, report, cfg)
    emit(args, {"id": fid, "finding": f}, f"added {fid} ({args.severity}): {args.title}")
    return 0


def finding_cap_or_die(cap: str, bid: str, report: dict) -> str:
    caps = catalog_caps()
    if report_format(report) < 5:
        die("--cap on a finding needs a format-5 report (suite 5.x); in this 4.x report, use `report score --cap`")
    if cap not in caps or caps[cap]["benchmark"] != bid:
        mine = "; ".join(f"{k}: {c['when']} → max {c['max']}" for k, c in caps.items() if c["benchmark"] == bid)
        die(f"{cap}: not one of {bid}'s caps ({mine or 'it has none'})")
    return cap


def cmd_finding_update(args) -> int:
    report, cfg = load_for_edit(args)
    f = finding_or_die(report, args.id)
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
            f["cap"] = finding_cap_or_die(args.cap, f.get("benchmark_id"), report)
        else:
            f.pop("cap", None)
    new_ev = evidence_from_args(args)
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
    if b["applicability"] == "not_applicable":
        if args.score is not None:
            die("a not_applicable benchmark has no score")
        b["score"], b["confidence"] = None, None
    else:
        if args.score is not None:
            b["score"] = args.score
        if args.confidence:
            b["confidence"] = args.confidence
        if b.get("score") is None or b.get("confidence") is None:
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
    if limits_enforced(report):
        too_high = over_limit(b, score_limits(report, cfg).get(b["id"]))
        if too_high:
            die(f"{b['id']}: {b['score']} is above its limit of {min(w['max'] for w in too_high)}: "
                + "; ".join(f"{w['why']} → max {w['max']}" for w in too_high))
    save_edit(args, report, cfg)
    msg = f"{b['id']} {b['name']}: " + ("not applicable" if b["score"] is None else f"{b['score']} ({b['confidence']} confidence)")
    if b.get("target") is not None:
        msg += f", target {b['target']}"
    emit(args, {"benchmark": b}, msg)
    return 0


def cmd_report_strength(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    b["strengths"].append({"note": args.text, "evidence": evidence_from_args(args, required=True)})
    save_edit(args, report, cfg)
    emit(args, {"benchmark_id": b["id"], "strengths": len(b["strengths"])}, f"{b['id']}: {len(b['strengths'])} strength(s)")
    return 0


def cmd_report_enforcement(args) -> int:
    report, cfg = load_for_edit(args)
    b = benchmark_or_die(report, args.benchmark)
    b["enforcement"] += evidence_from_args(args, required=True)
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


def cmd_report_feature(args) -> int:
    report, cfg = load_for_edit(args)
    evidence = evidence_from_args(args)
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
    flag = {"description": args.description, "evidence": evidence_from_args(args, required=True)}
    report["integrity_flags"].append(flag)
    save_edit(args, report, cfg)
    emit(args, {"integrity_flag": flag}, "added integrity flag (caps maturity at L1 for this run)")
    return 0


def cmd_report_ran(args) -> int:
    report, cfg = load_for_edit(args)
    entry = {"command": args.command_text, "exit_code": args.exit_code, "result_summary": args.summary}
    report["commands_run"].append(entry)
    save_edit(args, report, cfg)
    emit(args, {"command": entry}, f"recorded `{args.command_text}`")
    return 0


SETTABLE = ("summary", "scope_examined", "project_context_inferred", "metrics", "metrics_notes", "limitations", "holdout",
            "top_priorities", "run")


def cmd_report_set(args) -> int:
    report, cfg = load_for_edit(args)
    parts = args.key.split(".")
    if parts[0] not in SETTABLE:
        die(f"`report set` covers {', '.join(SETTABLE)}; use the other report commands for findings, scores and evidence")
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    node = report
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if not isinstance(node, dict):
            die(f"{args.key}: {p} is not an object")
    last = parts[-1]
    if args.append:
        node.setdefault(last, [])
        if not isinstance(node[last], list):
            die(f"{args.key} is not a list")
        node[last].append(value)
    else:
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
        todo.append("record the commands you ran: `report ran REPORT --command-text CMD --summary TEXT`")
    if not report.get("limitations"):
        todo.append("list limitations (or 'None'): `report set REPORT limitations \"...\" --append`")
    if report_format(report) >= 5 and not str((report.get("run") or {}).get("model") or "").strip():
        todo.append("record the model that graded: `report set REPORT run.model NAME` (or `report new --model`)")
    if report_format(report) >= 5 and pdir is not None:
        ids = {f.get("id") for f in report.get("findings", [])}
        for d in open_disputes(pdir, report):
            if d.get("finding_id") in ids:
                todo.append(f"answer the dispute on {d['finding_id']} ({d.get('by')}: {d.get('reason')}): "
                            f"`report finding answer REPORT {d['finding_id']} --uphold|--withdraw --note \"why\"`")
    return todo


def cmd_report_check(args) -> int:
    report, cfg = load_for_edit(args)
    normalize_report(report, cfg)
    errors, warnings = validate_report(report, cfg, load_catalog())
    pdir_ = project_dir_for_report(args.report) or project_dir_from_args(args)
    note = work_order_note(pdir_, report)
    if note:
        warnings.append(note)
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
    if args.write:
        if roll is not None:
            apply_rollup(report, cfg)
            report["run"]["date"] = utc_now()
            if report_format(report) >= 5:
                usage = report["run"].setdefault("usage", {})
                if usage.get("minutes") is None and report["run"].get("started"):
                    usage["minutes"] = minutes_between(report["run"]["started"], report["run"]["date"])
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
    emit(args, result, "\n".join(lines))
    return 1 if errors else EXIT_INCOMPLETE if todo else 0



# =========================================================================== carry forward
# The next report starts from the last one: findings keep their IDs, and every code citation is
# moved to where the same code is now. Benchmarks the change touches are cleared for re-grading.

ALWAYS_REGRADE = ("A1", "A3", "C1", "C2", "C3", "C4")   # pr-review.md: any source change


def _stripped(lines: list[str]) -> list[str]:
    return [ln.strip() for ln in lines]


def relocate_evidence(ev: dict, read_lines) -> tuple[dict, str]:
    """Move a code citation to the same code in another version of the repo.
    Returns (evidence, outcome): unchanged | moved | changed (the cited line itself changed) | lost.
    Quotes may be part of a line, as graders write them; they're kept unless the code changed."""
    if ev.get("type") != "code":
        return ev, "unchanged"
    lines = read_lines(str(ev.get("file", "")))
    if isinstance(lines, str):
        return ev, "lost"
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(ev.get("lines", "")))
    quote = norm(str(ev.get("quote", "")))
    if not m or not quote:
        return ev, "lost"
    start, end = int(m.group(1)), int(m.group(2) or m.group(1))
    span = end - start
    if end <= len(lines) and quote in norm("\n".join(lines[start - 1:end])):
        return ev, "unchanged"

    def label(n):
        return str(n) if span == 0 else f"{n}-{n + span}"

    hits = [i for i in range(max(1, len(lines) - span)) if quote in norm("\n".join(lines[i:i + span + 1]))]
    if hits:
        n = min(hits, key=lambda i: (abs(i + 1 - start), i)) + 1
        return dict(ev, lines=label(n)), "moved"
    first = next((norm(x) for x in str(ev.get("quote", "")).splitlines() if norm(x)), "")
    key = first.split("(")[0] + "(" if "(" in first else first[:24]
    if len(key.strip()) >= 8:
        hits = [i for i in range(len(lines)) if key in norm(lines[i])]
        if hits:
            n = min(hits, key=lambda i: (abs(i + 1 - start), i)) + 1
            e = min(len(lines), n + span)
            return dict(ev, lines=str(n) if e == n else f"{n}-{e}", quote="\n".join(lines[n - 1:e]).strip("\n")), "changed"
    return ev, "lost"


def evidence_files(items) -> set[str]:
    out = set()
    for ev in items:
        if ev.get("type") == "code" and ev.get("file"):
            out.add(repo_relative(ev["file"]))
    return out


def benchmark_files(report: dict) -> dict[str, set[str]]:
    files: dict[str, set[str]] = {}
    for loc, ev, bid in iter_evidence(report):
        if bid and ev.get("type") == "code" and ev.get("file"):
            files.setdefault(bid, set()).add(repo_relative(ev["file"]))
    for f in report.get("findings", []):
        for p in f.get("paths", []) or []:
            files.setdefault(f.get("benchmark_id"), set()).add(repo_relative(p))
    return files


def suggest_touched(baseline: dict, changed: list[str], cfg: dict) -> tuple[list[str], list[str]]:
    """Benchmarks to re-grade for a change (pr-review.md step 1, the parts a tool can see), with reasons."""
    if not changed:
        return [], []
    changed = [repo_relative(c) for c in changed]
    touched, why = set(ALWAYS_REGRADE), [f"{', '.join(ALWAYS_REGRADE)}: any change to the code"]
    for bid, files in benchmark_files(baseline).items():
        hit = sorted(c for c in changed for f in files if c == f or glob_to_regex(f).match(c))
        if hit:
            touched.add(bid)
            why.append(f"{bid}: cites {', '.join(dict.fromkeys(hit))}")
    hot = sorted(c for c in changed if zone_for_path(c, cfg)[1] == "hot")
    if hot:
        touched.update(cfg["gates"]["benchmarks"])
        why.append(f"gates ({', '.join(cfg['gates']['benchmarks'])}): hot-zone files changed ({', '.join(hot)})")
    order = [b["id"] for b in load_catalog()["benchmarks"]]
    cites = sorted(why[1:], key=lambda w: order.index(w.split(":")[0]) if w.split(":")[0] in order else 99)
    return [b for b in order if b in touched], why[:1] + cites


def git_changed_files(repo: str, base: str, head: str) -> list[str] | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", repo, "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None


def carry_report(baseline: dict, read_lines, cfg: dict, commit: str, mode: str, base_commit: str | None,
                 touched: list[str] | None) -> tuple[dict, dict]:
    """The next report, started from `baseline`. touched=None means a full re-grade (every benchmark)."""
    r = copy.deepcopy(baseline)
    for key in ("rollup", "publishing"):
        r.pop(key, None)
    r["suite_version"] = load_catalog()["suite_version"]
    r["mode"] = mode
    r["run"] = {**(baseline.get("run") or {}), "commit": commit, "base_commit": base_commit, "date": utc_now()}
    r["config"] = {**(baseline.get("config") or {}), "hash": cfg["hash"], "preset": cfg["preset"], "scoring_version": cfg["suite_version"]}
    r["top_priorities"] = []
    r["commands_run"] = []
    r["integrity_flags"] = []
    regrade = set(touched) if touched is not None else {b["id"] for b in r.get("benchmarks", [])}
    if mode == "pr":
        r["limitations"] = ["PR quick mode: benchmarks marked carried_forward were not re-graded."]
    else:
        r["limitations"], r["metrics"], r["metrics_notes"] = [], {}, {}
        r["scope_examined"] = ""
    r.pop("summary", None)
    stats = {"unchanged": 0, "moved": 0, "changed": [], "lost": []}

    def move(loc, items):
        out = []
        for ev in items:
            new, outcome = relocate_evidence(ev, read_lines)
            if outcome in ("unchanged", "moved"):
                stats[outcome] += 1
            else:
                stats[outcome].append(f"{loc}: {ev.get('file')}:{ev.get('lines')}")
            out.append(new)
        return out

    for f in r.get("findings", []):
        f["evidence"] = move(f"finding {f.get('id')}", f.get("evidence", []))
        if f.get("status") == "new":
            f["status"] = "open"
    for b in r.get("benchmarks", []):
        b["previous_score"] = b.get("score")
        b["change_explanation"] = None
        for i, s in enumerate(b.get("strengths", [])):
            s["evidence"] = move(f"{b['id']} strength #{i + 1}", s.get("evidence", []))
        b["enforcement"] = move(f"{b['id']} enforcement", b.get("enforcement", []))
        if b["id"] in regrade:
            b["carried_forward"] = False
            if b.get("applicability") != "not_applicable":
                b["score"], b["confidence"] = None, None
            b["gaming_flags"] = []
        else:
            b["carried_forward"] = True
    for feat in r.get("feature_inventory", []):
        feat["evidence"] = move(f"feature '{feat.get('feature')}'", feat.get("evidence", []) or [])
    normalize_report(r, cfg)
    return r, stats


def cmd_carry(args) -> int:
    baseline = load_json(args.baseline)
    if (baseline.get("publishing") or {}).get("withheld") and not args.allow_withheld:
        die(f"{args.baseline} is a public copy: {', '.join(baseline['publishing']['withheld'])} have their evidence withheld. "
            f"Carry from the full report ({private_path(args.baseline)}), or pass --allow-withheld to keep them as they are.")
    if args.mode == "pr" and not args.base_commit:
        die("--mode pr needs --base-commit (the pull request's base)")
    args.report = args.baseline
    cfg = authoring_config(args, baseline)
    if pin_problem(cfg):
        die(pin_problem(cfg))
    read = repo_reader(args.repo)
    changed = list(args.changed or [])
    notes = []
    if args.mode == "pr" and not changed and args.base_commit:
        found = git_changed_files(args.repo, args.base_commit, args.commit)
        if found is None:
            notes.append("couldn't list the changed files with git; pass --changed FILE… or --touched ID…")
        changed = found or []
    if args.mode == "full":
        touched, why = None, ["full mode: every benchmark is re-graded"]
    else:
        touched, why = suggest_touched(baseline, changed, cfg)
        extra = [t.upper() for t in args.touched or [] if t.upper() not in touched]
        for t in extra:
            if t not in {b["id"] for b in load_catalog()["benchmarks"]}:
                die(f"--touched: unknown benchmark '{t}'")
        if extra:
            touched += extra
            why.append(f"--touched: {', '.join(extra)}")
    report, stats = carry_report(baseline, read, cfg, args.commit, args.mode, args.base_commit, touched)
    report = {"schema_version": REPORT_FORMAT, **{k: v for k, v in report.items() if k != "schema_version"}}
    report["run"].update({"started": report["run"]["date"], "grader": args.grader or report["run"].get("grader"),
                          "model": args.model, "session": args.session, "work_order": args.work_order})
    report["run"].pop("usage", None)
    pdir = project_dir_for_report(args.baseline) or project_dir_from_args(args)
    if args.out:
        out = Path(args.out)
    elif args.mode == "full" and pdir:
        out = pdir / "reports" / f"{report['run']['date'][:10]}-{args.commit[:7]}" / "report.json"
    else:
        die("give --out FILE (PR reports are written outside the grading repo)")
    if out.exists() and not args.force:
        die(f"{out} exists (use --force to replace it)")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, report)
    regrade = [b["id"] for b in report["benchmarks"] if not b.get("carried_forward")]
    result = {"report": str(out), "regrade": regrade, "why": why, "changed_files": changed, "notes": notes,
              "evidence": {"unchanged": stats["unchanged"], "moved": stats["moved"], "changed": stats["changed"], "lost": stats["lost"]}}
    lines = [f"wrote {out}", f"re-grade: {', '.join(regrade) or 'nothing'}"] + [f"  {w}" for w in why]
    lines.append(f"citations: {stats['unchanged']} unchanged, {stats['moved']} moved, {len(stats['changed'])} on lines that changed, "
                 f"{len(stats['lost'])} not found")
    lines += [f"  changed: {c} (check the finding still applies)" for c in stats["changed"]]
    lines += [f"  not found: {c} (fixed, moved elsewhere, or needs new evidence)" for c in stats["lost"]]
    lines += [f"note: {n}" for n in notes]
    lines.append(f"next: grade the benchmarks listed, update finding statuses, then `gradekit report check {out} --repo {args.repo}`")
    emit(args, result, "\n".join(lines))
    return 0


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


def match_findings(report: dict, baseline: dict, threshold: float = 0.35) -> list[dict]:
    """Pairs of (finding written fresh in this report, earlier finding it probably is)."""
    old_by_id = {f.get("id"): f for f in baseline.get("findings", [])}
    fresh = [f for f in report.get("findings", []) if f.get("id") not in old_by_id]
    have = {f.get("id") for f in report.get("findings", [])}
    missing = [f for f in baseline.get("findings", []) if f.get("id") not in have and f.get("status") != "fixed"]
    pairs = []
    for f in fresh:
        scored = sorted(((finding_similarity(f, o), o) for o in missing), key=lambda x: -x[0])
        scored = [(s, o) for s, o in scored if s >= threshold]
        if scored:
            best, o = scored[0]
            pairs.append({"new": f["id"], "old": o["id"], "similarity": best, "old_title": o.get("title"), "new_title": f.get("title"),
                          "ambiguous": len(scored) > 1 and scored[1][0] >= best - 0.1})
    claimed: dict[str, dict] = {}
    for p in sorted(pairs, key=lambda p: -p["similarity"]):
        if p["old"] in claimed:
            p["ambiguous"] = True
        else:
            claimed[p["old"]] = p
    return pairs


def rename_finding(report: dict, old_id: str, new_id: str, first_seen: str | None) -> None:
    for f in report.get("findings", []):
        if f.get("id") == old_id:
            f["id"] = new_id
            if first_seen:
                f["first_seen_commit"] = first_seen
            if f.get("status") == "new":
                f["status"] = "open"
    for b in report.get("benchmarks", []):
        b["finding_ids"] = [new_id if i == old_id else i for i in b.get("finding_ids", [])]
        for a in b.get("path_to_target", []):
            a["resolves"] = [new_id if i == old_id else i for i in a.get("resolves", [])]


def cmd_report_match(args) -> int:
    report, cfg = load_for_edit(args)
    baseline = load_json(args.baseline)
    pairs = match_findings(report, baseline, args.threshold)
    applied = []
    if args.apply:
        old = {f.get("id"): f for f in baseline.get("findings", [])}
        for p in pairs:
            if p["similarity"] >= args.apply_at and not p["ambiguous"]:
                rename_finding(report, p["new"], p["old"], old[p["old"]].get("first_seen_commit"))
                applied.append(p)
        if applied:
            save_edit(args, report, cfg)
    lines = [f"{p['new']} looks like {p['old']} ({p['similarity']:.2f}{', ambiguous' if p['ambiguous'] else ''}): "
             f"\"{p['new_title']}\" ~ \"{p['old_title']}\"" for p in pairs] or ["no likely matches"]
    if args.apply:
        lines.append(f"renamed {len(applied)}: " + (", ".join(f"{p['new']} → {p['old']}" for p in applied) or "none")
                     + f" (only unambiguous matches ≥ {args.apply_at})")
    else:
        lines.append("to keep an earlier ID: `report match … --apply`, or re-add the finding with `finding add --id OLD-ID`")
    emit(args, {"matches": pairs, "applied": [{"from": p["new"], "to": p["old"]} for p in applied]}, "\n".join(lines))
    return 0


# =========================================================================== doctor
# A preflight: everything a run will need, checked before an hour of grading rather than after.

def _check(name, status, detail, fix=None):
    return {"check": name, "status": status, "detail": detail, **({"fix": fix} if fix else {})}


def _run(cmd, cwd=None, timeout=30):
    import subprocess
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return None, "not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


def doctor_checks(args) -> list[dict]:
    import shutil
    out = []
    v = sys.version_info
    out.append(_check("python", "ok" if v >= (3, 11) else "fail", f"Python {v.major}.{v.minor}.{v.micro}",
                      None if v >= (3, 11) else "gradekit needs Python 3.11 or later (it uses tomllib)"))
    try:
        catalog = load_catalog()
        load_json(SCHEMA_PATH)
        load_toml(DEFAULTS_PATH)
        out.append(_check("kit", "ok", f"suite {catalog['suite_version']} at {SUITE_DIR}"))
    except Exception as exc:   # noqa: BLE001 - any failure here means a broken kit
        out.append(_check("kit", "fail", f"can't load the kit at {SUITE_DIR}: {exc}", "download the kit again"))
        return out
    try:
        import jsonschema  # type: ignore  # noqa: F401
        out.append(_check("jsonschema", "ok", "installed: full schema checks"))
    except ImportError:
        out.append(_check("jsonschema", "warn", "not installed: validate skips the structural schema check",
                          "pip install jsonschema (optional)"))
    tmp = Path(tempfile.gettempdir())
    try:
        with tempfile.NamedTemporaryFile(dir=tmp, prefix="gradekit-doctor-") as fh:
            fh.write(b"ok")
        out.append(_check("temp", "ok", f"can write to {tmp}"))
    except OSError as exc:
        out.append(_check("temp", "fail", f"can't write to {tmp}: {exc}", "set TMPDIR to a writable folder"))

    if args.site:
        out += doctor_site(args.site, catalog)

    pdir = project_dir_from_args(args)
    if pdir or getattr(args, "config", None):
        try:
            cfg = load_config(args, quiet=True)
            warn = cfg.get("warnings", [])
            out.append(_check("config", "warn" if warn else "ok",
                              f"{cfg['hash']} · preset {cfg['preset']}" + (f" · {len(warn)} warning(s): {'; '.join(warn)}" if warn else "")))
            pin, kit = suite_pin(cfg), major(catalog["suite_version"])
            if pin is None:
                out.append(_check("suite pin", "warn", "project.toml doesn't pin a suite version",
                                  f"add `suite = \"{kit}\"` under [project], so a new major version can't change the rules mid-cycle"))
            else:
                out.append(_check("suite pin", "fail" if pin_problem(cfg) else "ok",
                                  pin_problem(cfg) or f"pinned to {pin}; this kit is {catalog['suite_version']}"))
        except GradekitError as exc:
            out.append(_check("config", "fail", str(exc), "fix project.toml; `gradekit resolve` shows the details"))
            cfg = None
        if pdir:
            for fname in (DECISIONS_FILE, DISPOSITIONS_FILE):
                f = pdir / fname
                if f.exists():
                    try:
                        load_json(f)
                    except GradekitError as exc:
                        out.append(_check(fname, "fail", str(exc), f"fix the JSON in {f}"))
            reports = pdir / "reports"
            try:
                reports.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=reports, prefix=".gradekit-doctor-"):
                    pass
                out.append(_check("project folder", "ok", f"can write to {reports}"))
            except OSError as exc:
                out.append(_check("project folder", "fail", f"can't write to {reports}: {exc}", "check the folder's permissions"))
            found = report_folders(pdir)
            out.append(_check("previous report", "ok", f"{found[-1].name} (start with `gradekit carry`)") if found
                       else _check("previous report", "ok", "none: this is the first report (start with `gradekit report new`)"))

    if args.repo:
        repo = Path(args.repo)
        if repo.suffix == ".zip" and repo.is_file():
            out.append(_check("code repo", "ok", f"zip {repo}"))
        elif repo.is_dir():
            n = sum(1 for _ in repo.rglob("*") if ".git" not in _.parts)
            rc, head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]) if shutil.which("git") else (None, "")
            out.append(_check("code repo", "ok", f"{repo} · {n} files" + (f" · commit {head[:12]}" if rc == 0 else " · not a git checkout")))
        else:
            out.append(_check("code repo", "fail", f"not found: {repo}", "pass the code checkout (or a zip of it) with --repo"))

    if args.delivery == "pr":
        out += doctor_git(args, pdir)
    return out


def doctor_site(site: str, catalog: dict) -> list[dict]:
    import urllib.request
    url = site.rstrip("/") + "/manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            man = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:   # noqa: BLE001 - any network failure is the finding
        return [_check("suite website", "fail", f"can't fetch {url}: {exc}",
                       "check the address, and that this sandbox may reach it (network allowlist or proxy)")]
    out = []
    ver = man.get("version")
    out.append(_check("suite website", "ok" if ver == catalog["suite_version"] else "warn",
                      f"{site} serves {ver}; this kit is {catalog['suite_version']}",
                      None if ver == catalog["suite_version"] else "use the kit the website serves (its download link), so prompts and tools match"))
    if ver == catalog["suite_version"]:
        changed = []
        for f in man.get("files", []):
            rel = str(f.get("path", ""))
            if rel.startswith("suite/"):
                local = SUITE_DIR / rel[len("suite/"):]
                if local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() != f.get("sha256"):
                    changed.append(rel[len("suite/"):])
        out.append(_check("kit files", "warn" if changed else "ok",
                          f"{len(changed)} differ from the website's copy: {', '.join(changed[:5])}" if changed else "match the website's copy",
                          "download the kit again if you didn't change these on purpose" if changed else None))
    return out


def doctor_git(args, pdir) -> list[dict]:
    import shutil
    out = []
    if not shutil.which("git"):
        return [_check("git", "fail", "not installed", "pr delivery needs git; or use --delivery save or return")]
    root = pdir or Path(args.grading_repo or ".")
    rc, top = _run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if rc != 0:
        return [_check("grading repo", "fail", f"{root} is not in a git checkout",
                       "clone the grading repo, or use --delivery save or return")]
    out.append(_check("grading repo", "ok", top))
    name = _run(["git", "-C", top, "config", "user.name"])[1]
    email = _run(["git", "-C", top, "config", "user.email"])[1]
    out.append(_check("git identity", "ok" if name and email else "fail", f"{name or '?'} <{email or '?'}>",
                      None if name and email else "git config user.name … && git config user.email …"))
    rc, url = _run(["git", "-C", top, "remote", "get-url", args.remote])
    if rc != 0:
        out.append(_check("remote", "fail", f"no remote '{args.remote}'", f"git remote add {args.remote} URL, or pass --remote"))
        return out
    rc, msg = _run(["git", "-C", top, "ls-remote", "--symref", args.remote, "HEAD"], timeout=60)
    if rc != 0:
        out.append(_check("remote read", "fail", f"can't read {url}: {msg.splitlines()[-1] if msg else ''}",
                          "check the address and the credentials this sandbox uses"))
        return out
    head = re.search(r"ref: refs/heads/(\S+)\s+HEAD", msg)
    out.append(_check("remote read", "ok", f"{url} (default branch {head.group(1) if head else 'unknown'})"))
    probe = f"refs/heads/gradekit-doctor-{os.getpid()}"
    rc, msg = _run(["git", "-C", top, "push", "--dry-run", "--quiet", args.remote, f"HEAD:{probe}"], timeout=60)
    out.append(_check("remote push", "ok" if rc == 0 else "fail",
                      "push allowed (dry run)" if rc == 0 else f"push refused (dry run): {msg.splitlines()[-1] if msg else ''}",
                      None if rc == 0 else "the grader needs permission to push branches to the grading repo"))
    if args.open:
        tool = {"github": "gh", "gitlab": "glab"}[args.open]
        rc, msg = _run([tool, "auth", "status"])
        out.append(_check(tool, "ok" if rc == 0 else "fail",
                          "signed in" if rc == 0 else (msg.splitlines()[-1].strip(" -") if msg else "not signed in"),
                          None if rc == 0 else f"{tool} auth login, or open the pull request by hand (drop --open)"))
    return out


def cmd_doctor(args) -> int:
    checks = doctor_checks(args)
    mark = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
    lines = []
    for c in checks:
        lines.append(f"{mark[c['status']]}  {c['check']:<16} {c['detail']}")
        if c.get("fix"):
            lines.append(f"      {'':<16} → {c['fix']}")
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    lines.append(f"\n{'ready' if not fails else 'not ready'}: {len(fails)} problem(s), {len(warns)} warning(s)")
    emit(args, {"ready": not fails, "checks": checks}, "\n".join(lines))
    return 1 if fails else 0


# =========================================================================== deliver
# Hands a finished report back in one of the grader's three deliveries (pr, save, return). The
# preparation is the same for all: finished, redacted if the grading repo is public, safe to
# publish, report.md rendered. For pr, the git steps are printed, or run with --run. Pushing and
# opening the pull request are separate opt-ins, because those depend on where the repo is hosted.

def git_out(cwd, *args, check=True) -> str:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        die(f"git {' '.join(args)}: {exc}")
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def default_branch(root, remote: str) -> str:
    ref = git_out(root, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD", check=False)
    if ref:
        return ref
    for cand in (f"{remote}/main", f"{remote}/master", "main", "master"):
        if git_out(root, "rev-parse", "--verify", "--quiet", cand, check=False):
            return cand
    die("can't tell the grading repo's default branch; pass --base BRANCH")


def prepare_delivery(args, report: dict, cfg: dict) -> dict:
    """Everything every delivery needs. Returns the file paths, or dies with what's left to do."""
    normalize_report(report, cfg)
    errors, _ = validate_report(report, cfg, load_catalog())
    todo = report_todo(report, project_dir_for_report(args.report))
    if args.repo:
        errors += [f"citation: {f}" for f in verify_evidence(report, repo_reader(args.repo), 2)["failures"]]
    if errors or todo:
        args._exit = 1 if errors else EXIT_INCOMPLETE
        raise DeliveryBlocked(errors, todo)
    if not report.get("rollup") or report["rollup"].get("config_hash") != cfg["hash"]:
        apply_rollup(report, cfg)
    write_json(args.report, report)
    files = {"report": args.report, "private": None}
    public = bool((cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"))
    if public and not (report.get("publishing") or {}).get("redacted"):
        pub, leaks = redact_report(report)
        if leaks:
            args._exit = 1
            raise DeliveryBlocked([f"leak: {x}" for x in leaks], [])
        priv = private_path(args.report)
        write_json(priv, report)
        write_json(args.report, pub)
        report = pub
    if Path(private_path(args.report)).exists():
        files["private"] = private_path(args.report)
    if public:
        problems = publish_problems(report)
        if problems:
            args._exit = 1
            raise DeliveryBlocked([f"publish: {p}" for p in problems], [])
    md = re.sub(r"\.json$", "", args.report) + ".md"
    Path(md).write_text(render_report_md(report, cfg), encoding="utf-8")
    files["markdown"] = md
    files["components"] = prepare_components(Path(args.report).parent, public, args)
    files["report_obj"] = report
    return files


def prepare_components(folder: Path, public: bool, args) -> list[str]:
    """A monorepo report's components/NAME.json: each finished, redacted when public, with its report.md."""
    done = []
    for cp in component_reports(folder):
        r = load_json(cp)
        ns = argparse.Namespace(report=str(cp), config=None, project=None, project_dir=None, component=None, grading_repo=None)
        ccfg = authoring_config(ns, r)
        errors, _ = validate_report(r, ccfg, load_catalog())
        todo = report_todo(r, project_dir_for_report(cp))
        if errors or todo:
            args._exit = 1 if errors else EXIT_INCOMPLETE
            raise DeliveryBlocked([f"components/{cp.name}: {e}" for e in errors], [f"components/{cp.name}: {x}" for x in todo])
        if public and not (r.get("publishing") or {}).get("redacted"):
            pub, leaks = redact_report(r)
            if leaks:
                args._exit = 1
                raise DeliveryBlocked([f"components/{cp.name}: leak: {x}" for x in leaks], [])
            write_json(private_path(str(cp)), r)
            write_json(cp, pub)
            r = pub
        cp.with_suffix(".md").write_text(render_report_md(r, ccfg), encoding="utf-8")
        done.append(str(cp))
    return done


class DeliveryBlocked(Exception):
    def __init__(self, errors, todo):
        super().__init__("report not ready")
        self.errors, self.todo = errors, todo


def cmd_deliver(args) -> int:
    report = load_json(args.report)
    cfg = authoring_config(args, report)
    if (args.push or args.open) and not args.run:
        die("--push and --open need --run")
    if args.open and not args.push:
        die("--open needs --push (the branch must be on the host first)")
    try:
        files = prepare_delivery(args, report, cfg)
    except DeliveryBlocked as b:
        lines = [f"ERROR: {e}" for e in b.errors] + [f"todo:  {t}" for t in b.todo]
        lines.append(f"\nnot delivered: {len(b.errors)} error(s), {len(b.todo)} to do (`gradekit report check` lists the same)")
        emit(args, {"delivered": False, "errors": b.errors, "todo": b.todo}, "\n".join(lines))
        return args._exit
    report = files.pop("report_obj")
    folder = Path(args.report).resolve().parent
    if folder.name == "runs":
        die("deliver the consensus report.json, not one run (see `gradekit stability`)")
    pr = render_report_pr(report, cfg, args.site, args.grading_repo_url, args.branch, folder.name)
    result = {"delivered": False, "delivery": args.delivery, "files": files, "title": pr["title"]}
    lines = [f"ready: {files['report']}" + (f" (public copy; full report in {files['private']})" if files["private"] else ""),
             f"wrote {files['markdown']}"]
    private_note = (f"keep {files['private']} private: never commit it or paste it into a pull request; "
                    f"hand it to whoever fixes the code") if files["private"] else None

    if args.delivery == "return":
        blocks = [("report.json", Path(files["report"]).read_text(encoding="utf-8"), "json"),
                  ("report.md", Path(files["markdown"]).read_text(encoding="utf-8"), "markdown")]
        if files["private"]:
            blocks.append(("report.private.json (private: don't commit)", Path(files["private"]).read_text(encoding="utf-8"), "json"))
        result.update(delivered=True, blocks=[{"name": n, "content": c} for n, c, _ in blocks])
        lines.append("\nReturn these in your final message, each in its own fenced block:")
        for name, content, lang in blocks:
            lines += ["", f"**{name}**", f"````{lang}", content.rstrip("\n"), "````"]
        emit(args, result, "\n".join(lines))
        return 0

    if args.delivery == "save":
        result["delivered"] = True
        result["folder"] = str(folder)
        lines.append(f"saved in {folder}")
        if private_note:
            lines.append(private_note)
        emit(args, result, "\n".join(lines))
        return 0

    # ---- pr
    root = Path(git_out(folder, "rev-parse", "--show-toplevel"))
    rel = folder.relative_to(root.resolve()).as_posix()
    base = args.base or default_branch(root, args.remote)
    branch = pr["branch"]
    base_name = base.split("/", 1)[1] if base.startswith(args.remote + "/") else base
    if branch in (base, base_name):
        die("refusing to deliver onto the default branch; reports go through a pull request")
    body_file = Path(args.body_file) if args.body_file else Path(tempfile.gettempdir()) / f"gradekit-{branch.replace('/', '_')}.md"
    body_file.write_text(pr["body"], encoding="utf-8")
    msg = f"{pr['title']}\n\n{(report.get('summary') or '').strip()}".strip()
    only = [rel, f":(exclude){rel}/**/*.private.json", f":(exclude){rel}/*.private.json"]   # never the private report
    steps = [["git", "-C", str(root), "switch", "-c", branch, base],
             ["git", "-C", str(root), "add", "--", *only],
             ["git", "-C", str(root), "commit", "-m", msg, "--", *only]]
    if args.push:
        steps.append(["git", "-C", str(root), "push", "-u", args.remote, branch])
    if args.open == "github":
        steps.append(["gh", "pr", "create", "--base", base_name, "--head", branch,
                      "--title", pr["title"], "--body-file", str(body_file)])
    elif args.open == "gitlab":
        steps.append(["glab", "mr", "create", "--source-branch", branch, "--target-branch", base_name,
                      "--title", pr["title"], "--description", pr["body"], "--yes"])
    result.update(branch=branch, base=base_name, body_file=str(body_file), commands=[shell_join(s) for s in steps])
    if not args.run:
        lines += ["", f"pull request: {pr['title']}", f"branch {branch} from {base}; body in {body_file}", "",
                  "run these (or `gradekit deliver … --run`), then open a pull request from that branch with that title and body:"]
        lines += [f"  {shell_join(s)}" for s in steps]
        if private_note:
            lines += ["", private_note]
        emit(args, result, "\n".join(lines))
        return 0

    import subprocess
    current = git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current == branch:
        steps = steps[1:]          # already on the report branch (a re-run)
    elif git_out(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        die(f"branch {branch} already exists; switch to it, or delete it, and run again")
    url = None
    for s in steps:
        r = subprocess.run(s, capture_output=True, text=True, cwd=str(root), timeout=300)
        if r.returncode != 0:
            msg_ = (r.stderr or r.stdout).strip()
            if s[3:5] == ["commit", "-m"] and re.search(r"nothing (added )?to commit", r.stdout + r.stderr):
                continue
            if "user.email" in msg_ or "Author identity unknown" in msg_:
                msg_ += "\n(set the committer: git config user.name … and git config user.email …)"
            die(f"`{shell_join(s)}` failed:\n{msg_}")
        found = re.findall(r"https?://\S+", r.stdout)
        if s[0] in ("gh", "glab") and found:
            url = found[-1]
    staged = git_out(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    leaked = [f for f in staged if f.endswith(".private.json")]
    if leaked:
        die(f"a private report was committed ({', '.join(leaked)}): undo with `git reset --soft HEAD~1` before pushing")
    result.update(delivered=True, commit=git_out(root, "rev-parse", "HEAD"), pushed=bool(args.push), url=url)
    lines += ["", f"pull request title: {pr['title']}", f"committed {rel} on {branch}" + (f" and pushed to {args.remote}" if args.push else "")]
    if url:
        lines.append(f"pull request: {url}")
    elif args.push:
        lines.append(f"open a pull request from {branch} into {base_name} with that title and the body in {body_file}")
    else:
        lines.append(f"next: push {branch} and open a pull request into {base_name} with that title and the body in {body_file}")
    if private_note:
        lines.append(private_note)
    emit(args, result, "\n".join(lines))
    return 0


def shell_join(parts) -> str:
    import shlex
    return " ".join(shlex.quote(str(p)) for p in parts)


# =========================================================================== migrate (4.x → 5)
# One pull request moves a project to this kit's major: the pin in project.toml and, with --reports, its
# reports in format 5. The change is mechanical and deterministic, so `gradekit ci` checks a migration pull
# request by redoing it from the base branch's files. Scores and rollups are never touched.

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


def scoring_version_4x(kit: str) -> str:
    """The scoring rules a 4.x kit used: 4.0.0 and 4.1.0, then 4.2.0 from 4.2.0 on."""
    m = re.fullmatch(r"4\.(\d+)\.\d+", str(kit or ""))
    return f"4.{min(int(m.group(1)), 2)}.0" if m else str(kit or "0")


def migrate_report(report: dict, private: dict | None = None) -> tuple[dict, list[str]]:
    """A 4.x report in format 5, with its judgments, scores and rollup unchanged. `private` is the full report
    of a public copy, if there is one: its findings give the withheld ones their fingerprints."""
    if report_format(report) >= 5:
        return report, []
    notes = []
    r = {"schema_version": REPORT_FORMAT, **copy.deepcopy(report)}
    r["suite_version"] = kit_version()
    r["migrated"] = {"from": report.get("suite_version"), "by": kit_version()}
    run = r["run"] = dict(r.get("run") or {})
    date = utc_stamp(run.get("date"))
    if date is None:
        die(f"run.date {run.get('date')!r} isn't a date; fix it in the report first")
    if date != run.get("date"):
        notes.append(f"run.date {run.get('date')} → {date}")
    run["date"] = date
    run.setdefault("started", date)
    for key in ("model", "session", "work_order"):
        run.setdefault(key, None)
    r["config"] = {**(r.get("config") or {})}
    r["config"].setdefault("scoring_version", scoring_version_4x(report.get("suite_version")))
    base = str(run.get("base_commit") or "")
    full = {f.get("id"): f for f in (private or {}).get("findings", [])}
    for f in r.get("findings", []):
        seen = str(f.get("first_seen_commit") or "")
        if r.get("mode") == "pr" and f.get("status") == "new" and base and seen and (seen.startswith(base) or base.startswith(seen)):
            f["status"] = "noticed"
            notes.append(f"{f['id']}: new → noticed (first seen at the base commit: it was already there)")
        if withheld(f):
            if f.get("id") in full:
                f["fingerprint"] = fingerprint_of(full[f["id"]])
        else:
            f["fingerprint"] = fingerprint_of(f)
    return r, notes


def set_pin_text(text: str, pin: str) -> str:
    """project.toml with `suite = "PIN"` under [project], changing only that line (comments survive)."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "[project]"), None)
    if start is None:
        die("project.toml has no [project] table")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    line = f'{"suite":<15} = "{pin}"   # the suite\'s major version for this project; tools won\'t write its reports with another\n'
    for i in range(start + 1, end):
        if re.match(r"\s*suite\s*=", lines[i]):
            lines[i] = line
            return "".join(lines)
    at = next((i + 1 for i in range(start + 1, end) if re.match(r"\s*preset\s*=", lines[i])), start + 1)
    lines.insert(at, line)
    return "".join(lines)


MIGRATE_REPORT_FILES = re.compile(r"(report\.json|report\.private\.json|runs/[^/]+\.json)")


def migration_plan(pdir: Path, cfg: dict, with_reports: bool) -> list[dict]:
    """Every file `migrate` changes: {path, text, notes, private}. Paths are relative to the project folder."""
    out = []
    toml = (pdir / PROJECT_FILE).read_text(encoding="utf-8")
    new_toml = set_pin_text(toml, major(kit_version()))
    if new_toml != toml:
        out.append({"path": PROJECT_FILE, "text": new_toml, "notes": [f"suite = \"{major(kit_version())}\""], "private": False})
    if not with_reports:
        return out
    for folder in report_folders(pdir):
        private_path_ = folder / "report.private.json"
        private = load_json(private_path_) if private_path_.exists() else None
        migrated_main = None
        for f in [folder / "report.json", private_path_, *sorted((folder / "runs").glob("*.json"))]:
            if not f.exists():
                continue
            src = load_json(f)
            if report_format(src) >= 5:
                continue
            new, notes = migrate_report(src, private if f.name == "report.json" else None)
            rel = f.relative_to(pdir).as_posix()
            out.append({"path": rel, "text": json.dumps(new, indent=2, ensure_ascii=False) + "\n", "notes": notes,
                        "private": f.name.endswith(".private.json"), "report": new, "before": src})
            if f.name == "report.json":
                migrated_main = new
        if migrated_main is not None:
            md = migrated_report_md(migrated_main, cfg)
            if md is not None and (folder / "report.md").exists():
                out.append({"path": (folder / "report.md").relative_to(pdir).as_posix(), "text": md, "notes": [], "private": False})
    return out


def migrated_report_md(report: dict, cfg: dict) -> str | None:
    """report.md for a migrated report, or None to leave the old one (a report graded under an older config)."""
    try:
        return render_report_md(report, cfg)
    except GradekitError:
        return None


def same_migration(expected: dict, actual: dict) -> bool:
    """A migration made by another 5.x kit (5.0.1, say) differs only in which 5.x it names."""
    e = copy.deepcopy(expected)
    have = {f.get("id"): f for f in actual.get("findings", []) if isinstance(f, dict)}
    for f in e.get("findings", []):   # a withheld finding's fingerprint comes from the private report, which CI never sees
        if withheld(f) and "fingerprint" not in f and "fingerprint" in have.get(f.get("id"), {}):
            f["fingerprint"] = have[f["id"]]["fingerprint"]
    if major(actual.get("suite_version", "")) == major(e.get("suite_version", "")):
        e["suite_version"] = actual.get("suite_version")
        if isinstance(actual.get("migrated"), dict) and isinstance(e.get("migrated"), dict):
            e["migrated"]["by"] = actual["migrated"].get("by")
    return e == actual


def cmd_migrate(args) -> int:
    pdir = project_dir_from_args(args)
    if pdir is None:
        die("give --project NAME (in a grading repo) or --project-dir DIR")
    cfg = load_config(args, quiet=True)
    pin, kit = suite_pin(cfg), major(kit_version())
    if pin and int(pin) > int(kit):
        die(f"this project is pinned to suite {pin}, newer than this kit ({kit_version()}); use a {pin}.x kit")
    if (args.push or args.open) and not args.run:
        die("--push and --open need --run")
    if args.open and not args.push:
        die("--open needs --push (the branch must be on the host first)")
    plan = migration_plan(pdir, cfg, args.reports)
    lines, checks = [], []
    for item in plan:
        if "report" in item:
            before, after = item["before"], item["report"]
            b, a = (before.get("rollup") or {}), (after.get("rollup") or {})
            same = (b.get("overall_score"), (b.get("maturity") or {}).get("current_level")) == \
                   (a.get("overall_score"), (a.get("maturity") or {}).get("current_level"))
            checks.append(same)
        lines.append(f"  {item['path']}" + (" (private, never committed)" if item["private"] else "")
                     + (f": {'; '.join(item['notes'])}" if item["notes"] else ""))
    result = {"project": pdir.name, "pin": kit, "files": [{"path": i["path"], "notes": i["notes"], "private": i["private"]} for i in plan],
              "scores_unchanged": all(checks), "written": False}
    if not plan:
        emit(args, result, f"{pdir.name} is already on suite {kit}" + ("" if args.reports else " (add --reports to also upgrade its reports)"))
        return 0
    head = [f"migrate {pdir.name} to suite {kit}: {len(plan)} file(s)" + ("" if args.reports else " (the pin only; --reports also upgrades its reports)")]
    if checks:
        head.append(f"scores and rollups: {'unchanged' if all(checks) else 'CHANGED, which a migration must never do'} in {len(checks)} report(s)")
    if not (args.write or args.run):
        emit(args, result, "\n".join(head + lines + ["", "dry run: nothing written. --write writes them here; --run makes a branch and commits"]))
        return 0
    if not all(checks):
        die("a migrated report's stored rollup differs from the original; nothing written")
    import subprocess
    root = Path(git_out(pdir, "rev-parse", "--show-toplevel", check=False) or ".")
    in_git = (root / ".git").exists()
    branch = args.branch or f"migrate/{pdir.name}-v{kit}"
    title = f"Migrate {pdir.name} to suite {kit}"
    steps = []
    if args.run:
        if not in_git:
            die("--run needs the grading repo to be a git checkout")
        base = args.base or default_branch(root, args.remote)
        if git_out(root, "status", "--porcelain", check=False):
            die("the grading repo has uncommitted changes; commit or stash them first")
        r = subprocess.run(["git", "-C", str(root), "switch", "-c", branch, base], capture_output=True, text=True)
        if r.returncode != 0:
            die(f"git switch -c {branch} {base} failed: {(r.stderr or r.stdout).strip()}")
    elif in_git:
        current = git_out(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        base_name = (args.base or default_branch(root, args.remote)).split("/")[-1]
        if current == base_name:
            die(f"refusing to write on {current}: a migration goes through a pull request. Switch to a branch, or use --run")
    for item in plan:
        (pdir / item["path"]).write_text(item["text"], encoding="utf-8")
    result["written"] = True
    if args.run:
        rels = [(pdir / i["path"]).resolve().relative_to(root.resolve()).as_posix() for i in plan if not i["private"]]
        body = "\n".join([f"Moves `{pdir.name}` to suite {kit} with `gradekit migrate`" + (" --reports" if args.reports else "") + ".", "",
                          "- the pin: `suite = \"" + kit + "\"` in project.toml"]
                         + (["- its reports in format 5: scores and rollups unchanged; `gradekit ci` checks this by redoing it"] if args.reports else [])
                         + ["", "Revert this pull request to undo it."]) + "\n"
        body_file = Path(tempfile.gettempdir()) / f"gradekit-{branch.replace('/', '_')}.md"
        body_file.write_text(body, encoding="utf-8")
        steps = [["git", "-C", str(root), "add", "--", *rels], ["git", "-C", str(root), "commit", "-m", title, "--", *rels]]
        if args.push:
            steps.append(["git", "-C", str(root), "push", "-u", args.remote, branch])
        base_name = (args.base or default_branch(root, args.remote)).split("/")[-1]
        if args.open == "github":
            steps.append(["gh", "pr", "create", "--base", base_name, "--head", branch, "--title", title, "--body-file", str(body_file)])
        elif args.open == "gitlab":
            steps.append(["glab", "mr", "create", "--source-branch", branch, "--target-branch", base_name, "--title", title,
                          "--description", body, "--yes"])
        for s in steps:
            r = subprocess.run(s, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                die(f"`{shell_join(s)}` failed:\n{(r.stderr or r.stdout).strip()}")
        result.update(branch=branch, commit=git_out(root, "rev-parse", "HEAD"), pushed=bool(args.push), title=title, body_file=str(body_file))
        tail = [f"committed on {branch}" + (f" and pushed to {args.remote}" if args.push else "") + f"; open a pull request titled "
                f"\"{title}\" with the body in {body_file}" if not args.open else f"opened a pull request: {title}"]
    else:
        tail = [f"wrote them; commit them on a branch and open a pull request titled \"{title}\""]
    if any(i["private"] for i in plan):
        tail.append("report.private.json files were upgraded in place; they stay out of git")
    emit(args, result, "\n".join(head + lines + [""] + tail))
    return 0


def check_migration(root: Path, mb: str, changes: list[tuple[str, str]]) -> dict | None:
    """If a pull request is a migration (only edits to one project's reports, plus its pin), check each file is
    exactly what `gradekit migrate` makes from the base branch's version. None if it isn't one."""
    paths = [(s, p) for s, p in changes if p != f"projects/{INDEX_FILE}"]
    rx = re.compile(r"projects/([^/]+)/reports/([^/]+)/(report\.json|report\.md|runs/[^/]+\.json)")
    reports = [(s, p) for s, p in paths if rx.fullmatch(p)]
    projects_ = {p.split("/")[1] for _, p in paths if p.startswith("projects/")}
    if not reports or len(projects_) != 1:
        return None
    proj = next(iter(projects_))
    toml_path = f"projects/{proj}/{PROJECT_FILE}"
    if any(p != toml_path and (s, p) not in reports for s, p in paths) or any(s != "M" for s, _ in reports):
        return None
    problems, notes = [], []
    pdir = root / "projects" / proj
    try:
        cfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), quiet=True)
    except GradekitError as exc:
        return {"project": proj, "problems": [f"config: {exc}"], "notes": [], "reports": 0}
    if suite_pin(cfg) != major(kit_version()):
        problems.append(f"a migration pins the project to this suite: `suite = \"{major(kit_version())}\"` in {toml_path}")
    if any(p == toml_path for _, p in paths):
        before = file_at(root, mb, toml_path)
        if before is None or set_pin_text(before, major(kit_version())) != (root / toml_path).read_text(encoding="utf-8"):
            problems.append(f"{toml_path}: a migration changes only the `suite` line (send other settings changes on their own)")
    expected_json = {}
    for s, p in reports:
        if p.endswith(".json"):
            base_text = file_at(root, mb, p)
            try:
                want, _ = migrate_report(json.loads(base_text or "{}"))
                have = load_json(root / p)
            except (GradekitError, json.JSONDecodeError) as exc:
                problems.append(f"{p}: {exc}")
                continue
            if not same_migration(want, have):
                problems.append(f"{p} isn't what `gradekit migrate` makes from the base branch's version: reports are never "
                                "edited by hand, so run `gradekit migrate --reports` on a fresh branch")
            elif p.endswith("/report.json"):
                expected_json[p.rsplit("/", 1)[0]] = have
    for s, p in reports:
        if p.endswith("/report.md"):
            folder = p.rsplit("/", 1)[0]
            rep = expected_json.get(folder) or (load_json(root / folder / "report.json") if (root / folder / "report.json").exists() else None)
            md = migrated_report_md(rep, cfg) if rep else None
            if md is None or md != (root / p).read_text(encoding="utf-8"):
                problems.append(f"{p} isn't the report.md that `gradekit render report` makes from the migrated report")
    if any(p.endswith(".private.json") for _, p in reports):
        problems.append("a private report is in the pull request: it must never be committed")
    return {"project": proj, "problems": problems, "notes": notes,
            "reports": sum(1 for _, p in reports if p.endswith("/report.json"))}




# =========================================================================== disputes
# A person who thinks a finding is wrong disputes it in projects/NAME/disputes.json (append-only). The next
# grader must answer: uphold it (with a note saying why it stands) or withdraw it (status `withdrawn`, which
# counts nowhere). An answer names the dispute's date, so the dispute is closed by the report that answers it.

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
    if report_format(report) < 5:
        die("answering a dispute needs a format-5 report (suite 5.x)")
    pdir = project_dir_for_report(args.report) or project_dir_from_args(args)
    mine = [d for d in open_disputes(pdir, report) if d.get("finding_id") == args.id]
    if not mine:
        die(f"no open dispute on {args.id} in {DISPUTES_FILE}")
    d = mine[-1]
    f["dispute"] = {"answer": "withdrawn" if args.withdraw else "upheld", "note": args.note, "disputed_on": d["date"], "by": d.get("by")}
    if args.withdraw:
        f["status"] = "withdrawn"
    save_edit(args, report, cfg)
    emit(args, {"id": f["id"], "dispute": f["dispute"]},
         f"{f['id']}: dispute {'withdrawn: the finding no longer counts' if args.withdraw else 'upheld'}")
    return 0


# =========================================================================== calibration program
# Golden repos, frozen at a commit, with expected scores a person set; several independent grader runs each.
# `gradekit calibration run` scores every run against its golden's expected scores, measures the spread across
# runs, and writes calibration/results.json and RESULTS.md. The results carry a fingerprint of the scoring rules,
# and a kit test fails when the rules change without the results being regenerated: no scoring change ships
# unmeasured.

GOLDEN_DIR = SUITE_DIR / "calibration" / "golden"
CALIBRATION_RESULTS = SUITE_DIR / "calibration" / "results.json"
CALIBRATION_MD = SUITE_DIR / "calibration" / "RESULTS.md"


def calibrate_scores(scores: dict, exp: dict) -> dict:
    """One run's {benchmark: {score, applicability}} against a golden's expected scores."""
    crit = {"within_tolerance_pct": 90, "mae_max": 0.75, **exp.get("criteria", {})}
    total = within = 0
    errs, mism, deltas, rows = [], [], [], []
    for bid, e in sorted(exp.get("expected", {}).items()):
        b = scores.get(bid) or {}
        actual = b.get("score")
        if e.get("applicability") and e["applicability"] != b.get("applicability"):
            mism.append(f"{bid}: expected {e['applicability']}, got {b.get('applicability')}")
        if e.get("score") is None or actual is None:
            continue
        tol = e.get("tolerance", 1)
        d = actual - e["score"]
        total += 1
        within += abs(d) <= tol
        errs.append(abs(d))
        deltas.append(d)
        rows.append({"benchmark": bid, "expected": e["score"], "actual": actual, "delta": d, "within": abs(d) <= tol})
    if not total:
        die("no comparable benchmarks")
    pct, mae, bias = 100 * within / total, sum(errs) / total, sum(deltas) / total
    ok = pct >= crit["within_tolerance_pct"] and mae <= crit["mae_max"] and not mism
    return {"pass": ok, "within_tolerance_pct": round(pct, 1), "mae": round(mae, 3), "bias": round(bias, 3), "compared": total,
            "applicability_mismatches": mism, "criteria": crit, "rows": rows}


def run_scores(report: dict) -> dict:
    return {b["id"]: {"score": b.get("score"), "applicability": b.get("applicability")} for b in report.get("benchmarks", [])}


def scoring_fingerprint() -> str:
    """What calibration measures: the scoring version, every benchmark's rubric (measures, boundaries, anchors,
    caps) and the computed limits. A change to any of them needs calibration to be run again."""
    rub = parse_rubric()
    body = {"scoring_version": load_toml(DEFAULTS_PATH).get("suite_version"),
            "benchmarks": [{k: b.get(k) for k in ("id", "measures", "not_this", "assess", "anchors", "caps")} for b in rub["benchmarks"]],
            "limits": [CRITICAL_MAX, NO_STRENGTH_MAX, NO_ENFORCEMENT_MAX, sorted(AUTO_CAPS)]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def calibration_results(golden_dir: Path, min_runs: int = 3) -> dict:
    goldens = []
    for d in sorted(p for p in golden_dir.iterdir() if (p / "expected.json").exists()) if golden_dir.is_dir() else []:
        exp = load_json(d / "expected.json")
        runs = []
        for f in sorted((d / "runs").glob("*.json"), key=lambda p: (len(p.name), p.name)) if (d / "runs").is_dir() else []:
            run = load_json(f)
            res = calibrate_scores(run.get("scores") or {}, exp)
            runs.append({"run": f.stem, "model": run.get("model"), "graded": run.get("graded"),
                         **{k: res[k] for k in ("pass", "within_tolerance_pct", "mae", "bias", "applicability_mismatches")}})
        max_spread = exp.get("criteria", {}).get("max_spread", 1)
        spread, unstable = {}, []
        for bid in sorted(exp.get("expected", {})):
            vals = [((load_json(f).get("scores") or {}).get(bid) or {}).get("score") for f in sorted((d / "runs").glob("*.json"))] \
                if (d / "runs").is_dir() else []
            vals = [v for v in vals if isinstance(v, int)]
            if len(vals) >= 2:
                spread[bid] = max(vals) - min(vals)
                if spread[bid] > max_spread:
                    unstable.append(bid)
        enough = len(runs) >= min_runs
        goldens.append({"name": d.name, "reference": exp.get("reference"), "set_by": exp.get("set_by"), "runs": runs,
                        "runs_needed": min_runs, "max_spread": max_spread,
                        "spread": {"largest": max(spread.values()) if spread else None,
                                   "mean": round(sum(spread.values()) / len(spread), 2) if spread else None, "unstable": unstable},
                        "pass": enough and bool(runs) and all(r["pass"] for r in runs) and not unstable,
                        "status": "pass" if enough and all(r["pass"] for r in runs) and not unstable
                                  else ("needs more runs" if not enough else "fail")})
    return {"_about": "Written by `gradekit calibration run`. Don't edit: a kit test checks it matches the golden runs and the "
                      "current scoring rules.", "scoring_version": load_toml(DEFAULTS_PATH).get("suite_version"),
            "scoring_fingerprint": scoring_fingerprint(), "min_runs": min_runs,
            "pass": bool(goldens) and all(g["pass"] for g in goldens), "goldens": goldens}


def calibration_markdown(res: dict) -> str:
    out = ["# Calibration results", "",
           f"Generated by `gradekit calibration run` (scoring version {res['scoring_version']}, "
           f"rules fingerprint `{res['scoring_fingerprint']}`). Don't edit.", "",
           f"**Overall: {'PASS' if res['pass'] else 'not passed yet'}.** Each golden repo needs at least {res['min_runs']} independent runs; "
           "every run must be within tolerance of the expected scores, and no benchmark may spread more than its golden allows across runs.", ""]
    for g in res["goldens"]:
        out += [f"## {g['name']}: {g['status']}", "", f"{g['reference'] or ''}" + (f". Expected scores set by {g['set_by']}." if g.get("set_by") else ""), "",
                "| Run | Model | Within tolerance | MAE | Bias | Result |", "|---|---|:-:|:-:|:-:|---|"]
        out += [f"| {r['run']} | {r['model'] or '?'} | {r['within_tolerance_pct']:g}% | {r['mae']:g} | {r['bias']:+g} | "
                f"{'pass' if r['pass'] else 'fail'}{' (' + '; '.join(r['applicability_mismatches']) + ')' if r['applicability_mismatches'] else ''} |"
                for r in g["runs"]] or ["| none yet | | | | | |"]
        sp = g["spread"]
        out += ["", f"Runs: {len(g['runs'])} of {g['runs_needed']}. Spread across runs: "
                + (f"largest {sp['largest']}, mean {sp['mean']}" if sp["largest"] is not None else "needs at least two runs")
                + (f"; above {g['max_spread']} on {', '.join(sp['unstable'])}" if sp["unstable"] else "") + ".", ""]
    if not res["goldens"]:
        out += ["No golden repos yet: see README.md.", ""]
    return "\n".join(out)


def cmd_calibration_add_run(args) -> int:
    golden = Path(args.golden)
    exp = load_json(golden / "expected.json")
    report = load_json(args.report)
    commit, want = str((report.get("run") or {}).get("commit") or ""), str(exp.get("commit") or "")
    if want and not (commit.startswith(want) or want.startswith(commit)):
        die(f"{args.report} grades {commit[:7]}, but this golden repo is frozen at {want[:7]}")
    runs = golden / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(m.group(1)) for f in runs.glob("run-*.json") if (m := re.fullmatch(r"run-(\d+)\.json", f.name))] or [0])
    run = report.get("run") or {}
    data = {"graded": run.get("date"), "commit": commit, "suite_version": report.get("suite_version"),
            "scoring_version": scoring_version_of(report), "grader": run.get("grader"), "model": run.get("model"),
            "session": run.get("session"), "note": args.note, "scores": run_scores(report)}
    out = runs / f"run-{n}.json"
    write_json(out, {k: v for k, v in data.items() if v is not None})
    emit(args, {"written": str(out)}, f"wrote {out}; then `gradekit calibration run` to update the results")
    return 0


def cmd_calibration_run(args) -> int:
    res = calibration_results(Path(args.golden_dir), args.min_runs)
    text = json.dumps(res, indent=2, ensure_ascii=False) + "\n"
    md = calibration_markdown(res) + "\n"
    out, mdo = Path(args.out), Path(args.markdown)
    if args.check:
        stale = [str(p) for p, want in ((out, text), (mdo, md)) if not p.exists() or p.read_text(encoding="utf-8") != want]
        emit(args, {"up_to_date": not stale, "stale": stale, "results": res},
             "calibration results are up to date" if not stale else
             f"out of date: {', '.join(stale)}. The scoring rules or the golden runs changed: run `gradekit calibration run`")
        return 0 if not stale else 1
    out.write_text(text, encoding="utf-8")
    mdo.write_text(md, encoding="utf-8")
    lines = [f"{g['name']}: {g['status']} ({len(g['runs'])} of {g['runs_needed']} runs)" for g in res["goldens"]]
    emit(args, {"results": res, "written": [str(out), str(mdo)]},
         "\n".join(lines + [f"\ncalibration: {'PASS' if res['pass'] else 'not passed yet'}; wrote {out} and {mdo}"]))
    return 0

# =========================================================================== work orders
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


def cmd_order_new(args) -> int:
    pdir = project_dir_from_args(args)
    if pdir is None or not (pdir / PROJECT_FILE).exists():
        die("give --project NAME (or --project-dir) of a project with a project.toml")
    now = utc_now()
    n = 1 + max([int(m.group(1)) for f in (pdir / ORDERS_DIR).glob(f"{now[:10]}-{args.role}-*.json")
                 if (m := re.search(r"-(\d+)\.json$", f.name))] or [0]) if (pdir / ORDERS_DIR).is_dir() else 1
    oid = f"{now[:10]}-{args.role}-{n}"
    order = {"id": oid, "project": pdir.name, "role": args.role, "status": "open", "created": now, "requested_by": args.by,
             "commit": args.commit, "base_commit": args.base_commit, "change": args.change, "delivery": args.delivery,
             "budget": args.budget, "notes": args.note}
    order = {k: v for k, v in order.items() if v is not None}
    out = pdir / ORDERS_DIR / f"{oid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, order)
    emit(args, {"order": order, "written": str(out)},
         f"wrote {out}\nGive the agent its ID (\"Work order: {oid}\"); its report records it with `--work-order {oid}`, which closes the order.")
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

# =========================================================================== index (grading repos)
# projects/index.json: one file with every project's latest score, maturity, history and the
# decisions waiting, for dashboards and the Review page. Derived from the reports, so it's
# deterministic (no timestamps of its own): `index --check` tells whether it's up to date.

INDEX_FILE = "index.json"
INDEX_ABOUT = ("Generated by `gradekit index` from the reports, project.toml and decisions.json files. Don't edit it: "
               "CI rebuilds it when reports or decisions change.")


def build_index(root: Path) -> dict:
    projects = []
    pdirs = sorted(d for d in (root / "projects").iterdir() if d.is_dir() and (d / PROJECT_FILE).exists()) if (root / "projects").is_dir() else []
    for pdir in pdirs:
        entry: dict = {"name": pdir.name, "problems": []}
        try:
            cfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), quiet=True)
            proj = cfg.get("project") or {}
            entry.update({"description": proj.get("description"), "preset": cfg["preset"], "code_repo": proj.get("code_repo"),
                          "path": proj.get("path"), "config_hash": cfg["hash"]})
        except GradekitError as exc:
            cfg = None
            entry["problems"].append(f"config: {exc}")
        history = []
        for folder in report_folders(pdir):
            try:
                r = load_json(folder / "report.json")
            except GradekitError as exc:
                entry["problems"].append(f"{folder.name}: {exc}")
                continue
            roll = r.get("rollup") or {}
            run = r.get("run") or {}
            history.append({"folder": folder.name, "date": str(run.get("date") or "")[:10], "commit": str(run.get("commit") or "")[:7],
                            "mode": r.get("mode"), "overall": roll.get("overall_score"),
                            "level": (roll.get("maturity") or {}).get("current_level"), "_report": r})
        latest = None
        pending = []
        full = [h for h in history if h["mode"] != "pr"]
        if full and cfg is not None:
            h = full[-1]
            r = h["_report"]
            try:
                roll = compute_rollup(r, cfg)
                zones = roll["finding_zones"]
                counts = {s: 0 for s in SEVERITIES[::-1]}
                for f in r.get("findings", []):
                    if f.get("status") in OPEN_STATUSES:
                        sev = (zones.get(f.get("id")) or {}).get("effective_severity", f.get("severity"))
                        if sev in counts:
                            counts[sev] += 1
                rr = r.get("repo_rollup") or {}
                latest = {"folder": h["folder"], "date": h["date"], "commit": h["commit"],
                          "overall": rr.get("overall_score", h["overall"]), "level": rr.get("maturity", h["level"]),
                          "next_level": roll["maturity"].get("next_level"),
                          "failed_gates": [g["benchmark_id"] for g in roll["gates"] if g["status"] == "failed"],
                          "open_findings": counts}
                if rr:
                    latest["components"] = [{"name": c["component"], "weight": c["weight"], "overall": c["overall"], "level": c["level"]}
                                            for c in rr.get("components", [])]
                pending = [{"action_id": p["action_id"], "question": p.get("decision_question"), "folder": h["folder"]}
                           for p in roll["priorities"]
                           if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
            except GradekitError as exc:
                entry["problems"].append(f"{h['folder']}: {exc}")
        answered = answered_orders(pdir)
        open_orders = [{"id": o.get("id"), "role": o.get("role"), "created": o.get("created"), "requested_by": o.get("requested_by")}
                       for o in load_orders(pdir) if order_status(o, answered) == "open"]
        try:
            disputes_open = [{"finding_id": d.get("finding_id"), "by": d.get("by"), "date": d.get("date")} for d in open_disputes(pdir)]
        except GradekitError as exc:
            disputes_open = []
            entry["problems"].append(f"{DISPUTES_FILE}: {exc}")
        entry.update({"latest": latest, "pending_decisions": pending, "open_orders": open_orders, "open_disputes": disputes_open,
                      "history": [{k: v for k, v in h.items() if k != "_report"} for h in history]})
        projects.append(entry)
    return {"_about": INDEX_ABOUT, "suite_version": load_catalog()["suite_version"], "projects": projects}


def index_text(root: Path) -> str:
    return json.dumps(build_index(root), indent=2, ensure_ascii=False) + "\n"


def cmd_index(args) -> int:
    root = Path(args.grading_repo or ".")
    if not (root / "projects").is_dir():
        die(f"{root} has no projects/ folder (is it a grading repo?)")
    out = Path(args.out) if args.out else root / "projects" / INDEX_FILE
    text = index_text(root)
    data = json.loads(text)
    current = out.read_text(encoding="utf-8") if out.exists() else None
    up_to_date = current == text
    summary = [f"{p['name']}: " + (f"{dash(p['latest']['overall'])} ({p['latest']['level']})" if p["latest"] else "no report yet")
               + (f", {len(p['pending_decisions'])} decision(s) waiting" if p["pending_decisions"] else "")
               + (f"  [problems: {'; '.join(p['problems'])}]" if p["problems"] else "") for p in data["projects"]]
    if args.check:
        emit(args, {"up_to_date": up_to_date, "path": str(out), "index": data},
             "\n".join(summary + ["", f"{out} is up to date" if up_to_date else f"{out} is out of date: run `gradekit index`"]))
        return 0 if up_to_date else 1
    if not up_to_date:
        out.write_text(text, encoding="utf-8")
    emit(args, {"written": str(out), "changed": not up_to_date, "index": data},
         "\n".join(summary + ["", f"{'wrote' if not up_to_date else 'unchanged:'} {out}"]))
    return 0


# =========================================================================== ci (grading repos)
# Checks a pull request to a grading repo. One kind of change per pull request:
#   report    one new report folder (report.json, report.md, runs/*.json), nothing else
#   settings  a project's project.toml, decisions.json, dispositions.json (append-only), org.toml
# Writes a summary comment and labels; the host's CI posts them (see ci/ in the kit).

CI_MARKER = "<!-- gradekit-ci -->"
REPORT_FOLDER_FILES = re.compile(r"(report\.json|report\.md|runs/[^/]+\.json|components/[^/]+\.(?:json|md))")
SETTINGS_FILES = {PROJECT_FILE, DECISIONS_FILE, DISPOSITIONS_FILE, DISPUTES_FILE, "reports/.gitkeep"}
ROOT_SETTINGS = {"org.toml", "README.md", ".gitignore"}
CI_LABELS = {"report": "grading: report", "settings": "grading: settings", "migration": "grading: migration",
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
    kinds = (["report"] if report_folders_ else []) + (["settings"] if settings else [])
    if len(report_folders_) > 1:
        problems.append("a pull request adds one report: " + ", ".join(f"projects/{p}/reports/{f}" for p, f in sorted(report_folders_)))
    if len(kinds) > 1:
        problems.append("a report pull request changes only its report folder; send the settings changes "
                        f"({', '.join(p for p in sorted(settings) if p) or 'root files'}) separately")
    projects_ = sorted({p for p, _ in report_folders_} | {p for p in settings if p})
    if len(projects_) > 1:
        problems.append(f"one project per pull request (this one touches {', '.join(projects_)})")
    if other and kinds:
        problems.append("grading changes come on their own; this also changes " + ", ".join(other[:8]) + ("…" if len(other) > 8 else ""))
    kind = kinds[0] if len(kinds) == 1 else ("mixed" if kinds else "other")
    folder = sorted(report_folders_)[0] if report_folders_ else None
    return {"kind": kind, "project": folder[0] if folder else (projects_[0] if projects_ else None),
            "folder": folder[1] if folder else None, "settings": settings, "other": other, "problems": problems}


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


def ci_check(root: Path, base: str, head: str, changes: list[tuple[str, str]], site: str | None = None,
             repo_url: str | None = None, branch: str | None = None) -> dict:
    mb = git_out(root, "merge-base", base, head, check=False) or base
    mig = check_migration(root, mb, changes)
    if mig is not None:
        labels = [CI_LABELS["migration"]] + ([CI_LABELS["problems"]] if mig["problems"] else [])
        result = {"kind": "migration", "project": mig["project"], "folder": None, "ok": not mig["problems"],
                  "problems": mig["problems"], "warnings": [], "labels": labels,
                  "summary": {"project": mig["project"], "reports": mig["reports"], "suite": major(kit_version())},
                  "changed": [p for _, p in changes]}
        result["comment"] = ci_comment(result, site, repo_url, branch)
        return result
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
                report = load_json(rpath)
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
                warnings += [f"report: {w}" for w in cfg.get("warnings", []) + warns if "run `gradekit redact" not in w]
                if (cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"):
                    problems += [f"publish: {e}" for e in publish_problems(report)]
                run = report.get("run") or {}
                commit = str(run.get("commit") or "")
                if commit and not folder.endswith("-" + commit[:7]):
                    problems.append(f"the folder is {folder}, but the report grades commit {commit[:7]} (expected <date>-{commit[:7]})")
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
                for cp in comps:
                    try:
                        cr = load_json(cp)
                        ccfg = load_config(argparse.Namespace(project_dir=str(pdir), config=None, component=None), cr, quiet=True)
                        cerr, _ = validate_report(cr, ccfg, load_catalog())
                        problems += [f"components/{cp.name}: {e}" for e in cerr]
                        if (ccfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"):
                            problems += [f"components/{cp.name}: publish: {e}" for e in publish_problems(cr)]
                        croll, cst = compute_rollup(cr, ccfg), cr.get("rollup") or {}
                        if (cst.get("overall_score"), (cst.get("maturity") or {}).get("current_level")) != (
                                croll["overall_score"], croll["maturity"]["current_level"]):
                            problems.append(f"components/{cp.name}: the stored rollup doesn't match its scores; run `gradekit rollup --write`")
                    except GradekitError as exc:
                        problems.append(f"components/{cp.name}: {exc}")
                if comps:
                    try:
                        want = repo_rollup(comps)
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

    if shape["kind"] == "settings":
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
    elif res["kind"] == "migration":
        lines.append(f"**Migration** of `{s['project']}` to suite {s['suite']}: the pin, and {s['reports']} report(s) in format 5. "
                     "Each file was checked by redoing the migration from the base branch; scores and rollups are unchanged.")
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


# =========================================================================== glossary
# One vocabulary for prompts, the website and the docs (rubric/glossary.json).

def load_glossary() -> dict:
    return load_json(GLOSSARY_PATH)


def glossary_terms() -> list[dict]:
    return [dict(t, group=g["name"]) for g in load_glossary()["groups"] for t in g["terms"]]


def glossary_markdown() -> str:
    data = load_glossary()
    out = ["# Glossary", "",
           "The words the suite uses, and what they mean. Prompts, the website and these docs use them exactly as defined "
           "here. When a term has alternatives to avoid, they're listed: please don't use them either.", "",
           "Generated from `rubric/glossary.json` by `gradekit glossary --markdown`. Edit that file, not this one.", ""]
    for g in data["groups"]:
        out += [f"## {g['name']}", ""]
        for t in g["terms"]:
            out.append(f"**{t['term']}**: {t['definition']}" + (f" *Not:* {', '.join(t['avoid'])}." if t.get("avoid") else ""))
            out.append("")
    return "\n".join(out)


def cmd_glossary(args) -> int:
    terms = glossary_terms()
    if args.markdown:
        text = glossary_markdown()
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            emit(args, {"written": args.out}, f"wrote {args.out}")
        else:
            emit(args, {"markdown": text}, text.rstrip("\n"))
        return 0
    if args.term:
        want = " ".join(args.term).lower()
        found = [t for t in terms if t["term"].lower() == want] or \
                [t for t in terms if want in t["term"].lower() or want in [a.lower() for a in t.get("avoid", [])]]
        if not found:
            die(f"'{want}' isn't in the glossary (`gradekit glossary` lists every term)")
        lines = []
        for t in found:
            lines.append(f"{t['term']}: {t['definition']}")
            if want in [a.lower() for a in t.get("avoid", [])]:
                lines.append(f"  (say '{t['term']}', not '{want}')")
        emit(args, {"terms": found}, "\n".join(lines))
        return 0
    lines = []
    group = None
    for t in terms:
        if t["group"] != group:
            group = t["group"]
            lines.append(("\n" if lines else "") + group)
        lines.append(f"  {t['term']:<20} {t['definition']}")
    emit(args, {"terms": terms}, "\n".join(lines))
    return 0


# =========================================================================== render
# Markdown made from report data, so every report, pull request, PR check and improvement log
# has the same layout and no hand-copied numbers. Public text never carries withheld details.

def md_cell(text) -> str:
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ").strip()


def dash(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer() and abs(v) >= 10:
        return str(int(v))
    return str(v)


def report_label(report: dict) -> tuple[str, str, str]:
    run = report.get("run") or {}
    project = run.get("project") or (report.get("component") or {}).get("name") or "project"
    commit = str(run.get("commit") or "?")[:7]
    return project, commit, str(run.get("date") or "")[:10]


def public_view(report: dict, cfg: dict) -> dict:
    """The report as it may be shown publicly: sensitive findings withheld unless the repo is private."""
    if not (cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public") or (report.get("publishing") or {}).get("redacted"):
        return report
    public, leaks = redact_report(report)
    if leaks:
        die("withheld text still appears elsewhere in the report; fix these first (or run `gradekit redact`):\n  "
            + "\n  ".join(leaks))
    return public


def rendering_rollup(report: dict, cfg: dict) -> dict:
    roll = compute_rollup(report, cfg)
    if roll["weight_issues"]:
        die("weights don't match the config; run `gradekit report check` first:\n  " + "\n  ".join(roll["weight_issues"]))
    return roll


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


def decisions_block(roll: dict) -> list[str]:
    pending = [p for p in roll["priorities"] if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
    if not pending:
        return ["None."]
    return [f"- [ ] **{p['action_id']}:** {p.get('decision_question')}" for p in pending]


def provenance_line(run: dict) -> str:
    """Who graded, with what, and how long it took (format 5)."""
    who = " ".join(x for x in (str(run.get("grader") or "").strip(), f"({run['model']})" if run.get("model") else "") if x)
    parts = [f"Graded by {md_cell(who or 'unknown')}"]
    if isinstance(run.get("_migrated_from"), str):
        parts.append(f"with suite {run['_migrated_from']} (migrated)")
    mins = (run.get("usage") or {}).get("minutes")
    if mins is not None:
        parts.append(f"{mins:g} min")
    for key, label in (("work_order", "work order"), ("session", "session")):
        if run.get(key):
            parts.append(f"{label} `{md_cell(run[key])}`")
    return "*" + " · ".join(parts) + "*"


def render_report_md(report: dict, cfg: dict, catalog: dict | None = None) -> str:
    catalog = catalog or load_catalog()
    report = public_view(report, cfg)
    roll = rendering_rollup(report, cfg)
    project, commit, date = report_label(report)
    by_id = benchmarks_by_id(report)
    fz = roll["finding_zones"]
    gates = {g["benchmark_id"]: g for g in roll["gates"]}
    mat = roll["maturity"]
    findings = report.get("findings", [])
    out = [f"# Grading report: {project} @ {commit} ({date})", ""]
    if report.get("mode") == "pr":
        out += [f"*PR check against base `{str((report.get('run') or {}).get('base_commit') or '?')[:7]}`. "
                f"Untouched benchmarks are carried forward from the last full report.*", ""]
    if report_format(report) >= 5:
        out += [provenance_line({**(report.get("run") or {}), "_migrated_from": (report.get("migrated") or {}).get("from")}), ""]

    out += ["## Summary", "", f"Overall **{dash(roll['overall_score'])}**"
            + (" (capped by a failed gate)" if roll["overall_cap_applied"] else "")
            + f", maturity **{mat['current_level']}**" + (f" (next: {mat['next_level']})" if mat.get("next_level") else "") + "."]
    if str(report.get("summary") or "").strip():
        out += ["", report["summary"].strip()]
    out.append("")

    out += ["## Gates and maturity", "", "| Gate | Score | Status |", "|---|:-:|---|"]
    for g in roll["gates"]:
        b = by_id.get(g["benchmark_id"], {})
        out.append(f"| {g['benchmark_id']} {md_cell(b.get('name'))} | {dash(g['score'])} | {g['status']} ({', '.join(g['why'])}) |")
    out.append("")
    if mat.get("level_before_integrity_cap"):
        out += [f"Maturity is capped at {mat['current_level']} by an integrity flag (it would be {mat['level_before_integrity_cap']}).", ""]
    if mat.get("next_level"):
        blockers = "; ".join(f"{x['requirement']} (now {dash(x.get('current'))})" for x in mat.get("blockers", []))
        out += [f"Blocking {mat['next_level']}: {blockers or 'nothing'}", ""]

    out += ["## Scorecard", "", "Gates are marked ★. Weight is the weight used, after applicability.", "",
            "| ID | Benchmark | Score | Target | Weight | Confidence | Applicability | Notes |", "|---|---|:-:|:-:|:-:|---|---|---|"]
    for pillar in PILLARS:
        rows = [b for b in report["benchmarks"] if b.get("pillar") == pillar]
        if not rows:
            continue
        for b in rows:
            why = b.get("rationale") or b.get("change_explanation") or b.get("applicability_reason") or ""
            out.append(f"| {b['id']}{' ★' if b['id'] in gates else ''} | {md_cell(b.get('name'))} | {dash(b.get('score'))} | "
                       f"{dash(roll['targets'].get(b['id']))} | {b.get('weight')} | {dash(b.get('confidence'))} | "
                       f"{b.get('applicability')} | {md_cell(why)} |")
        pname = catalog.get("pillars", {}).get(pillar, {})
        pname = pname.get("name") if isinstance(pname, dict) else pname
        out.append(f"| | **{pillar}{(' ' + md_cell(pname)) if pname else ''}** | **{dash(roll['pillar_scores'].get(pillar))}** | | | | | |")
    out += [f"| | **Overall** | **{dash(roll['overall_score'])}** | | | | | |", ""]

    app = roll.get("applicability", {})
    notes = [f"- **{bid}** limited: {by_id[bid].get('applicability_reason')}" for bid in app.get("limited", [])]
    notes += [f"- **{bid}** not applicable: {by_id[bid].get('applicability_reason')}" for bid in app.get("not_applicable", [])]
    notes += [f"- **{bid}** weight note: {n}" for bid, n in (app.get("weight_notes") or {}).items()]
    out += ["## Applicability and weight notes", ""] + (notes or ["Every benchmark fully applies, and no weight looked wrong."]) + [""]

    top = roll["priorities"][:10]
    out += ["## Top priorities", ""]
    for i, p in enumerate(top, 1):
        dec = p.get("decision") or {}
        tag = ""
        if p.get("requires_human_decision"):
            tag = f" — **decision {dec.get('status', 'pending')}:** {p.get('decision_question')}"
        out.append(f"{i}. **{p['action_id']}** (tier {p['tier']}, {p['zone']} zone, +{p['gain']}, effort {p['effort']}): {p.get('action')}{tag}")
    out += (["No actions."] if not top else []) + [""]

    out += ["## Decisions needed", ""] + decisions_block(roll)
    out += ["", "Answer in `decisions.json` (the suite website's *Review a report* page writes it for you).", ""]

    metrics = report.get("metrics") or {}
    if metrics:
        mn = report.get("metrics_notes") or {}
        out += ["## Metrics", "", "| Metric | Value | Note |", "|---|---|---|"]
        out += [f"| {k} | {dash(v)} | {md_cell(mn.get(k))} |" for k, v in metrics.items()] + [""]

    out += ["## Findings", ""]
    if findings:
        out += ["| ID | Severity → effective | Zone | Status | Title |", "|---|---|---|---|---|"]
        for f in findings:
            z = fz.get(f.get("id"), {})
            out.append(f"| {f.get('id')} | {f.get('severity')} → {z.get('effective_severity', f.get('severity'))} | "
                       f"{z.get('criticality', '')} | {f.get('status')} | {md_cell(f.get('title'))} |")
        for status, label in (("fixed", "Fixed since the last report"), ("regressed", "Regressed (fixed before, back again)")):
            ids = [f["id"] for f in findings if f.get("status") == status]
            if ids:
                out += ["", f"{label}: {', '.join(ids)}."]
    else:
        out.append("None.")
    out.append("")

    feats = report.get("feature_inventory") or []
    gaps = report.get("gap_register") or []
    if feats:
        out += ["## Feature inventory", "", "| Feature | Claimed in | Status |", "|---|---|---|"]
        out += [f"| {md_cell(x.get('feature'))} | {md_cell(x.get('source'))} | {x.get('status')} |" for x in feats] + [""]
    if gaps:
        out += ["## Gap register", "", "| ID | Gap | Severity | Necessity | Status | Benchmarks |", "|---|---|---|---|---|---|"]
        out += [f"| {g.get('id')} | {md_cell(g.get('gap'))} | {g.get('severity')} | {g.get('necessity')} | {g.get('status')} | "
                f"{', '.join(g.get('benchmark_ids', []))} |" for g in gaps] + [""]

    out += ["## Benchmark detail", ""]
    fmap = {f.get("id"): f for f in findings}
    for b in report["benchmarks"]:
        if b.get("applicability") == "not_applicable":
            continue
        out.append(f"### {b['id']} {b.get('name')}: {dash(b.get('score'))} (target {dash(roll['targets'].get(b['id']))})")
        out.append("")
        if b.get("carried_forward"):
            out += ["Carried forward from the last full report.", ""]
        for label, text in (("Why", b.get("rationale")), ("Change", b.get("change_explanation"))):
            if text:
                out += [f"{label}: {text}", ""]
        for s in b.get("strengths", []):
            out.append(f"- Strength: {s.get('note')} ({'; '.join(evidence_line(e) for e in s.get('evidence', []))})")
        for fid in b.get("finding_ids", []):
            f = fmap.get(fid, {})
            evs = [evidence_line(e) for e in f.get("evidence", []) if e.get("type") != "withheld"]
            out.append(f"- Finding {fid} ({f.get('severity')}, {f.get('status')}): {f.get('title')}" + (f" ({'; '.join(evs)})" if evs else ""))
        for e in b.get("enforcement", []):
            out.append(f"- Enforced by: {evidence_line(e)}")
        if report_format(report) >= 5:
            lim = (roll.get("limits") or {}).get(b.get("id"))
            held = [w for w in (lim or {}).get("why", []) if w["kind"] in ("cap", "critical")]
            if held:
                out.append(f"- Limit: at most {min(w['max'] for w in held)} while {'; '.join(w['why'] for w in held)}")
        else:
            for c in b.get("caps_applied", []):
                out.append(f"- Cap applied: {c}")
        for a in b.get("path_to_target", []):
            out.append(f"- Next: **{a['id']}** → {a.get('expected_new_score')} (effort {a.get('effort')}): {a.get('action')}"
                       + (" *(needs a decision)*" if a.get("requires_human_decision") else ""))
        out.append("")

    flags = report.get("integrity_flags") or []
    gaming = [(b["id"], g) for b in report["benchmarks"] for g in b.get("gaming_flags", [])]
    if flags or gaming:
        out += ["## Integrity and gaming flags", ""]
        out += [f"- Integrity: {f.get('description')} ({'; '.join(evidence_line(e) for e in f.get('evidence', []))})" for f in flags]
        out += [f"- Gaming ({bid}): {g}" for bid, g in gaming] + [""]

    out += ["## Limitations", ""]
    out += [f"- {x}" for x in report.get("limitations") or []] or ["- None recorded."]
    h = report.get("holdout") or {}
    if h.get("run"):
        out.append(f"- Hidden checks: {h.get('checks_run')} run, {h.get('pass_rate', 0):.0%} passed.")
    out += ["", f"<sub>Rendered by gradekit from report.json (suite {report.get('suite_version')}, config {roll['config_hash']}).</sub>", ""]
    return "\n".join(out)


def review_link(site: str | None, grading_repo: str | None, project: str, ref: str) -> str | None:
    if not (site and grading_repo):
        return None
    from urllib.parse import quote
    return f"{site.rstrip('/')}/app/review.html?repo={quote(grading_repo, safe='/:')}&project={quote(project)}&ref={quote(ref, safe='/')}"


def render_report_pr(report: dict, cfg: dict, site: str | None = None, grading_repo: str | None = None,
                     branch: str | None = None, folder: str | None = None) -> dict:
    report = public_view(report, cfg)
    roll = rendering_rollup(report, cfg)
    project, commit, date = report_label(report)
    folder = folder or f"{date}-{commit}"
    branch = branch or f"report/{project}/{folder}"
    mat = roll["maturity"]
    title = f"Report: {project} {date} — {dash(roll['overall_score'])} ({mat['current_level']})"
    body = [f"Grading report for **{project}** at `{commit}`: overall **{dash(roll['overall_score'])}**"
            + (" (capped by a failed gate)" if roll["overall_cap_applied"] else "")
            + f", maturity **{mat['current_level']}**" + (f" (next: {mat['next_level']})." if mat.get("next_level") else ".")]
    if str(report.get("summary") or "").strip():
        body += ["", report["summary"].strip()]
    body += ["", "**Gates**", ""]
    body += [f"- {g['benchmark_id']}: {dash(g['score'])} — {g['status']}" for g in roll["gates"]]
    blockers = "; ".join(f"{x['requirement']} (now {dash(x.get('current'))})" for x in mat.get("blockers", []))
    if mat.get("next_level"):
        body += ["", f"Blocking {mat['next_level']}: {blockers or 'nothing'}"]
    body += ["", "**Decisions needed**", ""] + decisions_block(roll)
    link = review_link(site, grading_repo, project, branch)
    if link:
        body += ["", f"[Review this report and answer the decisions]({link})"]
    body += ["", f"Files: `projects/{project}/reports/{folder}/` (report.json, report.md)."]
    return {"title": title, "body": "\n".join(body) + "\n", "branch": branch}


def render_check_comment(diff: dict, new: dict, cfg: dict) -> str:
    """The PR-check comment (pr-review.md step 4). Sensitive findings are always withheld: PR comments are often public."""
    sens = sensitive_ids(new)
    names = {b["id"]: b["name"] for b in load_catalog()["benchmarks"]}

    def title(f):
        return f"{names.get(f['id'].split('-')[0], '')} issue (details withheld)" if f["id"] in sens else f["title"]

    applicable = [b for b in new.get("benchmarks", []) if b.get("applicability") != "not_applicable"]
    regraded = [b["id"] for b in applicable if not b.get("carried_forward")]
    fixed_by = {}
    for f in diff["findings"]["fixed"]:
        fixed_by.setdefault(f["id"].split("-")[0], []).append(f["id"])
    changes = [f"{c['id']} {dash(c['old'])} → {dash(c['new'])}" + (f" ({', '.join(fixed_by[c['id']])} fixed)" if c["id"] in fixed_by else "")
               for c in diff["score_changes"]]
    fresh = [f for f in diff["findings"]["new"] if not f.get("pre_existing")]
    pre = [f for f in diff["findings"]["new"] if f.get("pre_existing")]
    roll = compute_rollup(new, cfg)
    pending = [p for p in roll["priorities"] if p.get("requires_human_decision") and (p.get("decision") or {}).get("status") == "pending"]
    lines = [f"**PR check: {diff['verdict']}**",
             ("Re-graded: every applicable benchmark (full report)" if len(regraded) == len(applicable) else
              f"Re-graded: {', '.join(regraded) or 'none'} (others carried forward)"),
             f"Changes: {' · '.join(changes) or 'none'}",
             f"Overall: {dash(diff['overall']['old'])} → {dash(diff['overall']['new'])} · Maturity: {diff['maturity']['old']} → {diff['maturity']['new']}",
             "New findings: " + ("; ".join(f"{f['id']}: {title(f)}, {f['effective_severity']}, {f['zone']} zone" for f in fresh) or "none"),
             "Regressions: " + ("; ".join(r if not any(i in r for i in sens) else r.split(":")[0] + ": details withheld" for r in diff["regressions"]) or "none")]
    if pre:
        lines.append("Already there before this change: " + "; ".join(f"{f['id']}: {title(f)}" for f in pre))
    if diff.get("holdout"):
        lines.append(f"Hidden checks: {diff['holdout']['old']:.0%} → {diff['holdout']['new']:.0%}")
    lines.append("Decisions needed: " + ("; ".join(f"{p['action_id']}: {p.get('decision_question')}" for p in pending) or "none"))
    lines += [f"Note: {n}" for n in diff["notes"] if not any(i in n for i in sens)]
    return "\n".join(lines) + "\n"


LOG_KEYS = {"done": ("action_id", "commit", "resolves", "check"), "blocked": ("action_id", "question"),
            "skipped": ("action_id", "reason"), "behavior_changes": None, "new_issues": None}


def log_commits(commit) -> str:
    """An action's commit(s) in the improvement log: one SHA, several (a list, or separated by spaces or commas), or none."""
    shas = commit if isinstance(commit, list) else re.split(r"[\s,]+", str(commit or "").strip())
    shas = [str(s).strip()[:10] for s in shas if str(s).strip()]
    return ", ".join(f"`{s}`" for s in shas) if shas else "`?`"


def render_improve_log(log: dict, report: dict | None = None, cfg: dict | None = None, guard: dict | None = None) -> str:
    for key in log:
        if key not in LOG_KEYS and key != "notes":
            die(f"improvement log: unknown section '{key}' (known: {', '.join(LOG_KEYS)}, notes)")
    blocked = list(log.get("blocked") or [])
    skipped = list(log.get("skipped") or [])
    if report is not None and cfg is not None:
        listed = {x.get("action_id") for x in (log.get("done") or []) + blocked + skipped}
        for p in compute_rollup(report, cfg)["priorities"]:
            st = (p.get("decision") or {}).get("status")
            if p.get("requires_human_decision") and p["action_id"] not in listed:
                if st == "pending":
                    blocked.append({"action_id": p["action_id"], "question": p.get("decision_question")})
                elif st == "declined":
                    skipped.append({"action_id": p["action_id"], "reason": "decision declined"})
    out = ["## Improvement log", ""]
    if log.get("notes"):
        out += [str(log["notes"]).strip(), ""]
    if guard is not None:
        out += render_guard(guard) + [""]
    out += ["**Done** (claims; the next independent grading verifies them)", ""]
    out += [f"- **{d.get('action_id')}** in {log_commits(d.get('commit'))}" + (f", resolves {', '.join(d.get('resolves') or [])}" if d.get("resolves") else "")
            + (f". Checked with: {d['check']}" if d.get("check") else "") for d in log.get("done") or []] or ["- Nothing yet."]
    out += ["", "**Blocked** (waiting on a decision)", ""]
    out += [f"- **{b.get('action_id')}:** {b.get('question')}" for b in blocked] or ["- None."]
    out += ["", "**Skipped**", ""]
    out += [f"- **{s.get('action_id')}:** {s.get('reason')}" for s in skipped] or ["- None."]
    for key, label in (("behavior_changes", "Behavior changes"), ("new_issues", "New issues noticed")):
        out += ["", f"**{label}**", ""] + ([f"- {x}" for x in log.get(key) or []] or ["- None."])
    return "\n".join(out) + "\n"


def render_out(args, text: str, default_path: Path | None) -> None:
    dest = args.out or (str(default_path) if default_path and not args.stdout else None)
    if dest and dest != "-":
        Path(dest).write_text(text, encoding="utf-8")
        args._result = {"written": dest, "markdown": text}
        print(f"wrote {dest}")
    else:
        args._result = {"written": None, "markdown": text}
        print(text, end="")


def cmd_render_report(args) -> int:
    report = load_json(args.report)
    cfg = authoring_config(args, report)
    text = render_report_md(report, cfg)
    render_out(args, text, Path(re.sub(r"\.json$", "", args.report) + ".md"))
    return 0


def cmd_render_pr(args) -> int:
    report = load_json(args.report)
    cfg = authoring_config(args, report)
    folder = Path(args.report).resolve().parent.name if Path(args.report).name == "report.json" else None
    pr = render_report_pr(report, cfg, args.site, args.grading_repo_url, args.branch, folder)
    args._result = pr
    print(f"{pr['title']}\n\n{pr['body']}", end="")
    return 0


def cmd_render_check(args) -> int:
    old, new = load_json(args.old), load_json(args.new)
    args.report = args.new
    cfg = authoring_config(args, new)
    text = render_check_comment(compute_diff(old, new, cfg, cfg), new, cfg)
    render_out(args, text, None)
    return 0


def cmd_render_log(args) -> int:
    log = load_json(args.log)
    report, cfg = None, None
    if args.report:
        report = load_json(args.report)
        cfg = authoring_config(args, report)
    guard = None
    if args.guard:
        guard = load_json(args.guard)
        if "verdict" not in guard or "items" not in guard:
            die(f"{args.guard} isn't a `guard compare` result (it writes .git/gradekit/guard-compare.json, or --out)")
    render_out(args, render_improve_log(log, report, cfg, guard), None)
    return 0



# =========================================================================== guard
# The improver's proof that nothing got worse. `guard snapshot` runs the code's own checks (tests,
# linters, type checker, build) and counts suppressions and skipped tests; `guard compare` runs the
# very same commands again and lists what got worse. It never judges quality: the next grade does.

GUARD_VERSION = 1
GUARD_TIMEOUT = 1800
GUARD_TAIL_LINES = 40

# How a command from a report's commands_run is recognised. First match wins; anything else
# (git log, cloc, ls…) isn't a check and is left out.
GUARD_KIND_PATTERNS = [
    ("types", r"\b(mypy|pyright|pytype|tsc|flow check|(npm|yarn|pnpm)( run)? (typecheck|type-check|types))\b"),
    ("lint", r"\b(ruff|flake8|pylint|eslint|biome|golangci-lint|go vet|clippy|rubocop|shellcheck|stylelint|standardrb"
             r"|prettier (--check|-c)|black --check|isort (--check|-c)|gofmt|cargo fmt|(npm|yarn|pnpm)( run)? lint)\b"),
    ("audit", r"\b(pip-audit|(npm|yarn|pnpm) audit|cargo audit|govulncheck|safety check|bundle audit|osv-scanner)\b"),
    ("coverage", r"\b(coverage (report|xml|json)|go tool cover)\b"),
    ("tests", r"\b(pytest|unittest|nose2?|tox|nox|jest|vitest|mocha|ava|go test|cargo test|rspec|phpunit|dotnet test|ctest"
              r"|bun test|deno test|coverage run|(npm|yarn|pnpm)( run)? test|make (test|check)"
              r"|mvn\b.*\b(test|verify)|gradlew?\b.*\b(test|check))\b"),
    ("build", r"\b((npm|yarn|pnpm) run build|cargo build|go build|mvn\b.*\b(package|compile|install)|gradlew?\b.*\bbuild"
              r"|python3? -m build|dotnet build|cmake --build)\b"),
]

# Markers a change can add to make a check quieter without making the code better. Counted per line.
GUARD_MARKERS = {
    "suppressions": [
        r"#\s*noqa\b", r"#\s*type:\s*ignore", r"#\s*pragma:\s*no\s*cover", r"#\s*pylint:\s*disable", r"#\s*pyright:\s*ignore",
        r"#\s*nosec\b", r"eslint-disable", r"@ts-ignore", r"@ts-expect-error", r"@ts-nocheck", r"\bnolint\b", r"\bNOLINT",
        r"#!?\[allow\(", r"@SuppressWarnings", r"NOSONAR", r"rubocop:disable", r"istanbul ignore", r"c8 ignore",
        r"@phpstan-ignore", r"@psalm-suppress", r"swiftlint:disable", r"biome-ignore", r"prettier-ignore",
    ],
    "skipped_tests": [
        r"@pytest\.mark\.(skip|skipif|xfail)\b", r"\bpytest\.(skip|xfail)\(", r"@unittest\.(skip|skipIf|skipUnless|expectedFailure)\b",
        r"\b(it|test|describe|context)\.(skip|todo)\(", r"\bx(it|describe|test|context)\(", r"\bt\.Skip(f|Now)?\(",
        r"#\[ignore\]", r"@Disabled\b", r"@Ignore\b", r"\bskip\s*:\s*true\b",
    ],
}
GUARD_MARKER_RE = {k: re.compile("|".join(v)) for k, v in GUARD_MARKERS.items()}

# Files that configure a gate: CI, lint, type-check, coverage and test settings. A change to one is listed
# for review (adding a check is fine; weakening one never is). Matched on the file name, at any depth.
GUARD_GATE_FILES = (
    "*.gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "bitbucket-pipelines.yml", ".pre-commit-config.yaml",
    "pyproject.toml", "setup.cfg", "tox.ini", "noxfile.py", ".coveragerc", "pytest.ini", "mypy.ini", ".mypy.ini",
    "pyrightconfig.json", "ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", "pylintrc", "package.json", ".eslintrc*",
    "eslint.config.*", "tsconfig*.json", "jest.config.*", "vitest.config.*", "biome.json", "biome.jsonc", ".golangci.y*ml",
    "clippy.toml", ".clippy.toml", "Cargo.toml", "codecov.yml", ".codecov.yml", "sonar-project.properties", "CODEOWNERS",
    "Makefile", ".rubocop.yml", "phpunit.xml*", "phpstan.neon*",
)
GUARD_GATE_DIRS = (".github/workflows", ".gitlab/ci", ".circleci", ".buildkite")
GUARD_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".nox", "dist", "build", "target",
                   ".mypy_cache", ".pytest_cache", ".ruff_cache", "vendor", ".next", "coverage", "htmlcov"}

# Direction of each count: which way is better.
GUARD_HIGHER = ("passed", "packages_ok", "coverage_pct", "pylint_score")
GUARD_LOWER = ("failed", "errors", "skipped", "xfailed", "pending", "problems", "warnings", "diagnostics", "packages_failed",
               "vulnerabilities")
GUARD_COUNT_ORDER = ("passed", "failed", "errors", "skipped", "xfailed", "pending", "packages_ok", "packages_failed",
                     "problems", "warnings", "vulnerabilities", "diagnostics", "coverage_pct", "pylint_score")
GUARD_LABEL = {"passed": "passed", "failed": "failed", "errors": "errors", "skipped": "skipped", "xfailed": "xfailed",
               "pending": "pending", "packages_ok": "packages ok", "packages_failed": "packages failed",
               "problems": "problems", "warnings": "warnings", "vulnerabilities": "vulnerabilities", "diagnostics": "diagnostic lines",
               "coverage_pct": "coverage %", "pylint_score": "pylint score"}

GUARD_SCORES = ("coverage_pct", "pylint_score")
_TESTS = {"passed", "failed", "errors", "skipped", "xfailed", "pending", "packages_ok", "packages_failed"}
_LINT = {"problems", "warnings"}
GUARD_FAMILY = {**{k: _TESTS for k in _TESTS}, **{k: _LINT for k in _LINT}, "diagnostics": {"diagnostics"},
                "vulnerabilities": {"vulnerabilities"}}


def guard_count_text(k: str, v) -> str:
    if k == "coverage_pct":
        return f"coverage {v:g}%"
    if k == "pylint_score":
        return f"pylint {v:g}/10"
    label = GUARD_LABEL[k]
    if v == 1:
        label = {"errors": "error", "problems": "problem", "warnings": "warning", "vulnerabilities": "vulnerability",
                 "diagnostic lines": "diagnostic line",
                 "packages ok": "package ok", "packages failed": "package failed"}.get(label, label)
    return f"{v:g} {label}" if isinstance(v, float) else f"{v} {label}"


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


GUARD_INSTALL_RE = re.compile(r"\b(pip3?|python3? -m pip|uv pip|npm|yarn|pnpm|bun|gem|bundle|cargo|go|apt(-get)?|brew|conda|poetry)"
                              r"\s+(install|add|ci|get|sync)\b")


def guard_trim_note(command: str) -> str:
    """Graders often note something after a command: `pytest -q  (venv without pytz)`. A `(…)` straight after a word
    isn't valid shell, so it's a note, not part of the command. After `&&`, `|` or `;` it's a subshell, and stays."""
    m = re.search(r"\s+\([^()]*\)\s*$", command)
    if m and not re.search(r"(&&|\|\||[|;&])\s*$", command[:m.start()]):
        return command[:m.start()].rstrip()
    return command


def guard_kind(command: str) -> str | None:
    for kind, pat in GUARD_KIND_PATTERNS:
        if re.search(pat, command):
            return kind
    return None


def guard_counts(output: str) -> dict:
    """Numbers a check's output reports, read from the summary lines of common tools. Unknown tools give {}
    (only the exit code is compared), except that file:line diagnostics are counted."""
    text = ANSI_RE.sub("", output).replace("\r", "")
    c: dict = {}

    def add(key, n):
        c[key] = c.get(key, 0) + int(n)

    def pairs(s, mapping):
        for n, w in re.findall(r"(\d+) (\w+)", s):
            key = mapping.get(w.lower())
            if key:
                add(key, n)

    # pytest: "3 failed, 41 passed, 2 skipped in 1.20s" (with or without ===)
    py = re.findall(r"^=*\s*((?:\d+ [a-z]+,? ?)+) in [\d.]+s\b.*$", text, re.M)
    if py and re.search(r"\d+ (passed|failed|error|errors|skipped|deselected|xfailed|xpassed|warnings?)\b", py[-1]):
        pairs(py[-1], {"passed": "passed", "failed": "failed", "error": "errors", "errors": "errors", "skipped": "skipped",
                       "xfailed": "xfailed", "warning": "warnings", "warnings": "warnings"})
    # unittest: "Ran 12 tests in 0.1s" … "FAILED (failures=1, errors=2, skipped=3)" / "OK (skipped=1)"
    ran = re.findall(r"^Ran (\d+) tests? in ", text, re.M)
    if ran and not py:
        total = int(ran[-1])
        st = re.findall(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", text, re.M)
        detail = dict((k.strip(), int(v)) for k, v in re.findall(r"([\w ]+)=(\d+)", st[-1][1] if st else ""))
        failed, errors, skipped = detail.get("failures", 0), detail.get("errors", 0), detail.get("skipped", 0)
        xf = detail.get("expected failures", 0)
        add("passed", max(0, total - failed - errors - skipped - xf))
        add("failed", failed), add("errors", errors), add("skipped", skipped)
        if xf:
            add("xfailed", xf)
    # jest: "Tests:       1 failed, 2 skipped, 40 passed, 43 total"
    for line in re.findall(r"^Tests:\s+(.*\d+ total)\s*$", text, re.M)[-1:]:
        pairs(line, {"passed": "passed", "failed": "failed", "skipped": "skipped", "todo": "skipped"})
    # vitest: " Tests  1 failed | 40 passed | 2 skipped (43)"
    for line in re.findall(r"^\s*Tests\s+(\d+ \w+(?: \| \d+ \w+)*) \(\d+\)\s*$", text, re.M)[-1:]:
        pairs(line, {"passed": "passed", "failed": "failed", "skipped": "skipped", "todo": "skipped"})
    # mocha: "  40 passing (12ms)", "  1 failing", "  2 pending"
    for word, key in (("passing", "passed"), ("failing", "failed"), ("pending", "pending")):
        m = re.findall(rf"^\s*(\d+) {word}\b", text, re.M)
        if m:
            add(key, m[-1])
    # go test: "--- FAIL: TestX", "ok  	pkg	0.1s", "FAIL	pkg	0.2s"
    if re.search(r"^(ok|FAIL|---) ", text, re.M) and re.search(r"^(ok|FAIL)\s+\S+\s+(\d|\[)", text, re.M):
        add("packages_ok", len(re.findall(r"^ok\s+\S+\s", text, re.M)))
        add("packages_failed", len(re.findall(r"^FAIL\s+\S+\s+(\d|\[)", text, re.M)))
        add("failed", len(re.findall(r"^\s*--- FAIL: ", text, re.M)))
        if re.search(r"^\s*--- PASS: ", text, re.M):
            add("passed", len(re.findall(r"^\s*--- PASS: ", text, re.M)))
        if re.search(r"^\s*--- SKIP: ", text, re.M):
            add("skipped", len(re.findall(r"^\s*--- SKIP: ", text, re.M)))
    # cargo test: "test result: ok. 12 passed; 0 failed; 1 ignored; …" (one per test binary)
    for p_, f_, i_ in re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text):
        add("passed", p_), add("failed", f_), add("skipped", i_)
    # rspec: "43 examples, 1 failure, 2 pending"
    for line in re.findall(r"^(\d+ examples?, \d+ failures?(?:, \d+ pending)?)", text, re.M)[-1:]:
        n = [int(x) for x in re.findall(r"\d+", line)]
        add("passed", n[0] - n[1] - (n[2] if len(n) > 2 else 0)), add("failed", n[1])
        if len(n) > 2:
            add("pending", n[2])
    # ruff / mypy / tsc: "Found 3 errors." ; clean runs say so
    found = re.findall(r"^Found (\d+) errors?\b", text, re.M)
    if found:
        add("problems", found[-1])
    elif re.search(r"^(All checks passed!|Success: no issues found)", text, re.M):
        add("problems", 0)
    # eslint: "✖ 5 problems (3 errors, 2 warnings)"
    es = re.findall(r"✖ (\d+) problems? \((\d+) errors?, (\d+) warnings?\)", text)
    if es:
        add("problems", es[-1][0]), add("warnings", es[-1][2])
    # black --check: "3 files would be reformatted, 1 file would be left unchanged."
    bl = re.findall(r"^(?:Oh no!.*\n)?(\d+) files? would be reformatted", text, re.M)
    if bl:
        add("problems", bl[-1])
    elif re.search(r"^\d+ files? would be left unchanged\.$", text, re.M):
        add("problems", 0)
    # pip-audit: "Found 5 known vulnerabilities in 1 package" / "No known vulnerabilities found";
    # npm audit: "found 3 vulnerabilities" / "3 vulnerabilities (1 low, 2 high)"
    va = re.findall(r"Found (\d+) known vulnerabilit(?:y|ies)", text) or re.findall(r"^(?:found )?(\d+) vulnerabilit(?:y|ies)\b", text, re.M | re.I)
    if va:
        add("vulnerabilities", va[-1])
    elif re.search(r"No known vulnerabilities found|found 0 vulnerabilities", text):
        add("vulnerabilities", 0)
    # pylint: "Your code has been rated at 9.12/10"
    pl = re.findall(r"rated at (-?[\d.]+)/10", text)
    if pl:
        c["pylint_score"] = float(pl[-1])
    # coverage: coverage.py / pytest-cov TOTAL row, istanbul's "All files", go tool cover, tarpaulin
    cov = (re.findall(r"^TOTAL\s.*?(\d+(?:\.\d+)?)%\s*$", text, re.M) or re.findall(r"^All files\s*\|\s*([\d.]+)", text, re.M)
           or re.findall(r"^total:\s+\(statements\)\s+([\d.]+)%", text, re.M) or re.findall(r"([\d.]+)% coverage, \d+/\d+ lines", text))
    if cov:
        c["coverage_pct"] = float(cov[-1])
    if not c:
        diags = re.findall(r"^[^\s:][^:\n]*:\d+(?::\d+)?:\s|^\S+\(\d+,\d+\): (?:error|warning)", text, re.M)
        if diags:
            c["diagnostics"] = len(diags)
    return c


def guard_git_dir(code: Path) -> Path | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(code), "rev-parse", "--absolute-git-dir"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def guard_default(code: Path, name: str) -> Path | None:
    """Inside .git/, so a snapshot can never be committed by accident and compare finds it by itself."""
    g = guard_git_dir(code)
    return g / "gradekit" / name if g else None


def guard_files(code: Path, sub: str) -> list[str]:
    """The code's files (tracked and new, not ignored), relative to the code folder, limited to SUB."""
    import subprocess
    base = code / sub if sub else code
    files = None
    if guard_git_dir(code):
        try:
            r = subprocess.run(["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z", "--full-name", "."],
                               capture_output=True, timeout=120)
            if r.returncode == 0:
                top = git_out(code, "rev-parse", "--show-toplevel")
                rel_code = Path(code).resolve().relative_to(Path(top).resolve()).as_posix() if top else "."
                files = []
                for f in r.stdout.decode("utf-8", "replace").split("\0"):
                    if not f:
                        continue
                    if rel_code not in ("", "."):
                        if not f.startswith(rel_code + "/"):
                            continue
                        f = f[len(rel_code) + 1:]
                    if (code / f).is_file():
                        files.append(f)
        except (OSError, subprocess.SubprocessError, ValueError):
            files = None
    if files is None:
        files = []
        for root, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in GUARD_SKIP_DIRS)
            for n in sorted(names):
                files.append((Path(root) / n).relative_to(code).as_posix())
    return sorted(files)


def guard_is_gate_file(rel: str) -> bool:
    import fnmatch
    if any(rel == d or rel.startswith(d + "/") or f"/{d}/" in f"/{rel}" for d in GUARD_GATE_DIRS):
        return True
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, pat) for pat in GUARD_GATE_FILES)


def guard_scan(code: Path, sub: str) -> tuple[dict, dict]:
    markers = {k: {"total": 0, "files": {}} for k in GUARD_MARKERS}
    gates = {}
    for rel in guard_files(code, sub):
        p = code / rel
        try:
            if p.stat().st_size > 2_000_000:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if guard_is_gate_file(rel):
            gates[rel] = hashlib.sha256(data).hexdigest()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        for key, rx in GUARD_MARKER_RE.items():
            n = sum(1 for line in text.splitlines() if rx.search(line))
            if n:
                markers[key]["files"][rel] = n
                markers[key]["total"] += n
    return markers, gates


def guard_detect(code: Path) -> list[dict]:
    """A small fallback when no checks were given: the usual test and lint entry points the repo declares."""
    out = []

    def has(*names):
        return any((code / n).exists() for n in names)

    pyproject = (code / "pyproject.toml").read_text(encoding="utf-8", errors="replace") if has("pyproject.toml") else ""
    if has("pytest.ini", "conftest.py", "tox.ini") or "[tool.pytest" in pyproject or (has("tests", "test") and (pyproject or has("setup.py", "setup.cfg"))):
        out.append({"name": "tests", "command": ("python" if os.name == "nt" else "python3") + " -m pytest -q"})
    if has("ruff.toml", ".ruff.toml") or "[tool.ruff" in pyproject:
        out.append({"name": "lint", "command": "ruff check ."})
    if has("package.json"):
        try:
            scripts = (json.loads((code / "package.json").read_text(encoding="utf-8")) or {}).get("scripts") or {}
        except (json.JSONDecodeError, OSError):
            scripts = {}
        for script, name in (("test", "tests"), ("lint", "lint"), ("typecheck", "types"), ("build", "build")):
            if script in scripts and "no test specified" not in str(scripts[script]):
                out.append({"name": name, "command": "npm test --silent" if script == "test" else f"npm run --silent {script}"})
    if has("go.mod"):
        out += [{"name": "tests", "command": "go test ./..."}, {"name": "lint", "command": "go vet ./..."}]
    if has("Cargo.toml"):
        out += [{"name": "tests", "command": "cargo test"}, {"name": "build", "command": "cargo build"}]
    return out


def guard_plan(args, code: Path) -> tuple[list[dict], list[str]]:
    """The checks to run, named, with where each one came from."""
    checks, notes = [], []
    for spec in args.check or []:
        name, sep, cmd = spec.partition("=")
        if not sep or not name.strip() or not cmd.strip():
            die(f"--check takes NAME=COMMAND, e.g. tests=\"pytest -q\"; got '{spec}'")
        checks.append({"name": name.strip(), "command": cmd.strip(), "from": "--check"})
    if args.from_report:
        rep = load_json(args.from_report)
        skipped, installs, trimmed = [], [], []
        for entry in rep.get("commands_run") or []:
            raw = str(entry.get("command") or "").strip()
            cmd = guard_trim_note(raw)
            if cmd != raw:
                trimmed.append(raw[len(cmd):].strip())
            kind = guard_kind(cmd) if cmd else None
            if kind and GUARD_INSTALL_RE.search(cmd):
                installs.append(cmd)
            elif kind:
                checks.append({"name": kind, "command": cmd, "from": "report"})
            elif cmd:
                skipped.append(cmd)
        if trimmed:
            notes.append(f"dropped the grader's notes after {len(trimmed)} command(s), which aren't part of the command: {'; '.join(trimmed[:3])}")
        if installs:
            notes.append(f"left out {len(installs)} command(s) that install packages (the guard never installs anything): "
                         f"{'; '.join(installs[:3])}")
        if skipped:
            notes.append(f"left out {len(skipped)} command(s) from the report that aren't tests, lint, types, coverage, build "
                         f"or audit: {'; '.join(skipped[:5])}{' …' if len(skipped) > 5 else ''}")
    if not checks:
        checks = [{**c, "from": "detected"} for c in guard_detect(code / (args.path or ""))]
        if checks:
            notes.append("no checks given, so these were detected from the repo; give --check NAME=COMMAND "
                         "(or --from-report) to choose them")
    seen, plan, used = set(), [], {}
    for c in checks:
        if c["command"] in seen:
            continue
        seen.add(c["command"])
        base = re.sub(r"[^\w.-]+", "-", c["name"]).strip("-") or "check"
        used[base] = used.get(base, 0) + 1
        plan.append({**c, "name": base if used[base] == 1 else f"{base}-{used[base]}", "kind": guard_kind(c["command"])})
    if not plan:
        die("no checks to run: give --check NAME=COMMAND (repeatable), e.g. --check tests=\"pytest -q\" --check lint=\"ruff check .\", "
            "or --from-report REPORT to use the commands the grader ran")
    return plan, notes


def guard_run(command: str, cwd: Path, timeout: int) -> dict:
    import subprocess
    import time
    env = dict(os.environ, CI=os.environ.get("CI", "true"), NO_COLOR="1", FORCE_COLOR="0", TERM="dumb", PYTHONDONTWRITEBYTECODE="1")
    t0 = time.monotonic()
    timed_out, code, output = False, None, ""
    try:
        r = subprocess.run(command, shell=True, cwd=str(cwd), env=env, capture_output=True, timeout=timeout)
        code, output = r.returncode, (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = ((exc.stdout or b"") + b"\n" + (exc.stderr or b"")).decode("utf-8", "replace")
    except OSError as exc:
        output = str(exc)
    output = ANSI_RE.sub("", output)
    lines = [ln for ln in output.rstrip().splitlines()]
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.monotonic() - t0, 1),
            "counts": guard_counts(output), "output_tail": "\n".join(lines[-GUARD_TAIL_LINES:])[-6000:],
            "output_sha256": hashlib.sha256(output.encode()).hexdigest()}


def guard_take(code: Path, plan: list[dict], sub: str, timeout: int, say=print) -> dict:
    import datetime
    import platform
    cwd = code / sub if sub else code
    head = git_out(code, "rev-parse", "HEAD", check=False) if guard_git_dir(code) else ""
    dirty = bool(git_out(code, "status", "--porcelain", check=False)) if head else None
    checks = []
    for c in plan:
        say(f"  running {c['name']}: {c['command']}")
        res = guard_run(c["command"], cwd, timeout)
        checks.append({"name": c["name"], "kind": c.get("kind"), "command": c["command"], "from": c.get("from"), **res})
    markers, gates = guard_scan(code, sub)
    return {"guard_version": GUARD_VERSION, "taken_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code": {"commit": head or None, "dirty": dirty, "path": sub or None},
            "environment": {"python": platform.python_version(), "platform": platform.platform(terse=True)},
            "checks": checks, "markers": markers, "gate_files": gates}


def guard_state(res: dict | None) -> str:
    if res is None:
        return "not run"
    if res.get("timed_out"):
        return "timed out"
    counts = res.get("counts") or {}
    parts = [guard_count_text(k, counts[k]) for k in GUARD_COUNT_ORDER if k in counts]
    ex = res.get("exit_code")
    status = "ok" if ex == 0 else ("could not start" if ex is None else f"exit {ex}")
    return f"{', '.join(parts)} ({status})" if parts else status


def guard_check_line(res: dict) -> str:
    return f"{res['name']}: {guard_state(res)}"


def guard_diff(before: dict, after: dict, explain: dict, coverage_tolerance: float = 0.1) -> dict:
    items = []

    def item(key, kind, status, detail, b=None, a=None):
        items.append({"key": key, "kind": kind, "status": status, "detail": detail, "before": b, "after": a})

    after_by = {c["name"]: c for c in after.get("checks") or []}
    for b in before.get("checks") or []:
        name = b["name"]
        a = after_by.get(name)
        if a is None or a.get("command") != b.get("command"):
            item(name, "check", "regressed", f"{name} wasn't run after with the same command; compare must run every check the snapshot ran",
                 b.get("command"), (a or {}).get("command"))
            continue
        changed = False
        if b.get("timed_out") != a.get("timed_out"):
            changed = True
            item(f"{name}.exit", "check", "regressed" if a.get("timed_out") else "improved",
                 f"{name} {'now times out' if a.get('timed_out') else 'no longer times out'}", guard_state(b), guard_state(a))
        elif (b.get("exit_code") == 0) != (a.get("exit_code") == 0):
            changed = True
            item(f"{name}.exit", "check", "regressed" if b.get("exit_code") == 0 else "improved",
                 f"{name} {'now fails' if b.get('exit_code') == 0 else 'now passes'} (exit {b.get('exit_code')} → {a.get('exit_code')})",
                 b.get("exit_code"), a.get("exit_code"))
        bc, ac = dict(b.get("counts") or {}), dict(a.get("counts") or {})
        for k in GUARD_COUNT_ORDER:
            if k not in bc and k not in ac:
                continue
            if k not in GUARD_SCORES:   # a tool that printed a summary leaves out the zeros ("41 passed": no failures)
                for have, other in ((bc, ac), (ac, bc)):
                    if k in other and k not in have and have and GUARD_FAMILY.get(k) & set(have):
                        have[k] = 0
            if k not in bc or k not in ac:
                if k in bc and a.get("exit_code") != 0:
                    continue   # a crash that prints no summary is already the exit-code change
                changed = True
                item(f"{name}.{k}", "check", "changed", f"{name}: {GUARD_LABEL[k]} reported {'only after' if k in ac else 'only before'}",
                     bc.get(k), ac.get(k))
                continue
            bv, av = bc[k], ac[k]
            if bv == av or (k == "coverage_pct" and abs(av - bv) < coverage_tolerance):
                continue
            changed = True
            worse = (av < bv) if k in GUARD_HIGHER else (av > bv)
            item(f"{name}.{k}", "check", "regressed" if worse else "improved",
                 f"{name}: {guard_count_text(k, bv)} → {guard_count_text(k, av)}", bv, av)
        if not changed:
            item(name, "check", "same", f"{name}: {guard_state(a)}", guard_state(b), guard_state(a))
    for name, a in after_by.items():
        if name not in {b["name"] for b in before.get("checks") or []}:
            item(name, "check", "changed", f"{name} is new (not in the snapshot), so it isn't compared", None, guard_state(a))
    for key in GUARD_MARKERS:
        bm = (before.get("markers") or {}).get(key) or {"total": 0, "files": {}}
        am = (after.get("markers") or {}).get(key) or {"total": 0, "files": {}}
        label = key.replace("_", " ")
        if am["total"] == bm["total"]:
            item(key, "marker", "same", f"{label}: {am['total']}", bm["total"], am["total"])
            continue
        rose = sorted(f for f, n in am["files"].items() if n > bm["files"].get(f, 0))
        where = f" (more in {', '.join(rose[:5])}{' …' if len(rose) > 5 else ''})" if rose else ""
        item(key, "marker", "regressed" if am["total"] > bm["total"] else "improved",
             f"{label}: {bm['total']} → {am['total']}{where if am['total'] > bm['total'] else ''}", bm["total"], am["total"])
    bg, ag = before.get("gate_files") or {}, after.get("gate_files") or {}
    for f in sorted(set(bg) | set(ag)):
        if bg.get(f) != ag.get(f):
            how = "added" if f not in bg else "removed" if f not in ag else "changed"
            item(f"gate:{f}", "gate", "review", f"{f} {how}: check it adds checks and weakens none", None, how)
    used = set()
    for it in items:
        if it["status"] != "regressed":
            continue
        for k in (it["key"], it["key"].split(".")[0]):
            if k in explain:
                it["status"], it["explanation"] = "explained", explain[k]
                used.add(k)
                break
    regressions = [it["key"] for it in items if it["status"] == "regressed"]
    return {"verdict": "FAIL" if regressions else "PASS", "regressions": regressions,
            "explained": [{"key": it["key"], "reason": it["explanation"]} for it in items if it["status"] == "explained"],
            "improved": [it["key"] for it in items if it["status"] == "improved"],
            "review": [it["key"][5:] for it in items if it["status"] == "review"],
            "unused_explanations": sorted(set(explain) - used), "items": items}


def guard_text(diff: dict, before: dict, after: dict, commits: int | None) -> str:
    bc, ac = (before.get("code") or {}), (after.get("code") or {})
    span = f"{(bc.get('commit') or 'no git')[:10]} → {(ac.get('commit') or 'no git')[:10]}"
    if commits is not None:
        span += f" ({commits} commit{'s' if commits != 1 else ''}{', plus uncommitted changes' if ac.get('dirty') else ''})"
    lines = [f"guard: {len(before.get('checks') or [])} check(s), {span}"]
    mark = {"regressed": "REGRESSED", "improved": "better", "same": "same", "changed": "note", "review": "review", "explained": "explained"}
    for it in diff["items"]:
        lines.append(f"  [{mark[it['status']]}] {it['detail']}" + (f" (explained: {it['explanation']})" if it.get("explanation") else ""))
    for k in diff["unused_explanations"]:
        lines.append(f"  note: --explain {k} matched nothing that got worse")
    if diff["regressions"]:
        lines.append(f"verdict: FAIL, {len(diff['regressions'])} regression(s): {', '.join(diff['regressions'])}. "
                     "Fix or revert, or if one is deliberate, say why with --explain KEY=\"why\"")
    else:
        lines.append("verdict: PASS, nothing got worse" + (f" ({len(diff['explained'])} explained)" if diff["explained"] else ""))
    return "\n".join(lines)


def cmd_guard_snapshot(args) -> int:
    code = Path(args.code).resolve()
    if not code.is_dir():
        die(f"code folder not found: {args.code}")
    if args.path and not (code / args.path).is_dir():
        die(f"--path {args.path}: no such folder in {code}")
    plan, notes = guard_plan(args, code)
    out = Path(args.out) if args.out else guard_default(code, "guard-before.json")
    if args.list:
        emit(args, {"checks": plan, "out": str(out) if out else None, "notes": notes},
             "\n".join([f"{c['name']}: {c['command']} (from {c['from']})" for c in plan] + [f"note: {n}" for n in notes]))
        return 0
    if out is None:
        die(f"{code} isn't a git checkout, so there's no safe default place for the snapshot: give --out FILE (outside the code)")
    for n in notes:
        print(f"note: {n}")
    snap = guard_take(code, plan, args.path or "", args.timeout)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, snap)
    lines = [guard_check_line(c) for c in snap["checks"]]
    for c in snap["checks"]:
        if c["exit_code"] in (126, 127) or c["exit_code"] is None:
            lines.append(f"warning: {c['name']} couldn't run (exit {c['exit_code']}); fix the command, or the baseline is meaningless")
    lines.append("markers: " + ", ".join(f"{k.replace('_', ' ')} {v['total']}" for k, v in snap["markers"].items())
                 + f"; {len(snap['gate_files'])} gate file(s) fingerprinted")
    lines.append(f"wrote {out}" + ("" if args.out else " (inside .git, so it's never committed)"))
    if snap["code"]["dirty"]:
        lines.append("note: the working tree has uncommitted changes; the snapshot includes them")
    emit(args, {"snapshot": str(out), "checks": [{k: c[k] for k in ("name", "command", "exit_code", "timed_out", "counts")} for c in snap["checks"]],
                "markers": {k: v["total"] for k, v in snap["markers"].items()}, "gate_files": len(snap["gate_files"]), "notes": notes},
         "\n".join(lines))
    return 0


def cmd_guard_compare(args) -> int:
    code = Path(args.code).resolve()
    before_path = Path(args.before) if args.before else guard_default(code, "guard-before.json")
    if before_path is None:
        die("give --before FILE: the snapshot `guard snapshot --out` wrote")
    if not before_path.is_file():
        die(f"no snapshot at {before_path}: run `gradekit guard snapshot` before changing anything")
    before = load_json(before_path)
    if before.get("guard_version") != GUARD_VERSION:
        die(f"{before_path} isn't a guard snapshot (version {before.get('guard_version')!r})")
    explain = {}
    for spec in args.explain or []:
        key, sep, why = spec.partition("=")
        if not sep or not why.strip():
            die(f"--explain takes KEY=REASON, e.g. tests.passed=\"removed the tests of the deleted export helper\"; got '{spec}'")
        explain[key.strip()] = why.strip()
    if args.after:
        after = load_json(args.after)
    else:
        if not code.is_dir():
            die(f"code folder not found: {args.code}")
        sub = (before.get("code") or {}).get("path") or ""
        plan = [{k: c.get(k) for k in ("name", "kind", "command", "from")} for c in before.get("checks") or []]
        after = guard_take(code, plan, sub, args.timeout)
    diff = guard_diff(before, after, explain, args.coverage_tolerance)
    commits = None
    b_commit, a_commit = (before.get("code") or {}).get("commit"), (after.get("code") or {}).get("commit")
    if b_commit and a_commit and code.is_dir() and guard_git_dir(code):
        n = git_out(code, "rev-list", "--count", f"{b_commit}..{a_commit}", check=False)
        commits = int(n) if n.isdigit() else None
    result = {**diff, "commits": commits, "before": before, "after": after}
    out = Path(args.out) if args.out else guard_default(code, "guard-compare.json")
    text = guard_text(diff, before, after, commits)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, result)
        text += f"\nwrote {out} (for `render log --guard`)"
    emit(args, {k: v for k, v in result.items() if k not in ("before", "after")} | {"written": str(out) if out else None}, text)
    return 2 if diff["regressions"] else 0


def render_guard(cmp: dict) -> list[str]:
    before, after = cmp.get("before") or {}, cmp.get("after") or {}
    a_by = {c["name"]: c for c in after.get("checks") or []}
    bc, ac = before.get("code") or {}, after.get("code") or {}
    span = f"`{(bc.get('commit') or '?')[:7]}` → `{(ac.get('commit') or '?')[:7]}`"
    out = ["**Guard** (the code's own checks, run before and after with the same commands)", "",
           f"Verdict: **{cmp.get('verdict', '?')}**, {span}" + (f", {cmp['commits']} commit(s)" if cmp.get("commits") is not None else "")
           + (" plus uncommitted changes" if ac.get("dirty") else "") + ".", "",
           "| Check | Command | Before | After | Result |", "|---|---|---|---|---|"]
    status_of = {}
    for it in cmp.get("items") or []:
        if it["kind"] == "check":
            name = it["key"].split(".")[0]
            rank = {"regressed": 4, "explained": 3, "improved": 2, "changed": 1, "same": 0}
            if rank.get(it["status"], 0) >= rank.get(status_of.get(name, "same"), 0):
                status_of[name] = it["status"]
    word = {"regressed": "**worse**", "explained": "worse, explained", "improved": "better", "changed": "changed", "same": "same"}
    for b in before.get("checks") or []:
        a = a_by.get(b["name"])
        cmd = b["command"].replace("|", "\\|")
        out.append(f"| {b['name']} | `{cmd}` | {guard_state(b)} | {guard_state(a)} | {word[status_of.get(b['name'], 'same')]} |")
    mk = []
    for key in GUARD_MARKERS:
        bt = ((before.get("markers") or {}).get(key) or {}).get("total", 0)
        at = ((after.get("markers") or {}).get(key) or {}).get("total", 0)
        mk.append(f"{key.replace('_', ' ')} {bt} → {at}")
    out += ["", "Markers in the code: " + "; ".join(mk) + "."]
    if cmp.get("review"):
        out += ["", "Gate files changed, to review (a change may add checks, never weaken one): " + ", ".join(f"`{f}`" for f in cmp["review"]) + "."]
    if cmp.get("explained"):
        out += ["", "Explained:"] + [f"- `{e['key']}`: {e['reason']}" for e in cmp["explained"]]
    if cmp.get("regressions"):
        out += ["", f"**Not explained:** {', '.join(f'`{k}`' for k in cmp['regressions'])}."]
    return out



# =========================================================================== rubric, one benchmark at a time
# The rubric files (rubric/A-…F-…, X-conditional.md) are the source. `gradekit rubric A3` prints one benchmark,
# so a grader loads only what it's grading; rubric/rubric.json is the same as data (a test keeps it current).

RUBRIC_FIELDS = {"Measures": "measures", "Not this": "not_this", "Assess": "assess", "Anchors": "anchors", "Caps": "caps"}


def parse_rubric(catalog: dict | None = None) -> dict:
    catalog = catalog or load_catalog()
    caps = catalog_caps(catalog)
    pillars, benches = {}, []
    for pid, p in catalog["pillars"].items():
        path = SUITE_DIR / p["rubric"]
        lines = path.read_text(encoding="utf-8").splitlines()
        question = next((ln.strip().strip("*") for ln in lines if ln.startswith("*") and ln.endswith("*")), None)
        pillars[pid] = {"name": p["name"], "question": question, "file": p["rubric"]}
        cur, key = None, None
        for ln in lines:
            m = re.match(r"## ([A-FX]\d)\. (.+?)(?: \(\*(.+)\*\))?\s*$", ln)
            if m:
                cur = {"id": m.group(1), "name": m.group(2), "pillar": pid, "applies_when": m.group(3)}
                benches.append(cur)
                key = None
                continue
            if cur is None:
                continue
            m = re.match(r"- \*\*(.+?):\*\*\s*(.*)$", ln)
            if m and m.group(1) in RUBRIC_FIELDS:
                key = RUBRIC_FIELDS[m.group(1)]
                if key == "anchors":
                    cur["anchors"] = {}
                elif key == "caps":
                    cur["caps"] = [{k: c[k] for k in ("id", "when", "max")} for c in caps.values() if c["benchmark"] == cur["id"]]
                else:
                    cur[key] = m.group(2).strip()
                continue
            m = re.match(r"\s+- \*\*(\d+(?:–\d+)?):\*\*\s*(.*)$", ln)
            if m and key == "anchors":
                cur["anchors"][m.group(1)] = m.group(2).strip()
                continue
            m = re.match(r"\s+- (.+)$", ln)
            if m and key in ("measures", "not_this", "assess"):   # sub-points, e.g. A4's idempotence and determinism
                cur[key] = (cur.get(key, "") + " " + re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1).strip())).strip()
    return {"_about": "Generated from the rubric files by `gradekit rubric --json --out rubric/rubric.json`. Don't edit.",
            "suite_version": catalog["suite_version"], "pillars": pillars, "benchmarks": benches}


def rubric_text(b: dict, pillar: dict) -> str:
    out = [f"{b['id']}. {b['name']}" + (f" (only for {b['applies_when']})" if b.get("applies_when") else "")
           + f"  [pillar {b['pillar']}: {pillar['name']}]"]
    for key, label in (("measures", "Measures"), ("not_this", "Not this"), ("assess", "Assess")):
        if b.get(key):
            out.append(f"{label}: {b[key]}")
    if b.get("anchors"):
        out.append("Anchors: " + "  ".join(f"{k}: {v}" for k, v in b["anchors"].items()))
    else:
        out.append("Anchors: the general score scale (prompts/grader.md, Part 3)")
    if b.get("caps"):
        out.append("Caps: " + "  ".join(f"{c['id']}: {c['when']} → max {c['max']}" for c in b["caps"]))
    return "\n".join(out)


def cmd_rubric(args) -> int:
    data = parse_rubric()
    want = [w.upper() for w in args.ids or []]
    picked = [b for b in data["benchmarks"] if not want or b["id"] in want or b["pillar"] in want]
    unknown = [w for w in want if w not in {b["id"] for b in data["benchmarks"]} and w not in data["pillars"]]
    if unknown:
        die(f"unknown benchmark or pillar: {', '.join(unknown)} (benchmarks look like A3; pillars are {', '.join(data['pillars'])})")
    if args.json:
        pass
    if args.out:
        if want:
            die("--out writes the whole rubric; leave out the IDs")
        Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        emit(args, {"written": args.out, "benchmarks": len(data["benchmarks"])}, f"wrote {args.out}")
        return 0
    emit(args, {"pillars": data["pillars"], "benchmarks": picked}, "\n\n".join(rubric_text(b, data["pillars"][b["pillar"]]) for b in picked))
    return 0



# =========================================================================== MCP server (agents without a shell)
# `gradekit mcp` speaks the Model Context Protocol over stdin/stdout (JSON-RPC 2.0, one message per line). Its tools
# are the command line's own commands, with input schemas made from their arguments, so the two never drift apart.
# Each call runs the command in-process with --json and returns the usual envelope.

MCP_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_SKIP = {("mcp",)}


def mcp_tools(ap=None) -> list[dict]:
    ap = ap or build_parser()
    tools = []
    for leaf in leaf_parsers(ap):
        words = tuple(leaf.prog.split()[1:])
        if not words or words in MCP_SKIP:
            continue
        props, required, order = {}, [], []
        for a in leaf._actions:
            if isinstance(a, (argparse._HelpAction, argparse._SubParsersAction)) or a.dest in ("json", "help"):
                continue
            if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                schema = {"type": "boolean"}
            elif isinstance(a, argparse._AppendAction) or a.nargs in ("+", "*"):
                schema = {"type": "array", "items": {"type": "string"}}
            elif a.type is int:
                schema = {"type": "integer"}
            elif a.type is float:
                schema = {"type": "number"}
            else:
                schema = {"type": "string"}
            if a.choices is not None and schema["type"] in ("string", "integer"):
                schema["enum"] = [c for c in a.choices]
            if a.help and a.help != argparse.SUPPRESS:
                schema["description"] = a.help % {"default": a.default} if "%(" in a.help else a.help
            props[a.dest] = schema
            order.append(a.dest)
            if not a.option_strings and a.nargs not in ("?", "*"):
                required.append(a.dest)
            elif a.required:
                required.append(a.dest)
        props["cwd"] = {"type": "string", "description": "folder to run in (default: the server's), e.g. the grading repo root"}
        tools.append({"name": "_".join(words).replace("-", "_"), "description": leaf.description or leaf_help(ap, words) or " ".join(words),
                      "inputSchema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
                      "_words": words, "_order": order})
    return tools


def leaf_help(ap, words) -> str | None:
    parser = ap
    help_ = None
    for w in words:
        sub = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub is None or w not in sub.choices:
            return help_
        help_ = next((c.help for c in sub._choices_actions if c.dest == w), help_)
        parser = sub.choices[w]
    return help_


def mcp_argv(tool: dict, leaf, arguments: dict) -> list[str]:
    """Command-line arguments for a tool call: positionals in order, then the options."""
    by_dest = {a.dest: a for a in leaf._actions}
    unknown = sorted(set(arguments) - set(tool["inputSchema"]["properties"]))
    if unknown:
        die(f"unknown argument(s) for {tool['name']}: {', '.join(unknown)}")
    argv = list(tool["_words"])
    for dest in tool["_order"]:
        a = by_dest[dest]
        if dest not in arguments or arguments[dest] is None:
            continue
        v = arguments[dest]
        if not a.option_strings:
            argv += [str(x) for x in v] if isinstance(v, list) else [str(v)]
            continue
        flag = a.option_strings[-1] if a.option_strings[-1].startswith("--") else a.option_strings[0]
        if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            if bool(v) == isinstance(a, argparse._StoreTrueAction):
                argv.append(flag)
        elif isinstance(a, argparse._AppendAction):
            for x in v if isinstance(v, list) else [v]:
                argv += [flag, str(x)]
        elif a.nargs in ("+", "*"):
            argv += [flag] + [str(x) for x in (v if isinstance(v, list) else [v])]
        else:
            argv += [flag, str(v)]
    return argv


def mcp_call(name: str, arguments: dict, tools: dict, leaves: dict) -> dict:
    tool = tools.get(name)
    if tool is None:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    arguments = dict(arguments or {})
    cwd = arguments.pop("cwd", None)
    try:
        argv = mcp_argv(tool, leaves[tool["_words"]], arguments) + ["--json"]
    except GradekitError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    buf, err = io.StringIO(), io.StringIO()
    here = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            try:
                main(argv)
            except SystemExit as e:   # bad arguments: argparse exits with its usage message
                env = {"ok": False, "exit_code": e.code if isinstance(e.code, int) else 64, "command": " ".join(tool["_words"]),
                       "result": None, "text": "", "error": err.getvalue().strip()}
                return {"content": [{"type": "text", "text": json.dumps(env, ensure_ascii=False)}], "structuredContent": env, "isError": True}
    except OSError as e:
        return {"content": [{"type": "text", "text": f"can't run in {cwd}: {e}"}], "isError": True}
    finally:
        os.chdir(here)
    try:
        env = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        env = {"ok": False, "exit_code": 1, "command": " ".join(tool["_words"]), "result": None, "text": buf.getvalue(),
               "error": err.getvalue().strip() or "no JSON output"}
    return {"content": [{"type": "text", "text": json.dumps(env, ensure_ascii=False)}], "structuredContent": env,
            "isError": not env.get("ok", False)}


def mcp_handle(msg: dict, state: dict) -> dict | None:
    """One JSON-RPC message in, its response out (None for notifications)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def fail(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if mid is None:
        return None   # notifications/initialized and the like
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in MCP_PROTOCOLS else MCP_PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "gradekit", "version": kit_version()},
                   "instructions": "The Code Grading Suite's gradekit commands as tools. Start with the card for your role "
                                   "(prompts/cards/ in the kit) and `rubric` for one benchmark at a time. Every tool returns "
                                   "{ok, exit_code, command, result, text}; `cwd` sets the folder a tool runs in."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{k: v for k, v in t.items() if not k.startswith("_")} for t in state["tools"].values()]})
    if method == "tools/call":
        return ok(mcp_call(params.get("name"), params.get("arguments") or {}, state["tools"], state["leaves"]))
    return fail(-32601, f"method not found: {method}")


def cmd_mcp(args) -> int:
    ap = build_parser()
    tools = mcp_tools(ap)
    if args.list:
        emit(args, {"tools": [t["name"] for t in tools]}, "\n".join(f"{t['name']}: {t['description']}" for t in tools))
        return 0
    state = {"tools": {t["name"]: t for t in tools}, "leaves": {tuple(p.prog.split()[1:]): p for p in leaf_parsers(ap)}}
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
        else:
            resp = mcp_handle(msg, state) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None,
                                                                         "error": {"code": -32600, "message": "invalid request"}}
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


# =========================================================================== web API (used by the website via Pyodide)

def _web_layers(p: dict) -> list[tuple[str, dict]]:
    layers = []
    if p.get("org_toml"):
        layers.append(("org.toml", parse_toml(p["org_toml"], "org.toml")))
    if p.get("project_toml"):
        layers.append(("project.toml", parse_toml(p["project_toml"], "project.toml")))
    if p.get("project") is not None:
        layers.append(("project (form)", p["project"]))
    return layers


def _web_cfg(p: dict, report: dict | None = None) -> tuple[dict, str]:
    layers = _web_layers(p)
    comp = ((report or {}).get("component") or {}).get("name")
    comp = None if comp == "repo" else comp
    fallback = ((report or {}).get("config") or {}).get("preset")
    decisions = p.get("decisions") if isinstance(p.get("decisions"), list) else parse_list_text(p.get("decisions_json"), "decisions", "decisions.json")
    dispositions = p.get("dispositions") if isinstance(p.get("dispositions"), list) else parse_list_text(p.get("dispositions_json"), "dispositions", "dispositions.json")
    cfg = resolve_layers(layers, component=comp, preset_fallback=fallback, component_required=False,
                         decisions=decisions, dispositions=dispositions)
    source = " + ".join(n for n, _ in layers) if layers else f"suite defaults (preset '{cfg['preset']}' from the report)"
    return cfg, source


def _api_glossary(p):
    return {"groups": load_glossary()["groups"]}


def _api_info(p):
    merged = load_toml(DEFAULTS_PATH)
    for _, layer in _web_layers({"org_toml": p.get("org_toml")}):
        merged = deep_merge(merged, layer)
    return {"suite_version": load_catalog()["suite_version"], "scoring_version": merged.get("suite_version"), "catalog": load_catalog(),
            "questions": merged.get("questions", {}), "presets": merged.get("presets", {}),
            "base_weights": merged.get("weights", {}).get("base", {}), "gates": merged.get("gates", {}),
            "zone_settings": merged.get("zone_settings", {}), "targets": merged.get("targets", {}),
            "maturity": merged.get("maturity", {}), "review": merged.get("review", {}),
            "starter_decisions": starter_json("decisions"), "starter_dispositions": starter_json("dispositions"),
            "grading_repo_readme": GRADING_REPO_README, "side_files": SIDE_FILES}


def _api_build(p):
    defaults = load_toml(DEFAULTS_PATH)
    name = ((p.get("project") or {}).get("project") or {}).get("name")
    path = p.get("path") or f"projects/{slug(name) if name else '<name>'}/project.toml"
    text = render_project_toml(p.get("project") or {}, defaults, path=path)
    try:
        cfg, _ = _web_cfg({"org_toml": p.get("org_toml"), "project_toml": text})
        return {"toml": text, "config": cfg, "config_error": None}
    except GradekitError as e:
        return {"toml": text, "config": None, "config_error": str(e)}


def _api_parse(p):
    return {"project": parse_toml(p.get("toml", ""), p.get("name") or "project.toml")}


def _api_zone_test(p):
    cfg, _ = _web_cfg(p)
    out = []
    for path in p.get("paths", []):
        zname, crit = zone_for_path(path, cfg)
        out.append({"path": path, "zone": zname, "criticality": crit})
    return {"results": out}


def _api_check(p):
    report = p["report"]
    cfg, source = _web_cfg(p, report)
    errors, warnings = validate_report(report, cfg, load_catalog())
    notes = [w for w in warnings if w.startswith("jsonschema not installed")]  # about this browser, not the report
    warnings = [w for w in warnings if w not in notes]
    roll = compute_rollup(report, cfg)
    rc = report.get("config") or {}
    return {"validation": {"errors": errors, "warnings": cfg.get("warnings", []) + warnings, "notes": notes},
            "rollup": roll, "config_source": source, "config_hash_match": rc.get("hash") == cfg["hash"],
            "publish": {"public": bool((cfg.get("publishing") or {}).get("public")), "problems": publish_problems(report, require_redacted=False),
                        "sensitive": sorted(sensitive_ids(report))},
            "config": {k: cfg.get(k) for k in ("hash", "preset", "answers", "gates", "project", "review", "zones", "publishing")},
            "weights": {k: v["weight"] for k, v in cfg["weights"].items()}}


def _api_consensus(p):
    runs = p["runs"]
    cfg, source = _web_cfg(p, runs[0] if runs else None)
    res = compute_consensus(runs, cfg)
    return {**res, "config_source": source}


def _api_compare(p):
    cfg, source = _web_cfg(p, p.get("new"))
    return {"diff": compute_diff(p["old"], p["new"], cfg, cfg), "config_source": source}


def _api_verify_zip(p):
    return verify_evidence(p["report"], zip_reader(p["zip_path"]), int(p.get("tolerance", 2)))


def _api_redact(p):
    public, leaks = redact_report(p["report"])
    return {"report": public, "leaks": leaks, "withheld": public["publishing"]["withheld"]}


def _api_decisions_update(p):
    entries = p.get("decisions", [])
    for d in entries:
        if not d.get("action_id") or not isinstance(d.get("approved"), bool):
            die("each decision needs action_id and approved (true/false)")
    return {"json": append_entries(p.get("decisions_json"), "decisions", entries), "added": len(entries)}


def _api_scan_zip(p):
    """Sort out a dropped .zip: a grading repo / project folder (returns its projects), or code (for citations)."""
    import zipfile

    zf = zipfile.ZipFile(p["zip_path"])
    names = [n for n in zf.namelist() if not n.endswith("/") and "/__MACOSX/" not in "/" + n]
    return {"kind": "grading" if any(n.endswith("/" + PROJECT_FILE) or n == PROJECT_FILE or re.search(r"(^|/)reports/[^/]+/report\.json$", n)
                                     for n in names) else "code",
            "projects": scan_paths({n: (lambda n=n: zf.read(n).decode("utf-8", errors="replace")) for n in names})}


SIDE_FILES = {PROJECT_FILE: "project", DECISIONS_FILE: "decisions", DISPOSITIONS_FILE: "dispositions", "org.toml": "org"}


def scan_layout(paths: list[str]) -> list[dict]:
    """Find the projects in a grading repo (or one project folder) from file paths alone.
    Each: {name, root, side: {file name: path}, org: path, reports: {folder: {report: path, runs: [paths]}}}."""
    projects: dict[str, dict] = {}
    org = None
    for path in paths:
        parts = path.strip("/").split("/")
        if parts[-1] == "org.toml":
            org = path
            continue
        if "reports" in parts:
            i = len(parts) - 1 - parts[::-1].index("reports")
            root, rest = parts[:i], parts[i + 1:]
        else:
            root, rest = parts[:-1], parts[-1:]
        if not rest:
            continue
        key = "/".join(root)
        proj = projects.setdefault(key, {"name": root[-1] if root else "project", "root": key, "side": {}, "reports": {}})
        if len(rest) == 1 and rest[0] in SIDE_FILES and "reports" not in parts:
            proj["side"][rest[0]] = path
        elif len(rest) == 2 and rest[1] == "report.json":
            proj["reports"].setdefault(rest[0], {"runs": []})["report"] = path
        elif len(rest) == 3 and rest[1] == "runs" and rest[2].endswith(".json"):
            proj["reports"].setdefault(rest[0], {"runs": []})["runs"].append(path)
    found = [p for p in projects.values() if p["side"].get(PROJECT_FILE) or any(r.get("report") for r in p["reports"].values())]
    # Copies of the suite (any folder with tools/gradekit.py, such as bundle/bare/ or a website's suite/)
    # ship an example project. Skip projects inside them, unless they're all there is.
    clean = [x.strip("/") for x in paths]
    kits = [x[: -len("tools/gradekit.py")] for x in clean if x == "tools/gradekit.py" or x.endswith("/tools/gradekit.py")]
    outside = [p for p in found if not any((p["root"] + "/").startswith(k) for k in kits)]
    if not outside:  # only copies of the example: show each project once (the shortest path)
        seen: set = set()
        outside = [p for p in sorted(found, key=lambda p: len(p["root"])) if not (p["name"] in seen or seen.add(p["name"]))]
    names: set = set()
    for p in outside:
        p["org"] = org
        p["reports"] = {f: r for f, r in p["reports"].items() if r.get("report")}
        if p["name"] in names:
            p["name"] = p["root"]
        names.add(p["name"])
    return outside


def scan_paths(files: dict) -> dict:
    """Group files of a grading repo (or one project folder) by project, with their contents.
    files: path -> callable returning text."""
    out = {}
    for p in scan_layout(list(files)):
        texts = {f: files[r["report"]]() for f, r in p["reports"].items()}
        _, need = order_report_folders(list(texts))
        order = order_report_folders(list(texts), {f: run_date_of(texts[f]) for f in need})[0]
        side = {k: files[v]() for k, v in p["side"].items()}
        out[p["name"]] = {
            "root": p["root"], "project_toml": side.get(PROJECT_FILE), "decisions_json": side.get(DECISIONS_FILE),
            "dispositions_json": side.get(DISPOSITIONS_FILE), "org_toml": files[p["org"]]() if p["org"] else None,
            "reports": [{"folder": f, "report": texts[f], "runs": [files[x]() for x in p["reports"][f]["runs"]]} for f in order]}
    return out


def classify_files(files: list[dict]) -> list[str]:
    """What each loose file dropped on the Review page is, in the order given.
    files: [{name, json (parsed, if it's JSON), error (if it didn't parse), role (if the person chose one)}].
    The newest report (by run.date) is the one reviewed; another with the same commit is a run of it
    (for consensus); any other report is an earlier one to compare with."""
    roles: list[str] = []
    fixed: list[bool] = []
    for f in files:
        name, data = str(f.get("name") or ""), f.get("json")
        if f.get("role"):
            roles.append(f["role"])
            fixed.append(True)
            continue
        fixed.append(False)
        run = (data.get("run") or {}) if isinstance(data, dict) else {}
        if f.get("error"):
            role = "ignore"
        elif name in SIDE_FILES:
            role = SIDE_FILES[name]
        elif name.lower().endswith(".zip"):
            role = "zip"
        elif name.lower().endswith(".toml"):
            role = "org" if "project" in roles else "project"
        elif isinstance(data, dict) and isinstance(data.get("benchmarks"), list):
            main = next((i for i, r in enumerate(roles) if r == "report"), None)
            if main is None:
                role = "report"
            else:
                mrun = (files[main].get("json") or {}).get("run") or {}
                if run.get("commit") and run.get("commit") == mrun.get("commit"):
                    role = "run"
                elif not fixed[main] and str(run.get("date") or "") > str(mrun.get("date") or ""):
                    roles[main], role = "previous", "report"
                else:
                    role = "previous"
        elif isinstance(data, dict) and isinstance(data.get("decisions"), list):
            role = "decisions"
        elif isinstance(data, dict) and isinstance(data.get("dispositions"), list):
            role = "dispositions"
        else:
            role = "ignore"
        roles.append(role)
    return roles



def _api_scan_layout(p):
    return {"projects": scan_layout(list(p.get("paths") or []))}


def _api_order_reports(p):
    ordered, need = order_report_folders(list(p.get("folders") or []), p.get("run_dates") or {})
    return {"ordered": ordered, "need_run_dates": need}


def _api_classify(p):
    return {"roles": classify_files(list(p.get("files") or []))}


WEB_API = {"info": _api_info, "build": _api_build, "parse": _api_parse, "zone_test": _api_zone_test,
           "check": _api_check, "consensus": _api_consensus, "compare": _api_compare,
           "verify_zip": _api_verify_zip, "redact": _api_redact, "decisions_update": _api_decisions_update,
           "scan_zip": _api_scan_zip, "scan_layout": _api_scan_layout, "glossary": _api_glossary, "order_reports": _api_order_reports,
           "classify": _api_classify}


def web_api(name: str, payload: dict) -> dict:
    fn = WEB_API.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown call '{name}'"}
    try:
        return {"ok": True, **fn(payload or {})}
    except GradekitError as e:
        return {"ok": False, "error": str(e)}
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return {"ok": False, "error": f"unexpected input ({type(e).__name__}: {e})"}


# =========================================================================== main

def build_parser() -> argparse.ArgumentParser:
    ap = CliParser(prog="gradekit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def provenance(p):
        p.add_argument("--model", help="the model grading, e.g. claude-opus-5-5 (a finished report needs it)")
        p.add_argument("--session", help="the agent session's ID or URL, so reviewers can see who graded")
        p.add_argument("--work-order", help="the work order this run answers (its ID)")

    def with_config(p):
        p.add_argument("--project", metavar="NAME", help="project folder projects/NAME in the grading repo")
        p.add_argument("--grading-repo", metavar="DIR", help="grading repo root (default: current folder)")
        p.add_argument("--project-dir", metavar="DIR", help="a project folder anywhere (project.toml, decisions.json, reports/…)")
        p.add_argument("--config", action="append", metavar="FILE",
                       help="config TOML (repeatable, layered in order over defaults) or one effective-config JSON; "
                            "default: the project's project.toml (+ org.toml at the grading repo root)")
        p.add_argument("--component", help="monorepo component name from the project config")

    p = sub.add_parser("init", help="create projects/NAME/ in a grading repo (or a single project.toml)")
    p.add_argument("--project", metavar="NAME", help="create projects/NAME/ with project.toml, decisions.json, dispositions.json, reports/")
    p.add_argument("--grading-repo", metavar="DIR", help="grading repo root (default: current folder)")
    p.add_argument("--code-repo", metavar="URL", help="where the code lives")
    p.add_argument("--path", metavar="SUBFOLDER", help="monorepos: the subfolder this project covers")
    p.add_argument("--preset", default="default")
    p.add_argument("--name", default="my-project", help="project name when writing a single file with --out")
    p.add_argument("--answer", action="append", metavar="Q=A", help="e.g. --answer data_sensitivity=financial")
    p.add_argument("--out", default="project.toml")
    p.add_argument("--ci", choices=["github", "gitlab"], help="also add the grading check for pull requests (see the kit's ci/)")
    p.add_argument("--site", metavar="URL", help="with --ci: your suite website's address (else set SUITE_SITE in the CI settings)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("resolve", help="show / write the effective config")
    with_config(p)
    p.add_argument("--explain", metavar="ID", help="explain one benchmark's weight and gate status")
    p.add_argument("--out", help="write the effective config JSON here")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("presets", help="compare weights and gates across presets")
    p.add_argument("--config", action="append", metavar="FILE", help="org-level config to layer in")
    p.add_argument("--markdown", action="store_true")
    p.set_defaults(fn=cmd_presets)

    p = sub.add_parser("validate", help="schema + config + semantic checks")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--publish", action="store_true", help="also fail unless the report is safe to commit to a public grading repo")
    with_config(p)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("verify-evidence", help="check code citations against the repo")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--repo", default=".", help="repo folder, or a .zip of it (default: current folder)")
    p.add_argument("--tolerance", type=int, default=2, help="line drift allowed around the cited range (default 2)")
    p.set_defaults(fn=cmd_verify_evidence)

    p = sub.add_parser("rollup", help="compute gates, zones, scores, targets, maturity and priorities")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    with_config(p)
    p.add_argument("--write", action="store_true", help="write rollup and targets back into the report")
    p.add_argument("--out", help="write the updated report here instead")
    p.set_defaults(fn=cmd_rollup)

    p = sub.add_parser("stability", help="median consensus across independent runs")
    p.add_argument("reports", nargs="+")
    with_config(p)
    p.add_argument("--out", help="write the consensus report here")
    p.add_argument("--strict", action="store_true", help="exit 3 if any benchmark is unstable")
    p.set_defaults(fn=cmd_stability)

    p = sub.add_parser("diff", help="compare two reports (default: the project's previous and latest)")
    p.add_argument("old", nargs="?")
    p.add_argument("new", nargs="?")
    with_config(p)
    p.add_argument("--old-config", action="append", metavar="FILE", help="config the old report was graded with, if different")
    p.add_argument("--fail-on-regression", action="store_true")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("calibrate", help="compare a report with expected scores")
    p.add_argument("report")
    p.add_argument("expected")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("redact", help="make a copy safe to publish: no hidden-check details, sensitive findings withheld")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--out", help="where to write the public copy (default: REPORT.shared.json)")
    g.add_argument("--in-place", action="store_true",
                   help="for grading repos: move the full report to REPORT.private.json and write the public one in its place")
    p.set_defaults(fn=cmd_redact)

    p = sub.add_parser("rollup-repo", help="combine per-component reports (each must already have a rollup)")
    p.add_argument("reports", nargs="+", help="the component reports, or one report folder (with components/)")
    p.add_argument("--out")
    p.add_argument("--write", action="store_true", help="with a folder: store the result in its report.json as repo_rollup")
    p.set_defaults(fn=cmd_rollup_repo)

    # ------------------------------------------------------------ report authoring
    p = sub.add_parser("report", help="build a report step by step (graders): new, cite, finding, score, check…",
                       description="Build a report without typing JSON. Weights, targets, quotes and IDs come from the tool; "
                                   "every command re-checks the report against the project's config.")
    rsub = p.add_subparsers(dest="report_cmd", required=True, metavar="ACTION")

    def report_arg(q):
        q.add_argument("report", help="the report JSON being written")
        with_config(q)

    def evidence_args(q, cite_help="FILE:LINE or FILE:START-END; the quote is copied from the file (repeatable)"):
        q.add_argument("--cite", action="append", metavar="FILE:LINES", help=cite_help)
        q.add_argument("--repo", metavar="DIR_OR_ZIP", help="the code checkout (or a zip of it) that --cite reads")
        q.add_argument("--command", metavar="CMD", help="evidence from a command you ran…")
        q.add_argument("--excerpt", metavar="TEXT", help="…and the relevant part of its output ('@file' or '-' for stdin)")
        q.add_argument("--absence", metavar="WHAT", help="evidence that something is missing: what you looked for…")
        q.add_argument("--method", metavar="HOW", help="…and how you searched")
        q.add_argument("--note", help="note on each evidence item added by this command")

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

    q = rsub.add_parser("cite", help="print an evidence object for FILE:LINES with the exact quote")
    q.add_argument("spec", metavar="FILE:LINES")
    q.add_argument("--repo", required=True, metavar="DIR_OR_ZIP")
    q.add_argument("--note")
    q.add_argument("--compact", action="store_true", help="one line")
    q.set_defaults(fn=cmd_report_cite)

    q = rsub.add_parser("finding", help="add or update a finding")
    fsub = q.add_subparsers(dest="finding_cmd", required=True, metavar="add|update")
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
    q = fsub.add_parser("answer", help="answer a dispute on a finding: uphold it, or withdraw the finding")
    report_arg(q)
    q.add_argument("id")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--uphold", action="store_true", help="the finding stands")
    g.add_argument("--withdraw", action="store_true", help="the finding was wrong: status withdrawn, and it counts nowhere")
    q.add_argument("--note", required=True, help="why, for the person who disputed it")
    q.set_defaults(fn=cmd_finding_answer)

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

    q = rsub.add_parser("strength", help="add a strength (positive evidence) to a benchmark")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--text", required=True, help="what is good")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_strength)

    q = rsub.add_parser("enforcement", help="add evidence that a benchmark's quality is enforced (CI, lint rule, test)")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_enforcement)

    q = rsub.add_parser("action", help="add a step on a benchmark's path to its target")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--action", required=True, help="what to do")
    q.add_argument("--resolves", nargs="*", default=[], metavar="ID", help="finding or gap IDs it resolves")
    q.add_argument("--new-score", type=int, required=True, choices=range(1, 11), metavar="1-10", help="expected score afterwards")
    q.add_argument("--effort", required=True, choices=["S", "M", "L"])
    q.add_argument("--decision", metavar="QUESTION", help="a yes/no question a person must answer first")
    q.add_argument("--optional", action="store_true", help="beyond the target; only done when asked")
    q.set_defaults(fn=cmd_report_action)

    q = rsub.add_parser("gap", help="add a gap (something the code should do but doesn't)")
    report_arg(q)
    q.add_argument("--gap", required=True)
    q.add_argument("--severity", required=True, choices=SEVERITIES[::-1])
    q.add_argument("--necessity", required=True, choices=["must-have", "nice-to-have"])
    q.add_argument("--status", default="new", choices=GAP_STATUSES)
    q.add_argument("--rationale")
    q.add_argument("--benchmarks", nargs="+", required=True, metavar="ID")
    q.set_defaults(fn=cmd_report_gap)

    q = rsub.add_parser("feature", help="add a feature to the inventory (the same name again updates it: status, source, evidence)")
    report_arg(q)
    q.add_argument("--feature", required=True)
    q.add_argument("--source", required=True, help="where it's claimed, e.g. README")
    q.add_argument("--status", required=True, choices=["complete", "partial", "stub", "broken", "undocumented"])
    evidence_args(q)
    q.set_defaults(fn=cmd_report_feature)

    q = rsub.add_parser("flag", help="record an integrity flag: repo text that tries to influence grading")
    report_arg(q)
    q.add_argument("--description", required=True)
    evidence_args(q)
    q.set_defaults(fn=cmd_report_flag)

    q = rsub.add_parser("ran", help="record a command you ran")
    report_arg(q)
    q.add_argument("--command", "--command-text", dest="command_text", required=True, metavar="CMD",
                   help="exactly what you ran, so others (and `guard snapshot --from-report`) can run it again; notes go in --summary")
    q.add_argument("--exit-code", type=int)
    q.add_argument("--summary", required=True)
    q.set_defaults(fn=cmd_report_ran)

    q = rsub.add_parser("set", help=f"set a field: {', '.join(SETTABLE)} (dotted keys, e.g. metrics.line_coverage_pct)")
    report_arg(q)
    q.add_argument("key")
    q.add_argument("value", help="JSON (a number, true, an object…) or plain text")
    q.add_argument("--append", action="store_true", help="append to a list")
    q.set_defaults(fn=cmd_report_set)

    q = rsub.add_parser("check", help="what's missing or wrong; with --write, store the rollup when it's complete")
    report_arg(q)
    q.add_argument("--repo", metavar="DIR_OR_ZIP", help="also verify every citation against the code")
    q.add_argument("--tolerance", type=int, default=2)
    q.add_argument("--write", action="store_true", help="store the rollup and the finish time")
    q.set_defaults(fn=cmd_report_check)

    q = rsub.add_parser("match", help="suggest which earlier finding each newly written finding is, to keep its ID")
    report_arg(q)
    q.add_argument("--baseline", required=True, help="the previous report")
    q.add_argument("--threshold", type=float, default=0.35, help="lowest similarity to suggest (0–1)")
    q.add_argument("--apply", action="store_true", help="rename unambiguous matches to their earlier IDs")
    q.add_argument("--apply-at", type=float, default=0.6, help="lowest similarity --apply acts on")
    q.set_defaults(fn=cmd_report_match)

    # ------------------------------------------------------------ carry
    p = sub.add_parser("carry", help="start the next report from the last one, with citations moved to the new code")
    p.add_argument("baseline", help="the last report (the full one, not the public copy, if it withholds findings)")
    p.add_argument("--repo", required=True, metavar="DIR_OR_ZIP", help="the code at the new commit")
    p.add_argument("--commit", required=True, help="the new commit")
    p.add_argument("--mode", choices=["pr", "full"], default="pr")
    p.add_argument("--base-commit", help="pr mode: the pull request's base commit")
    p.add_argument("--changed", nargs="+", metavar="FILE", help="files the change touched (default: from git, if --repo is a checkout)")
    p.add_argument("--touched", nargs="+", metavar="ID", help="more benchmarks to re-grade, on top of those suggested from the changed files")
    p.add_argument("--out", metavar="FILE", help="where to write (required in pr mode; full mode defaults to a new report folder)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-withheld", action="store_true", help="carry from a public copy anyway")
    p.add_argument("--grader", help="the agent or person grading now (default: the baseline's)")
    provenance(p)
    with_config(p)
    p.set_defaults(fn=cmd_carry)

    # ------------------------------------------------------------ doctor
    p = sub.add_parser("doctor", help="preflight: check Python, the kit, the config, the code and delivery access before a run")
    p.add_argument("--repo", metavar="DIR_OR_ZIP", help="the code to grade")
    p.add_argument("--delivery", choices=["pr", "save", "return"], help="also check what this delivery needs (pr: git, identity, push)")
    p.add_argument("--open", choices=["github", "gitlab"], help="pr: also check gh / glab sign-in")
    p.add_argument("--remote", default="origin")
    p.add_argument("--site", metavar="URL", help="the suite website: check it's reachable and serves this kit's version")
    with_config(p)
    p.set_defaults(fn=cmd_doctor)

    # ------------------------------------------------------------ deliver
    p = sub.add_parser("migrate", help="move a project to this suite version in one pull request: the pin, and its reports with --reports",
                       description="A dry run unless --write (here, never on the default branch) or --run (a new branch, committed). "
                                   "Scores and rollups never change; `gradekit ci` checks a migration by redoing it. Revert the pull request to undo.")
    with_config(p)
    p.add_argument("--reports", action="store_true", help="also upgrade the project's 4.x reports to format 5 (and re-render report.md)")
    p.add_argument("--write", action="store_true", help="write the files into this checkout (not on the default branch)")
    p.add_argument("--run", action="store_true", help="create a branch from the default branch, write the files and commit")
    p.add_argument("--push", action="store_true", help="with --run: push the branch")
    p.add_argument("--open", choices=["github", "gitlab"], help="with --push: open the pull request with gh or glab")
    p.add_argument("--branch", help="default: migrate/<project>-v<major>")
    p.add_argument("--base", metavar="BRANCH", help="branch to start from (default: the remote's default branch)")
    p.add_argument("--remote", default="origin")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("deliver", help="hand back a finished report: pr, save or return (prints the git steps, or runs them)",
                       description="Checks the report is finished, withholds sensitive findings if the grading repo is public, "
                                   "renders report.md, then delivers. For pr it prints the branch, commit, title and body "
                                   "(or does the git steps with --run); pushing and opening the pull request are opt-in.")
    p.add_argument("report", help="the finished report.json, in projects/NAME/reports/<folder>/")
    p.add_argument("--delivery", choices=["pr", "save", "return"], default="pr")
    p.add_argument("--repo", metavar="DIR_OR_ZIP", help="also verify every citation against the code first")
    p.add_argument("--run", action="store_true", help="pr: create the branch and commit (otherwise just print the steps)")
    p.add_argument("--push", action="store_true", help="pr, with --run: push the branch")
    p.add_argument("--open", choices=["github", "gitlab"], help="pr, with --push: open it with gh or glab (needs them installed and signed in)")
    p.add_argument("--base", metavar="BRANCH", help="pr: branch to start from and target (default: the remote's default branch)")
    p.add_argument("--remote", default="origin")
    p.add_argument("--branch", help="default: report/<project>/<date>-<commit>")
    p.add_argument("--body-file", metavar="FILE", help="where to write the pull request body (default: a temp file)")
    p.add_argument("--site", metavar="URL", help="the suite website, for a Review-page link in the body")
    p.add_argument("--grading-repo-url", metavar="URL", help="the grading repo's address, for that link")
    with_config(p)
    p.set_defaults(fn=cmd_deliver)

    # ------------------------------------------------------------ ci
    p = sub.add_parser("ci", help="grading repos: check a pull request (one report, or settings), write a comment and labels",
                       description="Run in a grading repo's CI on a pull request. Templates for GitHub Actions and GitLab CI "
                                   "are in the kit's ci/ folder (`gradekit init --ci github|gitlab` adds one).")
    p.add_argument("--base", required=True, help="the target branch, e.g. origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--grading-repo", metavar="DIR", help="the grading repo checkout (default: current folder)")
    p.add_argument("--changed", nargs="+", metavar="[A|M|D:]PATH", help="the changed files, if git can't list them")
    p.add_argument("--site", metavar="URL", help="the suite website, for a Review-page link")
    p.add_argument("--grading-repo-url", metavar="URL", help="this repo's address, for that link")
    p.add_argument("--branch", help="the pull request's branch, for that link")
    p.add_argument("--comment-file", metavar="FILE", help="write the summary comment (markdown) here")
    p.add_argument("--labels-file", metavar="FILE", help="write the labels to set, one per line, here")
    p.set_defaults(fn=cmd_ci)

    # ------------------------------------------------------------ index
    p = sub.add_parser("index", help="grading repos: write projects/index.json (latest scores, history, decisions waiting)")
    p.add_argument("--grading-repo", metavar="DIR", help="grading repo root (default: current folder)")
    p.add_argument("--out", metavar="FILE", help="default: projects/index.json")
    p.add_argument("--check", action="store_true", help="don't write; exit 1 if the file is missing or out of date")
    p.set_defaults(fn=cmd_index)

    # ------------------------------------------------------------ glossary
    p = sub.add_parser("calibration", help="the calibration program: golden repos, repeated runs, published results")
    csub = p.add_subparsers(dest="calibration_cmd", required=True, metavar="STEP")
    q = csub.add_parser("add-run", help="save a grader's scores for a golden repo as runs/run-N.json")
    q.add_argument("golden", help="the golden repo's folder, e.g. calibration/golden/schedule")
    q.add_argument("report", help="the grader's report.json for the golden commit")
    q.add_argument("--note", help="e.g. which model or session, anything unusual")
    q.set_defaults(fn=cmd_calibration_add_run)
    q = csub.add_parser("run", help="score every run against its golden repo; write results.json and RESULTS.md")
    q.add_argument("--golden-dir", default=str(GOLDEN_DIR))
    q.add_argument("--min-runs", type=int, default=3, help="independent runs each golden repo needs (default 3)")
    q.add_argument("--out", default=str(CALIBRATION_RESULTS))
    q.add_argument("--markdown", default=str(CALIBRATION_MD))
    q.add_argument("--check", action="store_true", help="only check the written results are up to date (exit 1 if not)")
    q.set_defaults(fn=cmd_calibration_run)

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

    p = sub.add_parser("mcp", help="run as an MCP server on stdin/stdout: every command becomes a tool, for agents without a shell")
    p.add_argument("--list", action="store_true", help="print the tools it offers, and exit")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("rubric", help="the rubric for one benchmark or pillar (e.g. A3, or B), as text or --json")
    p.add_argument("ids", nargs="*", metavar="ID", help="benchmarks (A3) or pillars (B); none: all")
    p.add_argument("--out", metavar="FILE", help="write the whole rubric as JSON (rubric/rubric.json)")
    p.set_defaults(fn=cmd_rubric)

    p = sub.add_parser("glossary", help="the suite's terms and what they mean (one, or all)")
    p.add_argument("term", nargs="*", help="a term to look up, e.g. gate or effective severity")
    p.add_argument("--markdown", action="store_true", help="the whole glossary as GLOSSARY.md")
    p.add_argument("--out", metavar="FILE", help="with --markdown: write it here")
    p.set_defaults(fn=cmd_glossary)

    # ------------------------------------------------------------ render
    p = sub.add_parser("render", help="markdown from report data: report.md, PR title/body, PR-check comment, improvement log")
    rsub = p.add_subparsers(dest="render_cmd", required=True, metavar="WHAT")

    def render_dest(q, default_note):
        q.add_argument("--out", metavar="FILE", help=f"where to write ('-' for stdout; default: {default_note})")
        q.add_argument("--stdout", action="store_true", help="print instead of writing the default file")

    q = rsub.add_parser("report", help="report.md from report.json (sensitive findings withheld in public grading repos)")
    q.add_argument("report")
    render_dest(q, "beside the report, e.g. report.md")
    with_config(q)
    q.set_defaults(fn=cmd_render_report)

    q = rsub.add_parser("pr", help="the grading pull request: branch, title and body (title on the first line)")
    q.add_argument("report")
    q.add_argument("--site", metavar="URL", help="the suite website, for a link to its Review page")
    q.add_argument("--grading-repo-url", metavar="URL", help="the grading repo (e.g. https://github.com/acme/grading), for that link")
    q.add_argument("--branch", help="default: report/<project>/<date>-<commit>")
    with_config(q)
    q.set_defaults(fn=cmd_render_pr)

    q = rsub.add_parser("check", help="the PR-check comment, comparing the baseline report with the PR report")
    q.add_argument("old", help="baseline report (newest merged report)")
    q.add_argument("new", help="the PR report (mode pr)")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_check)

    q = rsub.add_parser("log", help="the improver's log, from a small JSON file (see prompts/improver.md)")
    q.add_argument("log", help="improve-log.json")
    q.add_argument("--report", help="the report worked from: adds pending decisions as blocked and declined ones as skipped")
    q.add_argument("--guard", metavar="FILE", help="the `guard compare` result: adds the before → after table of the code's checks")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_log)

    # ------------------------------------------------------------ guard
    p = sub.add_parser("guard", help="improvers: run the code's checks before changing it, then prove nothing got worse")
    gsub = p.add_subparsers(dest="guard_cmd", required=True, metavar="STEP")
    q = gsub.add_parser("snapshot", help="before any change: run the checks and record the results (in .git/, never committed)")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--check", action="append", metavar="NAME=COMMAND",
                   help='a check to run, e.g. tests="pytest -q" (repeatable; run from the code folder, or --path)')
    q.add_argument("--from-report", metavar="REPORT", help="also use the tests, lint, type-check, coverage, build and audit commands the grader ran")
    q.add_argument("--path", metavar="SUBDIR", help="only this part of the code (the project's `path`): checks run there, and only it is scanned")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write it (default: .git/gradekit/guard-before.json)")
    q.add_argument("--list", action="store_true", help="show the checks it would run, and run nothing")
    q.set_defaults(fn=cmd_guard_snapshot)
    q = gsub.add_parser("compare", help="after changing: run the same checks again; exit 2 if anything got worse")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--before", metavar="FILE", help="the snapshot (default: .git/gradekit/guard-before.json)")
    q.add_argument("--after", metavar="FILE", help="compare with this snapshot instead of running the checks now")
    q.add_argument("--explain", action="append", metavar="KEY=REASON",
                   help='a deliberate change, e.g. tests.passed="removed the tests of the deleted export helper" (repeatable)')
    q.add_argument("--coverage-tolerance", type=float, default=0.1, metavar="POINTS", help="coverage may move this much (default 0.1)")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write the result (default: .git/gradekit/guard-compare.json)")
    q.set_defaults(fn=cmd_guard_compare)

    for leaf in leaf_parsers(ap):
        leaf.add_argument("--json", action="store_true",
                          help="print one JSON object instead: {ok, exit_code, command, result, text}")

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "json", False):
        return run_command(ap, args)
    buf = io.StringIO()
    error = None
    with contextlib.redirect_stdout(buf):
        try:
            rc = run_command(ap, args, raise_errors=True)
        except GradekitError as e:
            rc, error = 1, str(e)
    out = {"ok": rc == 0, "exit_code": rc, "command": command_name(args), "result": getattr(args, "_result", None),
           "text": buf.getvalue()}
    if error:
        out["error"] = error
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return rc


def command_name(args) -> str:
    return " ".join(x for x in (args.cmd, getattr(args, "report_cmd", None), getattr(args, "finding_cmd", None),
                                 getattr(args, "render_cmd", None), getattr(args, "guard_cmd", None),
                                 getattr(args, "order_cmd", None), getattr(args, "dispute_cmd", None),
                                 getattr(args, "calibration_cmd", None)) if x)


def run_command(ap, args, raise_errors: bool = False) -> int:
    if args.cmd in ("validate", "rollup", "verify-evidence", "redact") and args.report is None:
        pdir = project_dir_from_args(args)
        found = report_folders(pdir) if pdir else []
        if not found:
            ap.error("give a report file, or --project NAME with at least one report in projects/NAME/reports/")
        args.report = str(found[-1] / "report.json")
        print(f"note: using {args.report}")
    if args.cmd == "diff" and (args.old is None or args.new is None):
        pdir = project_dir_from_args(args)
        found = report_folders(pdir) if pdir else []
        if args.new is None and args.old is None:
            if len(found) < 2:
                ap.error("give two reports, or --project NAME with at least two reports")
            args.old, args.new = str(found[-2] / "report.json"), str(found[-1] / "report.json")
        elif args.new is None:
            if not found:
                ap.error("give the new report too, or --project NAME")
            args.new = str(found[-1] / "report.json")
        print(f"note: comparing {args.old} → {args.new}")
    try:
        return args.fn(args)
    except GradekitError as e:
        if raise_errors:
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


EXIT_USAGE = 64   # bad arguments (BSD sysexits EX_USAGE), so it never looks like diff's "regression" (2)


class CliParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def leaf_parsers(parser):
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield parser
    for a in subs:
        for sp in dict.fromkeys(a.choices.values()):
            yield from leaf_parsers(sp)


if __name__ == "__main__":
    try:  # behave like a normal CLI when piped into `head` etc. (only as a script: never change a host process)
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
