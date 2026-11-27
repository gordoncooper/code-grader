"""The rubric, one benchmark at a time, and the glossary."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import die, emit, GLOSSARY_PATH, load_catalog, load_json, SUITE_DIR
from .rollup import catalog_caps


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


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_rubric(sub):
    p = sub.add_parser("rubric", help="the rubric for one benchmark or pillar (e.g. A3, or B), as text or --json")
    p.add_argument("ids", nargs="*", metavar="ID", help="benchmarks (A3) or pillars (B); none: all")
    p.add_argument("--out", metavar="FILE", help="write the whole rubric as JSON (rubric/rubric.json)")
    p.set_defaults(fn=cmd_rubric)


def add_glossary(sub):
    p = sub.add_parser("glossary", help="the suite's terms and what they mean (one, or all)")
    p.add_argument("term", nargs="*", help="a term to look up, e.g. gate or effective severity")
    p.add_argument("--markdown", action="store_true", help="the whole glossary as GLOSSARY.md")
    p.add_argument("--out", metavar="FILE", help="with --markdown: write it here")
    p.set_defaults(fn=cmd_glossary)
