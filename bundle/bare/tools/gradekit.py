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

Defaults: commands look for .grading/project.toml and .grading/report.json in the current
folder, so inside a repo set up with `init --grading-dir .grading` you can usually omit them.
--config (repeatable) takes TOML files layered over config/defaults.toml in order, or one
effective-config JSON produced by `resolve --out`.

The website runs this same file in the browser (Pyodide) through web_api().

Python 3.11+ (uses tomllib); standard library only. Uses `jsonschema` when installed.
Exit codes: 0 ok, 1 invalid/failed check, 2 regression (diff --fail-on-regression),
3 unstable runs (stability --strict), 4 calibration failed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import statistics
import sys
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
SCHEMA_PATH = SUITE_DIR / "schema" / "report.schema.json"
GRADING_DIR = Path(".grading")
DEFAULT_PROJECT = GRADING_DIR / "project.toml"
DEFAULT_REPORT = GRADING_DIR / "report.json"
PILLARS = ["A", "B", "C", "D", "E", "F", "X"]
OPEN_STATUSES = {"new", "open", "regressed"}
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


HASHED_KEYS = ("suite_version", "preset", "answers", "weights", "gates", "zones", "targets", "maturity", "priorities")


def config_hash(cfg: dict) -> str:
    """Fingerprint of everything that affects scoring. Project prose, dispositions and
    decisions are deliberately excluded: they change between cycles without re-weighting."""
    body = {k: cfg.get(k) for k in HASHED_KEYS}
    body["out_of_scope"] = (cfg.get("project") or {}).get("out_of_scope", [])
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def resolve_config(paths: list[str], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True) -> dict:
    return resolve_layers([(str(p), load_toml(p)) for p in paths], component, preset_fallback, component_required)


def resolve_layers(layers: list[tuple[str, dict]], component: str | None = None, preset_fallback: str | None = None,
                   component_required: bool = True) -> dict:
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

    if major(merged.get("suite_version", "0")) != major(catalog["suite_version"]):
        errors.append(f"config suite_version {merged.get('suite_version')} does not match suite {catalog['suite_version']}")

    project = merged.get("project", {}) or {}
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

    dispositions = list(merged.get("dispositions", []) or [])
    for i, d in enumerate(dispositions, 1):
        if not (d.get("finding_id") or d.get("match")):
            errors.append(f"dispositions #{i}: needs finding_id or match")
        if not str(d.get("reason", "")).strip():
            errors.append(f"dispositions #{i}: needs a reason")
    decisions = list(merged.get("decisions", []) or [])
    for i, d in enumerate(decisions, 1):
        if not d.get("action_id"):
            errors.append(f"decisions #{i}: needs action_id")
        if not isinstance(d.get("approved"), bool):
            errors.append(f"decisions #{i} ({d.get('action_id')}): approved must be true or false")
    review = {"allow_agent_decisions": False, **(merged.get("review", {}) or {})}

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
        "warnings": warnings,
    }
    cfg["hash"] = config_hash(cfg)
    return cfg


def load_config(args, report: dict | None = None, quiet: bool = False) -> dict:
    paths = getattr(args, "config", None) or []
    comp = getattr(args, "component", None)
    required = comp is not None
    if report and not comp:
        comp = (report.get("component") or {}).get("name")
        if comp == "repo":
            comp = None
    if len(paths) == 1 and paths[0].endswith(".json"):
        cfg = load_json(paths[0])
        if cfg.get("hash") != config_hash(cfg):
            die(f"{paths[0]} has been edited after it was generated (hash mismatch); re-run resolve")
        return cfg
    if any(p.endswith(".json") for p in paths):
        die("--config takes either TOML files or a single effective-config JSON, not both")
    fallback = ((report or {}).get("config") or {}).get("preset")
    if not paths and DEFAULT_PROJECT.exists():
        paths = [str(DEFAULT_PROJECT)]
        if not quiet:
            print(f"note: using {DEFAULT_PROJECT} (pass --config to use another)")
    elif not paths and not quiet:
        print(f"note: no --config given and no {DEFAULT_PROJECT}; using suite defaults with preset '{fallback or 'default'}'")
    return resolve_config(paths, component=comp, preset_fallback=fallback, component_required=required)


# =========================================================================== zones & severity

