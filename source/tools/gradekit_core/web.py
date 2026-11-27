"""The web API the website calls through Pyodide (`web_api`)."""
from __future__ import annotations

import re

from .common import (
    DECISIONS_FILE, DEFAULTS_PATH, die, DISPOSITIONS_FILE, GradekitError, kit_version, load_toml, parse_toml,
    PROJECT_FILE, RUBRIC, slug,
)
from .config import deep_merge, order_report_folders, parse_list_text, resolve_layers, run_date_of
from .zones import zone_for_path
from .rollup import compute_rollup
from .publishing import publish_problems, redact_report, sensitive_ids
from .validate import validate_report
from .evidence import verify_evidence, zip_reader
from .compare import compute_consensus, compute_diff
from .settings import append_entries, GRADING_REPO_README, render_project_toml, starter_json
from .rubric import load_glossary


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
    return {"suite_version": kit_version(), "scoring_version": merged.get("suite_version"), "catalog": RUBRIC.catalog,
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
    errors, warnings = validate_report(report, cfg, RUBRIC.catalog)
    notes: list[str] = []   # about this browser, not the report (none since the schema check is built in)
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


def _api_code_context(p):
    """Each cited code location with the lines around it, from a code archive: [{file, lines, start, text: [...], cited: [a, b]}]."""
    read = zip_reader(p["zip_path"])
    out, ctx = [], int(p.get("context", 3))
    for loc in p.get("locations", []):
        lines = read(loc["file"])
        if isinstance(lines, str):
            out.append({"file": loc["file"], "lines": loc.get("lines"), "error": lines})
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", str(loc.get("lines") or ""))
        if m:
            a = int(m.group(1)); b = int(m.group(2) or a)
        else:   # format 5 without line numbers: the quote is the anchor
            q = [x.strip() for x in str(loc.get("quote") or "").strip("\n").splitlines()]
            hit = next((i for i in range(len(lines)) if q and lines[i].strip() == q[0]
                        and [x.strip() for x in lines[i:i + len(q)]] == q), None)
            if hit is None:
                out.append({"file": loc["file"], "lines": None, "error": "quote not found in the archive"})
                continue
            a, b = hit + 1, hit + len(q)
        start, end = max(1, a - ctx), min(len(lines), b + ctx)
        out.append({"file": loc["file"], "lines": loc.get("lines"), "start": start, "text": lines[start - 1:end], "cited": [a, b]})
    return {"locations": out}


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
           "verify_zip": _api_verify_zip, "code_context": _api_code_context, "redact": _api_redact, "decisions_update": _api_decisions_update,
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
