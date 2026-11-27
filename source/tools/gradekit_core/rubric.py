"""The rubric, one benchmark at a time, and the glossary."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import CATALOG_PATH, die, emit, GLOSSARY_PATH, kit_version, load_json, SUITE_DIR


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


# =========================================================================== rubric, one benchmark at a time
# The rubric files (rubric/A-…F-…, X-conditional.md) are the one authored source. `gradekit rubric --write` makes
# rubric/rubric.json (the rubric as data) and rubric/catalog.json (what the engine reads: IDs, names, pillars, caps and
# each benchmark's facts) from them, and `gradekit rubric --check` lints them and checks both files are current.
# `gradekit rubric A3` prints one benchmark, so a grader loads only what it's grading.

RUBRIC_FIELDS = {"Measures": "measures", "Not this": "not_this", "Assess": "assess", "Anchors": "anchors", "Caps": "caps",
                 "Scope": "scope", "Re-grade": "regrade", "Sensitive": "sensitive"}
FIELD_VALUES = {"scope": ("repo",), "regrade": ("any source change",), "sensitive": ("yes",)}
AUTOMATIC_CONDITIONS = ("open critical gap",)   # what the rollup can see in a report's own data
ANCHOR_BANDS = ("1–3", "4–6", "7–8", "9–10")
CAP_RE = re.compile(r"(.+?)\s*→\s*max\s+(\d+)\s*\(`([A-FX]\d+-cap-\d+)`(?:;\s*automatic:\s*([^)]+?))?\)\.?(?:\s+|$)")
CATALOG_COMMENT = ("Generated from the rubric files by `gradekit rubric --write`. Don't edit it, apart from suite_version (the "
                   "kit version, set at each release). Weights, gates, targets and maturity rules live in config/defaults.toml.")


def read_rubric(rubric_dir: Path | None = None) -> tuple[dict, list[str]]:
    """The rubric as data, read from the rubric files, and what's wrong with them."""
    problems, pillars, benches = [], {}, []
    for path in sorted((rubric_dir or SUITE_DIR / "rubric").glob("[A-FX]-*.md")):
        pid, rel = path.name[0], f"rubric/{path.name}"
        lines = path.read_text(encoding="utf-8").splitlines()
        title = next((m for ln in lines if (m := re.match(r"# Pillar ([A-FX]) rubric: (.+?)\s*$", ln))), None)
        if not title or title.group(1) != pid:
            problems.append(f"{rel}: the first heading must be '# Pillar {pid} rubric: NAME'")
        question = next((ln.strip().strip("*") for ln in lines if ln.startswith("*") and ln.endswith("*")), None)
        pillars[pid] = {"name": title.group(2) if title else pid, "question": question, "file": rel}
        cur, key = None, None
        for n, ln in enumerate(lines, 1):
            where = f"{rel}:{n}"
            if ln.startswith("## "):
                m = re.match(r"## ([A-FX]\d+)\. (.+?)(?: \(\*(.+)\*\))?\s*$", ln)
                cur, key = None, None
                if not m:
                    problems.append(f"{where}: a benchmark heading is '## {pid}N. Name'" + (", then (*what it applies to*)" if pid == "X" else ""))
                    continue
                cur = {"id": m.group(1), "name": m.group(2), "pillar": pid, "applies_when": m.group(3)}
                if not cur["id"].startswith(pid):
                    problems.append(f"{where}: {cur['id']} is in the pillar {pid} file")
                if bool(cur["applies_when"]) != (pid == "X"):
                    problems.append(f"{where}: " + ("a conditional benchmark says what it applies to: '(*UI code*)'" if pid == "X"
                                                     else "only conditional (X) benchmarks say what they apply to"))
                benches.append(cur)
                continue
            if cur is None:
                continue
            m = re.match(r"- \*\*(.+?):\*\*\s*(.*)$", ln)
            if m and m.group(1) not in RUBRIC_FIELDS:
                problems.append(f"{where}: unknown field '{m.group(1)}' (fields: {', '.join(RUBRIC_FIELDS)})")
                key = None
                continue
            if m:
                key, value = RUBRIC_FIELDS[m.group(1)], m.group(2).strip()
                if key in cur:
                    problems.append(f"{where}: {cur['id']} has '{m.group(1)}' twice")
                if key == "anchors":
                    cur["anchors"] = {}
                elif key == "caps":
                    found = CAP_RE.findall(value)
                    if (not found or CAP_RE.sub("", value).strip() or len(re.findall(r"-cap-\d+", value)) != len(found)
                            or any(re.search(r"→|\bmax\s+\d", when) for when, *_ in found)):
                        problems.append(f"{where}: caps are written 'WHEN → max N (`{cur['id']}-cap-1`)', each ending with a period")
                    cur["caps"] = [{"id": cid, "when": when.strip(), "max": int(mx), **({"automatic": auto.strip()} if auto else {})}
                                   for when, mx, cid, auto in found]
                    for c in cur["caps"]:
                        if not c["id"].startswith(cur["id"] + "-cap-"):
                            problems.append(f"{where}: {c['id']} is a cap on another benchmark")
                        if c.get("automatic") and c["automatic"] not in AUTOMATIC_CONDITIONS:
                            problems.append(f"{where}: {c['id']}: gradekit can't apply a cap automatically on "
                                            f"'{c['automatic']}' (it can on: {', '.join(AUTOMATIC_CONDITIONS)})")
                elif key in FIELD_VALUES:
                    if value not in FIELD_VALUES[key]:
                        problems.append(f"{where}: {m.group(1)} is '{FIELD_VALUES[key][0]}', or leave the line out")
                    cur[key] = True if value == "yes" else value
                else:
                    cur[key] = value
                continue
            m = re.match(r"\s+- \*\*(\d+(?:–\d+)?):\*\*\s*(.*)$", ln)
            if m and key == "anchors":
                cur["anchors"][m.group(1)] = m.group(2).strip()
                continue
            m = re.match(r"\s+- (.+)$", ln)
            if m and key in ("measures", "not_this", "assess"):   # sub-points, e.g. A4's idempotence and determinism
                cur[key] = (cur.get(key, "") + " " + re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1).strip())).strip()
    seen = {}
    for b in benches:
        if b["id"] in seen:
            problems.append(f"{b['id']} is defined twice")
        seen[b["id"]] = b
        for need in ("measures",) if b["pillar"] == "X" else ("measures", "assess"):
            if not b.get(need):
                problems.append(f"{b['id']} has no '{next(k for k, v in RUBRIC_FIELDS.items() if v == need)}'")
        if b["pillar"] != "X" and tuple(b.get("anchors") or ()) != ANCHOR_BANDS:
            problems.append(f"{b['id']}: anchors are the bands {', '.join(ANCHOR_BANDS)}, in order")
    caps = [c["id"] for b in benches for c in b.get("caps", [])]
    problems += [f"{c} is defined twice" for c in sorted({c for c in caps if caps.count(c) > 1})]
    data = {"_about": "Generated from the rubric files by `gradekit rubric --write`. Don't edit.",
            "suite_version": kit_version(), "pillars": pillars, "benchmarks": benches}
    return data, problems