def glob_to_regex(pattern: str) -> re.Pattern:
    p = pattern.strip().lstrip("./")
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
    path = str(path).lstrip("./")
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

        validator = jsonschema.Draft202012Validator(load_json(SCHEMA_PATH))
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

    if major(report.get("suite_version", "0")) != major(catalog["suite_version"]):
        errors.append(f"suite_version {report.get('suite_version')} does not match suite {catalog['suite_version']}")
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
                warnings.append(f"finding {fid} is 'accepted' but no [[dispositions]] entry in the project config covers it")
        if f.get("disposition") and f.get("status") != "accepted":
            warnings.append(f"finding {fid}: has a disposition but status is '{f.get('status')}'")
    fz = analyze_findings(report, cfg)

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
            crit_open = [fid for fid in b.get("finding_ids", [])
                         if fz.get(fid, {}).get("effective_severity") == "critical" and fz.get(fid, {}).get("status") in OPEN_STATUSES]
            if crit_open and score > 5:
                warnings.append(f"{bid}: score {score} despite open effective-critical finding(s) {', '.join(crit_open)}")
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
    return errors, warnings


def cmd_validate(args) -> int:
    catalog = load_catalog()
    report = load_json(args.report)
    cfg = load_config(args, report)
    errors, warnings = validate_report(report, cfg, catalog)
    for w in cfg.get("warnings", []) + warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
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
        key = rel.lstrip("./")
        if key not in index:
            return f"file not found in archive: {rel}"
        return zf.read(index[key]).decode("utf-8", errors="replace").splitlines()
    return read


def verify_evidence(report: dict, read_lines, tolerance: int = 2) -> dict:
    carried = {b["id"] for b in report.get("benchmarks", []) if b.get("carried_forward")}
    checked = skipped = 0
    failures: list[str] = []
    other = {"command": 0, "absence": 0}
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
            "command": other.get("command", 0), "absence": other.get("absence", 0)}


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
          f"absence: {res['absence']} (not machine-checkable)")
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
        return {"status": "pending", "note": f"answered by {by}, but agent decisions are not allowed ([review] allow_agent_decisions)"}
    return {"status": "approved" if match.get("approved") else "declined", "answer": match.get("answer"),
            "decided_by": by, "date": match.get("date")}


def apply_rollup(report: dict, cfg: dict) -> dict:
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
    if args.write or args.out:
        out = args.out or args.report
        write_json(out, report)
        print(f"\nwrote rollup to {out}")
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
    return 3 if (args.strict and res["unstable"]) else 0


# =========================================================================== diff

def compute_diff(old: dict, new: dict, cfg_old: dict, cfg_new: dict) -> dict:
    regressions, notes = [], []
    same_major = major(old.get("suite_version", "0")) == major(new.get("suite_version", "0"))
    oh, nh = (old.get("config") or {}).get("hash"), (new.get("config") or {}).get("hash")
    if oh != nh:
        notes.append(f"reports used different configs ({oh} → {nh}); weights may differ, so overall and maturity "
                     "changes can come from re-weighting, not code changes")
    r_old, r_new = compute_rollup(old, cfg_old), compute_rollup(new, cfg_new)
    if not same_major:
        notes.append("suite major versions differ; score deltas are not comparable and are not used for regressions")
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
    new_ids = [brief(i) for i, f in nf.items() if i not in of or f.get("status") == "new"]
    fixed = [brief(i) for i, f in nf.items() if f.get("status") == "fixed" and of.get(i, {}).get("status") != "fixed"]
    regressed = [brief(i) for i, f in nf.items() if f.get("status") == "regressed"]
    for f in new_ids:
        if f["effective_severity"] in ("critical", "major"):
            regressions.append(f"new {f['effective_severity']} finding {f['id']} ({f['zone']} zone): {f['title']}")
    for f in regressed:
        regressions.append(f"finding regressed {f['id']}: {f['title']}")
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
    return 0 if ok else 4


