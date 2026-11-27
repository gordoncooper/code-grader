"""Configuration commands (init, resolve, presets) and writing project.toml."""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

from .common import (
    DECISIONS_FILE, DEFAULTS_PATH, die, DISPOSITIONS_FILE, emit, GradekitError, kit_version, load_toml, major,
    parse_toml, PILLARS, PROJECT_FILE, RUBRIC, slug, SUITE_DIR, write_json,
)
from .config import deep_merge, load_config, resolve_config, with_config


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
    catalog = RUBRIC.catalog
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


PROJECT_HEADER = """# Code Grading Suite project configuration (created with kit v{version})
# People own this file. Agents read it but don't change it.
# Answers to decision questions go in decisions.json, accepted findings in dispositions.json.
# Check it with:  python3 SUITE_DIR/tools/gradekit.py resolve --config {path}
# Or use the "Set up a project" page on the suite's website.
"""


def render_project_toml(data: dict, defaults: dict | None = None, path: str = "project.toml") -> str:
    """Write a project config in the suite's standard layout, with helpful comments."""
    defaults = defaults or load_toml(DEFAULTS_PATH)
    d = copy.deepcopy(data or {})
    out = [PROJECT_HEADER.format(version=kit_version(), path=path)]

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
    out.append("# A commented-out answer is the preset's: it follows the preset, including later improvements to it.")
    out.append("[answers]")
    preset = (defaults.get("presets") or {}).get(proj.get("preset") or "", {})
    for q in list(questions) + [q for q in answers if q not in questions]:
        qd = questions.get(q, {})
        opts = " | ".join(qd.get("options", {}))
        if q not in answers:
            if preset and qd:
                pval = (preset.get("answers") or {}).get(q, qd.get("default"))
                if pval is not None:
                    out.append(f"# {toml_key(q):<15} = {toml_value(pval)}   # the {proj.get('preset')} preset's; uncomment to change ({opts})")
            continue
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

    schedule = d.pop("schedule", None)
    if schedule:
        _emit_table("schedule", schedule, out)
    else:
        out += ["# Ask for a grade on a schedule (the grading CI's scheduled job writes a work order when it's due):",
                "# [schedule]", "# grade_every_days     = 30", "# only_if_code_changed = true", ""]

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


CI_DIR = SUITE_DIR / "ci"


# Where a pinned grading CI gets its kit: the suite's own release assets, which keep every version (the website keeps
# only each major's newest). Any copy works with --kit-url and --kit-sha256.
KIT_RELEASES = "https://github.com/gordoncooper/code-grader/releases/download/v{version}/"
KIT_ASSET = "code-grading-suite-v{version}.zip"


def kit_pin(version: str | None = None, url: str | None = None, sha256: str | None = None) -> dict:
    """{version, url, sha256} for a grading CI: the given values, or the release's own (its SHA256SUMS), by version."""
    version = (version or kit_version()).lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        die(f"--kit-version {version}: expected X.Y.Z")
    url = url or KIT_RELEASES.format(version=version) + KIT_ASSET.format(version=version)
    if sha256:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256.lower()):
            die("--kit-sha256: expected 64 hex digits (`sha256sum kit.zip`)")
        return {"version": version, "url": url, "sha256": sha256.lower()}
    sums_url = url.rsplit("/", 1)[0] + "/SHA256SUMS"
    try:
        import urllib.request
        with urllib.request.urlopen(sums_url, timeout=60) as r:
            sums = r.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - say what to do, whatever went wrong
        die(f"couldn't read {sums_url} ({exc}). Is {version} released? Pin a released version (--kit-version), "
            "or give --kit-url URL --kit-sha256 HEX for a copy you have")
    name = url.rsplit("/", 1)[1]
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return {"version": version, "url": url, "sha256": parts[0].lower()}
    die(f"{sums_url} has no checksum for {name}")


PIN_LINE = re.compile(r'^(\s*GRADEKIT_(VERSION|URL|SHA256):\s*)"[^"]*"', re.M)


def apply_pin(text: str, pin: dict) -> str:
    vals = {"VERSION": pin["version"], "URL": pin["url"], "SHA256": pin["sha256"]}
    out, n = PIN_LINE.subn(lambda m: f'{m.group(1)}"{vals[m.group(2)]}"', text)
    if n != 3:
        die("this workflow has no GRADEKIT_VERSION, GRADEKIT_URL and GRADEKIT_SHA256 to pin (it's older than 5.0.1): "
            "reinstall it with `gradekit init --ci HOST --force`")
    return out


def ci_files(root: Path) -> list[Path]:
    return [p for p in (root / ".github" / "workflows" / "grading.yml", root / ".gitlab-ci.yml", root / ".gitlab" / "grading.yml")
            if p.exists() and "gradekit" in p.read_text(encoding="utf-8").lower()]