def parse_rubric(rubric_dir: Path | None = None) -> dict:
    return read_rubric(rubric_dir)[0]


def catalog_from(data: dict) -> dict:
    """rubric/catalog.json from the rubric: what the engine needs about each benchmark."""
    benches = []
    for b in data["benchmarks"]:
        entry = {"id": b["id"], "name": b["name"], "pillar": b["pillar"], "conditional": b["pillar"] == "X"}
        entry.update({k: b[k] for k in ("scope", "regrade", "sensitive") if k in b})
        if b.get("caps"):
            entry["caps"] = b["caps"]
        benches.append(entry)
    return {"suite_version": data["suite_version"], "_comment": CATALOG_COMMENT,
            "pillars": {pid: {"name": p["name"], "rubric": p["file"]} for pid, p in data["pillars"].items()},
            "benchmarks": benches}


def json_text(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def rubric_text(b: dict, pillar: dict) -> str:
    out = [f"{b['id']}. {b['name']}" + (f" ({b['applies_when']})" if str(b.get("applies_when", "")).startswith("graded") else f" (only for {b['applies_when']})" if b.get("applies_when") else "")
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
    if args.check or args.write:
        if args.ids:
            die("--check and --write cover the whole rubric; leave out the IDs")
        data, problems = read_rubric()
        wanted = {CATALOG_PATH: json_text(catalog_from(data)), SUITE_DIR / "rubric" / "rubric.json": json_text(data)}
        stale = [path for path, text in wanted.items() if not path.exists() or path.read_text(encoding="utf-8") != text]
        rel = lambda path: str(path.relative_to(SUITE_DIR))
        if problems:
            emit(args, {"problems": problems, "stale": [rel(p) for p in stale], "written": []},
                 "\n".join(f"- {x}" for x in problems) + "\n\nfix the rubric files" + (", then run `gradekit rubric --write`" if args.write else ""))
            return 1
        if args.write:
            for path in stale:
                path.write_text(wanted[path], encoding="utf-8")
            emit(args, {"problems": [], "stale": [], "written": [rel(p) for p in stale]},
                 "\n".join(f"wrote {rel(p)}" for p in stale) or "rubric/catalog.json and rubric/rubric.json are already current")
            return 0
        emit(args, {"problems": [], "stale": [rel(p) for p in stale], "written": []},
             "\n".join(f"{rel(p)} isn't what the rubric files make: run `gradekit rubric --write`" for p in stale)
             or f"ok: {len(data['benchmarks'])} benchmarks; rubric/catalog.json and rubric/rubric.json are current")
        return 1 if stale else 0
    data = parse_rubric()
    want = [w.upper() for w in args.ids or []]
    picked = [b for b in data["benchmarks"] if not want or b["id"] in want or b["pillar"] in want]
    unknown = [w for w in want if w not in {b["id"] for b in data["benchmarks"]} and w not in data["pillars"]]
    if unknown:
        die(f"unknown benchmark or pillar: {', '.join(unknown)} (benchmarks look like A3; pillars are {', '.join(data['pillars'])})")
    emit(args, {"pillars": data["pillars"], "benchmarks": picked}, "\n\n".join(rubric_text(b, data["pillars"][b["pillar"]]) for b in picked))
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_rubric(sub):
    p = sub.add_parser("rubric", help="the rubric for one benchmark or pillar (e.g. A3, or B), as text or --json")
    p.add_argument("ids", nargs="*", metavar="ID", help="benchmarks (A3) or pillars (B); none: all")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="lint the rubric files; check rubric/catalog.json and rubric.json are current")
    g.add_argument("--write", action="store_true", help="make rubric/catalog.json and rubric/rubric.json from the rubric files")
    p.set_defaults(fn=cmd_rubric)


def add_glossary(sub):
    p = sub.add_parser("glossary", help="the suite's terms and what they mean (one, or all)")
    p.add_argument("term", nargs="*", help="a term to look up, e.g. gate or effective severity")
    p.add_argument("--markdown", action="store_true", help="the whole glossary as GLOSSARY.md")
    p.add_argument("--out", metavar="FILE", help="with --markdown: write it here")
    p.set_defaults(fn=cmd_glossary)
