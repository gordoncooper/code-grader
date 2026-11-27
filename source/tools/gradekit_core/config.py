"""Configuration: config/defaults.toml and a project's layers resolved into the effective config; project folders."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .common import (
    DECISIONS_FILE, DEFAULTS_PATH, die, DISPOSITIONS_FILE, HEAT, load_catalog, load_json, load_toml, major,
    PROJECT_FILE, SEVERITIES, SUITE_DIR,
)


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

# [schedule] in project.toml: when the scheduled job (`gradekit due --write-orders`) asks for a grade. Never changes scores.
SCHEDULE_DEFAULTS = {"grade_every_days": 0, "only_if_code_changed": True}
HASHED_KEYS = ("suite_version", "preset", "answers", "weights", "gates", "zones", "targets", "maturity", "priorities")


def config_hash(cfg: dict) -> str:
    """Fingerprint of everything that affects scoring. Project prose, dispositions and
    decisions are deliberately excluded: they change between cycles without re-weighting."""
    body = {k: cfg.get(k) for k in HASHED_KEYS}
    body["out_of_scope"] = (cfg.get("project") or {}).get("out_of_scope", [])
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def resolve_config(paths: list[str], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True, decisions: list | None = None, dispositions: list | None = None,
) -> dict:
    return resolve_layers([(str(p), load_toml(p)) for p in paths], component, preset_fallback, component_required,
                          decisions, dispositions)


def resolve_layers(layers: list[tuple[str, dict]], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True, decisions: list | None = None, dispositions: list | None = None) -> dict:
    catalog = load_catalog()
    ids = [b["id"] for b in catalog["benchmarks"]]
    names = {b["id"]: b["name"] for b in catalog["benchmarks"]}
    rules = DEFAULTS_PATH
    merged = load_toml(rules)
    sources = [str(rules.relative_to(SUITE_DIR))]
    for name, data in layers:
        merged = deep_merge(merged, data)
        sources.append(name)
    errors: list[str] = []
    warnings: list[str] = []

    scoring = load_toml(rules).get("suite_version", "0")
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
    moved = [k for k in ("severity_shift", "never_downgrade") if k in zs]
    if moved:
        warnings.append(f"zone_settings.{' and '.join(moved)} no longer apply: since scoring 5.0, graders judge severity where the "
                        "code runs, and hot zones raise the bar for maturity instead (remove the setting)")
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
    schedule = {**SCHEDULE_DEFAULTS, **(merged.get("schedule", {}) or {})}
    if not isinstance(schedule.get("grade_every_days"), int) or isinstance(schedule.get("grade_every_days"), bool) or schedule["grade_every_days"] < 0:
        errors.append("schedule.grade_every_days must be a whole number of days (0: no schedule)")
    if not isinstance(schedule.get("only_if_code_changed"), bool):
        errors.append("schedule.only_if_code_changed must be true or false")
    for k in sorted(set(schedule) - set(SCHEDULE_DEFAULTS)):
        errors.append(f"schedule.{k}: unknown setting (grade_every_days, only_if_code_changed)")
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
        # a monorepo's parts and their weights, as people set them (not hashed: each component's config is)
        "components": {c.get("name"): c.get("weight") or 1 for c in merged.get("components", []) or []},
        "preset": preset,
        "answers": answers,
        "weights": weights,
        "gates": {"benchmarks": sorted(gate_why), "why": gate_why,
                  "hard_floor": gcfg.get("hard_floor", 3), "overall_cap": gcfg.get("overall_cap", 4.0)},
        "zones": {"list": zones, "default": zs.get("default", "normal"),
                  "priority_multiplier": zs.get("priority_multiplier", {"hot": 2.0, "normal": 1.0, "cold": 0.5})},
        "targets": targets,
        "maturity": merged.get("maturity", {}),
        "priorities": merged.get("priorities", {}),
        "dispositions": dispositions,
        "decisions": decisions,
        "review": review,
        "publishing": publishing,
        "schedule": schedule,
        "warnings": warnings,
    }
    cfg["hash"] = config_hash(cfg)
    return cfg


def read_list_file(path: Path, key: str) -> list:
    """decisions.json / dispositions.json: {"decisions": [...]} or a bare list. Missing file = empty."""
    if not path.exists():
        return []
    data = load_json(path, want=(dict, list))
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


def component_reports(folder: Path) -> list[Path]:
    """A report folder's components/NAME.json (never the private copies)."""
    d = folder / "components"
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".private.json")) if d.is_dir() else []


def folder_reports(folder: Path) -> list[Path]:
    return [folder / "report.json", *component_reports(folder)]


def project_dir_for_report(path) -> Path | None:
    """projects/NAME/reports/<folder>/report.json (or …/<folder>/runs/run-N.json) → projects/NAME."""
    p = Path(path).resolve().parent
    for cand in (p.parent, p.parent.parent):
        if cand.name == "reports" and (cand.parent / PROJECT_FILE).exists():
            return cand.parent
    return None


def project_dir_or_die(args) -> Path:
    pdir = project_dir_from_args(args)
    if not pdir or not (pdir / PROJECT_FILE).exists():
        die("which project? --project-dir projects/NAME (or --project NAME in the grading repo's root)")
    return pdir