def cmd_ci_pin(args) -> int:
    root = Path(args.grading_repo or ".")
    files = ci_files(root)
    if not files:
        die(f"no grading CI in {root} (.github/workflows/grading.yml or .gitlab-ci.yml); `gradekit init --ci HOST` adds it")
    pin = kit_pin(args.version, args.kit_url, args.kit_sha256)
    changed = []
    for f in files:
        old = f.read_text(encoding="utf-8")
        new = apply_pin(old, pin)
        if new != old:
            f.write_text(new, encoding="utf-8")
            changed.append(str(f))
    emit(args, {"pin": pin, "changed": changed},
         (f"pinned the grading CI to kit {pin['version']} ({pin['sha256'][:12]}…) in {', '.join(changed)}" if changed
          else f"already pinned to kit {pin['version']}") +
         ". The workflow template is still the one you installed; a new kit's `init --ci HOST --force` brings its own.")
    return 0


def install_ci(root: Path, host: str, site: str | None, force: bool = False, pin: dict | None = None) -> Path:
    """Add the grading check to a grading repo, pinned to one kit zip (by default this kit's release). Returns the file."""
    text = (CI_DIR / f"{host}-grading.yml").read_text(encoding="utf-8")
    if site:
        text = text.replace("__SUITE_SITE__", site.rstrip("/"))
    pin = pin or kit_pin()
    text = text.replace("__KIT_VERSION__", pin["version"]).replace("__KIT_URL__", pin["url"]).replace("__KIT_SHA256__", pin["sha256"])
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
    print(f"wrote {dest}, pinned to kit {pin['version']}" + ("" if site else "  (set SUITE_SITE in the CI settings: your suite website's address)"))
    return dest


def invocation() -> str:
    """How to run gradekit again, as this run was started (a script path, or an installed `gradekit`)."""
    import shlex
    cmd = sys.argv[0] if sys.argv and sys.argv[0] else "gradekit"
    return f"python3 {shlex.quote(cmd)}" if cmd.endswith(".py") else shlex.quote(Path(cmd).name)


def cmd_init(args) -> int:
    defaults = load_toml(DEFAULTS_PATH)
    if args.preset not in defaults["presets"]:
        die(f"unknown preset '{args.preset}' (known: {', '.join(defaults['presets'])})")
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
    # Only the answers given are written: the rest stay the preset's (as comments), so the project follows its preset.
    answers = {q: given[q] for q in defaults["questions"] if q in given}
    proj = {"name": name, "description": "<what it is, in one sentence>"}
    if args.code_repo:
        proj["code_repo"] = args.code_repo
    if args.path:
        proj["path"] = args.path
    proj.update({"preset": args.preset, "suite": major(kit_version()),
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
        ci_file = install_ci(root, args.ci, args.site, args.force,
                             pin=kit_pin(args.kit_version, args.kit_url, args.kit_sha256))
    print(f"next: edit {out}, then run: {invocation()} resolve " + (f"--project {name}" if pdir else f"--config {out}"))
    args._result = {"project": name, "project_toml": str(out), "project_dir": str(pdir) if pdir else None,
                    "ci": str(ci_file) if ci_file else None}
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_init(sub):
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
    p.add_argument("--kit-version", metavar="X.Y.Z", help="with --ci: the kit the CI runs (default: this one); it's pinned by hash")
    p.add_argument("--kit-url", metavar="URL", help="with --ci: where the CI downloads that kit's zip (default: the suite's releases)")
    p.add_argument("--kit-sha256", metavar="HEX", help="with --ci: the zip's SHA-256, for a copy that isn't a release (no download needed)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)


def add_ci_pin(sub):
    p = sub.add_parser("ci-pin", help="pin the grading CI to an exact kit version and hash (the deliberate way to upgrade it)")
    p.add_argument("--grading-repo", metavar="DIR")
    p.add_argument("--version", metavar="X.Y.Z", help="a released kit version (default: this kit's)")
    p.add_argument("--kit-url", metavar="URL", help="another copy of the zip")
    p.add_argument("--kit-sha256", metavar="HEX", help="its SHA-256 (then nothing is downloaded)")
    p.set_defaults(fn=cmd_ci_pin)


def add_resolve(sub):
    p = sub.add_parser("resolve", help="show / write the effective config")
    with_config(p)
    p.add_argument("--explain", metavar="ID", help="explain one benchmark's weight and gate status")
    p.add_argument("--out", help="write the effective config JSON here")
    p.set_defaults(fn=cmd_resolve)


def add_presets(sub):
    p = sub.add_parser("presets", help="compare weights and gates across presets")
    p.add_argument("--config", action="append", metavar="FILE", help="org-level config to layer in")
    p.add_argument("--markdown", action="store_true")
    p.set_defaults(fn=cmd_presets)