def strip_private(obj):
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("private_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


def cmd_redact(args) -> int:
    shared = strip_private(copy.deepcopy(load_json(args.report)))
    if "holdout" in shared:
        shared["holdout"]["private_details"] = "[redacted]"
    out = args.out or re.sub(r"\.json$", "", args.report) + ".shared.json"
    write_json(out, shared)
    print(f"wrote redacted report to {out}")
    return 0


def cmd_rollup_repo(args) -> int:
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
    if args.out:
        write_json(args.out, {"computed_by": "gradekit.py rollup-repo", "overall_score": overall,
                              "maturity": lowest["level"], "limited_by": lowest["component"], "components": rows})
        print(f"wrote {args.out}")
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
# Humans own this file. Agents may read it but must never change it.
# Check it with:  python3 SUITE_DIR/tools/gradekit.py resolve --config {path}
# Or use the "Set up a project" page on the suite's website.
"""


def render_project_toml(data: dict, defaults: dict | None = None, path: str = "project.toml") -> str:
    """Write a project config in the suite's standard layout, with helpful comments."""
    defaults = defaults or load_toml(DEFAULTS_PATH)
    d = copy.deepcopy(data or {})
    out = [PROJECT_HEADER.format(version=defaults.get("suite_version"), path=path)]

    proj = d.pop("project", {}) or {}
    hints = {"preset": " | ".join(defaults.get("presets", {})),
             "maturity_target": "prototype | internal tool | production | public open source",
             "out_of_scope": "paths the grader skips, e.g. \"vendor/**\""}
    order = ["name", "description", "preset", "languages", "users", "maturity_target", "scope", "out_of_scope"]
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
    out.append("# Criticality zones: the first match wins, so list specific zones first.")
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

    for comp in d.pop("components", []) or []:
        _emit_table("components", comp, out, array=True)

    disp = d.pop("dispositions", []) or []
    out.append("# Accepted findings: the grader marks these 'accepted' and they stop lowering scores.")
    if disp:
        out.append("")
        for x in disp:
            _emit_table("dispositions", x, out, array=True)
    else:
        out += ["# [[dispositions]]", '# finding_id = "B5-001"', '# decision   = "won\'t fix"',
                '# reason     = "Single payment provider is a deliberate constraint through 2027"',
                '# decided_by = "jane@example.com"', '# date       = "2026-11-07"', ""]

    dec = d.pop("decisions", []) or []
    out.append("# Answers to decision questions from grading reports (append new ones at the end).")
    if dec:
        out.append("")
        for x in dec:
            _emit_table("decisions", x, out, array=True)
    else:
        out += ["# [[decisions]]", '# action_id  = "D1-act-1"', '# question   = "Implement CSV export, or drop the claim from the README?"',
                "# approved   = true", '# answer     = "Implement CSV only"', '# decided_by = "jane@example.com"',
                '# date       = "2026-11-07"', ""]

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


def render_decisions_toml(decisions: list[dict]) -> str:
    out: list[str] = []
    for d in decisions:
        _emit_table("decisions", {k: d.get(k) for k in ("action_id", "question", "approved", "answer", "decided_by", "date")
                                  if d.get(k) is not None}, out, array=True)
    return "\n".join(out).rstrip() + "\n"


GRADING_README = """# .grading/

This folder holds the Code Grading Suite setup and the latest grading report for this repository.
It is part of the grading process, not part of the code being graded.

| File | Written by | What it is |
|---|---|---|
| `project.toml` | Humans | Grading settings, accepted findings and answers to decision questions |
| `report.json`, `report.md` | Grader agents | The latest grading report (older ones are in git history) |

Improving agents and contributors: read these files, but don't change them in your pull requests.
Changes here belong in grading-report PRs (report files) or human decisions (`project.toml`).
"""

CODEOWNERS_HINT = "/.grading/  @your-team-or-username"


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
    answers = {q: given.get(q, preset_answers.get(q, qd.get("default"))) for q, qd in defaults["questions"].items()}
    data = {"project": {"name": args.name, "description": "<what it is, in one sentence>", "preset": args.preset,
                        "languages": "<e.g. Python 3.12, FastAPI, Postgres>", "users": "<who uses it>",
                        "maturity_target": "<choose one>",
                        "scope": "<stated scope or link to requirements>", "out_of_scope": []},
            "answers": answers}
    if args.grading_dir:
        gdir = Path(args.grading_dir)
        out = gdir / "project.toml"
    else:
        gdir, out = None, Path(args.out)
    if out.exists() and not args.force:
        die(f"{out} exists (use --force to overwrite)")
    text = render_project_toml(data, defaults, path=str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    if gdir is not None:
        readme = gdir / "README.md"
        if not readme.exists():
            readme.write_text(GRADING_README, encoding="utf-8")
            print(f"wrote {readme}")
        print(f"tip: protect the folder with a CODEOWNERS line:  {CODEOWNERS_HINT}")
    print(f"next: edit {out}, then run: gradekit resolve --config {out}")
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
    cfg = resolve_layers(layers, component=comp, preset_fallback=fallback, component_required=False)
    source = " + ".join(n for n, _ in layers) if layers else f"suite defaults (preset '{cfg['preset']}' from the report)"
    return cfg, source


def _api_info(p):
    merged = load_toml(DEFAULTS_PATH)
    for _, layer in _web_layers({"org_toml": p.get("org_toml")}):
        merged = deep_merge(merged, layer)
    return {"suite_version": merged.get("suite_version"), "catalog": load_catalog(),
            "questions": merged.get("questions", {}), "presets": merged.get("presets", {}),
            "base_weights": merged.get("weights", {}).get("base", {}), "gates": merged.get("gates", {}),
            "zone_settings": merged.get("zone_settings", {}), "targets": merged.get("targets", {}),
            "maturity": merged.get("maturity", {}), "review": merged.get("review", {}),
            "grading_readme": GRADING_README, "codeowners_hint": CODEOWNERS_HINT}


def _api_build(p):
    defaults = load_toml(DEFAULTS_PATH)
    text = render_project_toml(p.get("project") or {}, defaults, path=p.get("path") or ".grading/project.toml")
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
    roll = compute_rollup(report, cfg)
    rc = report.get("config") or {}
    return {"validation": {"errors": errors, "warnings": cfg.get("warnings", []) + warnings},
            "rollup": roll, "config_source": source, "config_hash_match": rc.get("hash") == cfg["hash"],
            "config": {k: cfg.get(k) for k in ("hash", "preset", "answers", "gates", "project", "review", "zones")},
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
    shared = strip_private(copy.deepcopy(p["report"]))
    if "holdout" in shared:
        shared["holdout"]["private_details"] = "[redacted]"
    return {"report": shared}


def _api_decisions_toml(p):
    block = render_decisions_toml(p.get("decisions", []))
    out = {"toml": block}
    if p.get("project_toml"):
        updated = p["project_toml"].rstrip() + "\n\n" + block
        parse_toml(updated, "updated project.toml")
        out["updated_project_toml"] = updated
    return out


WEB_API = {"info": _api_info, "build": _api_build, "parse": _api_parse, "zone_test": _api_zone_test,
           "check": _api_check, "consensus": _api_consensus, "compare": _api_compare,
           "verify_zip": _api_verify_zip, "redact": _api_redact, "decisions_toml": _api_decisions_toml}


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

def main(argv=None) -> int:
    try:  # behave like a normal CLI when piped into `head` etc.
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="gradekit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_config(p):
        p.add_argument("--config", action="append", metavar="FILE",
                       help="config TOML (repeatable, layered in order over defaults) or one effective-config JSON")
        p.add_argument("--component", help="monorepo component name from the project config")

    p = sub.add_parser("init", help="write a starter project.toml")
    p.add_argument("--preset", default="default")
    p.add_argument("--name", default="my-project")
    p.add_argument("--answer", action="append", metavar="Q=A", help="e.g. --answer data_sensitivity=financial")
    p.add_argument("--out", default="project.toml")
    p.add_argument("--grading-dir", metavar="DIR", help="write DIR/project.toml and DIR/README.md instead (e.g. .grading)")
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
    p.add_argument("report", nargs="?", help=f"report JSON (default: {DEFAULT_REPORT})")
    with_config(p)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("verify-evidence", help="check code citations against the repo")
    p.add_argument("report", nargs="?", help=f"report JSON (default: {DEFAULT_REPORT})")
    p.add_argument("--repo", default=".", help="repo folder, or a .zip of it (default: current folder)")
    p.add_argument("--tolerance", type=int, default=2, help="line drift allowed around the cited range (default 2)")
    p.set_defaults(fn=cmd_verify_evidence)

    p = sub.add_parser("rollup", help="compute gates, zones, scores, targets, maturity and priorities")
    p.add_argument("report", nargs="?", help=f"report JSON (default: {DEFAULT_REPORT})")
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

    p = sub.add_parser("diff", help="compare two reports")
    p.add_argument("old")
    p.add_argument("new")
    with_config(p)
    p.add_argument("--old-config", action="append", metavar="FILE", help="config the old report was graded with, if different")
    p.add_argument("--fail-on-regression", action="store_true")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("calibrate", help="compare a report with expected scores")
    p.add_argument("report")
    p.add_argument("expected")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("redact", help="strip hidden-check details for sharing")
    p.add_argument("report", nargs="?", help=f"report JSON (default: {DEFAULT_REPORT})")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_redact)

    p = sub.add_parser("rollup-repo", help="combine per-component reports (each must already have a rollup)")
    p.add_argument("reports", nargs="+")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_rollup_repo)

    args = ap.parse_args(argv)
    if hasattr(args, "report") and args.report is None:
        if not DEFAULT_REPORT.exists():
            ap.error(f"give a report file (no {DEFAULT_REPORT} here)")
        args.report = str(DEFAULT_REPORT)
    try:
        return args.fn(args)
    except GradekitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
