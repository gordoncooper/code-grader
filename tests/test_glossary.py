"""One vocabulary (4.3): rubric/glossary.json defines the terms; prompts, docs and the website use them,
and never the alternatives it lists."""
import json
import re
import subprocess
import sys
import urllib.request

import pytest

from conftest import SRC
from states import STATES

GLOSSARY = json.loads((SRC / "rubric" / "glossary.json").read_text())
TERMS = {t["term"]: t for g in GLOSSARY["groups"] for t in g["terms"]}
AVOID = {a.lower(): t["term"] for t in TERMS.values() for a in t.get("avoid", [])}
NOT_PROSE = ("CHANGELOG.md", "GLOSSARY.md")   # history, and the list of words to avoid itself


def avoided(text: str) -> list[str]:
    found = []
    for a, term in AVOID.items():
        for m in re.finditer(r"(?<![\w/.-])" + re.escape(a) + r"s?(?![\w/-]|\.\w)", text, re.I):
            found.append(f"'{m.group(0)}' (say '{term}'): …{text[max(0, m.start() - 40):m.end() + 20]}…".replace("\n", " "))
    return found


def prose(md: str) -> str:
    md = re.sub(r"^(```|~~~).*?^\1\s*$", "", md, flags=re.S | re.M)
    md = re.sub(r"`[^`\n]*`", "", md)
    md = re.sub(r"\]\([^)]*\)", "]", md)
    return re.sub(r"https?://\S+", "", md)


def test_glossary_is_well_formed():
    assert len(TERMS) >= 40
    for name, t in TERMS.items():
        assert t["definition"].endswith(".") and len(t["definition"]) < 300, name
        for a in t.get("avoid", []):
            assert a.lower() not in {n.lower() for n in TERMS}, f"'{a}' is both a term and a word to avoid"


def test_glossary_md_is_generated(gk):
    assert (SRC / "GLOSSARY.md").read_text() == gk.glossary_markdown(), "run `gradekit glossary --markdown --out GLOSSARY.md`"


def test_prompts_and_docs_use_the_terms():
    problems = {}
    for p in sorted(SRC.rglob("*.md")):
        if p.name in NOT_PROSE or "examples" in p.parts:
            continue
        found = avoided(prose(p.read_text()))
        if found:
            problems[str(p.relative_to(SRC))] = found
    assert not problems, json.dumps(problems, indent=1, ensure_ascii=False)


def test_tool_output_uses_the_terms(gk):
    """report.md and the PR-check comment are text people read."""
    example = SRC / "examples" / "grading-repo" / "projects" / "orders-api" / "reports"
    for md in example.glob("*/report.md"):
        assert not avoided(prose(md.read_text())), md


def test_every_prompt_points_at_the_glossary():
    for name in ("grader", "reviewer", "improver", "pr-review"):
        assert "GLOSSARY.md" in (SRC / "prompts" / f"{name}.md").read_text(), name


def test_lookup():
    run = lambda *a: subprocess.run([sys.executable, str(SRC / "tools" / "gradekit.py"), "glossary", *a], capture_output=True, text=True)
    r = run("hard", "gate")
    assert r.returncode == 0 and r.stdout.startswith("gate: ") and "say 'gate', not 'hard gate'" in r.stdout
    assert json.loads(run("effective severity", "--json").stdout)["result"]["terms"][0]["term"] == "effective severity"
    assert run("nonsense").returncode == 1


# --------------------------------------------------------------------------- the website

VISIBLE_TEXT = """() => { const c = document.querySelector('main') || document.body;
  const clone = c.cloneNode(true); clone.querySelectorAll('pre, code, script, style, .term-pop').forEach(e => e.remove());
  return clone.innerText; }"""


@pytest.mark.browser
def test_pages_use_the_terms(page, site):
    problems = {}
    for state in STATES:
        state(page, site)
        found = avoided(page.evaluate(VISIBLE_TEXT))
        if found:
            problems[state.__name__] = found
    manifest = json.loads(urllib.request.urlopen(site + "manifest.json").read())
    for f in manifest["files"]:
        path = f["path"]
        if path.startswith("docs/") and path.endswith(".html") and not any(n.replace(".md", "") in path for n in NOT_PROSE):
            page.goto(site + path)
            found = avoided(page.evaluate(VISIBLE_TEXT))
            if found:
                problems[path] = found
    assert not problems, json.dumps(problems, indent=1, ensure_ascii=False)


@pytest.mark.browser
def test_term_help_shows_the_glossary_definition(page, site):
    from states import review_tab, setup_filled
    setup_filled(page, site)
    marked = page.eval_on_selector_all("[data-term]", "els => els.map(e => e.dataset.term)")
    assert {"gate", "zone", "preset", "target", "weight", "answers"} <= set(marked)
    assert set(marked) <= set(TERMS), "every data-term is in the glossary"
    btn = page.locator("[data-term=zone] > .term-help")
    btn.click()
    pop = page.locator("#" + btn.get_attribute("aria-controls"))
    assert pop.is_visible() and btn.get_attribute("aria-expanded") == "true"
    assert TERMS["zone"]["definition"].split(".")[0] in pop.inner_text()
    page.keyboard.press("Escape")
    assert not pop.is_visible() and page.evaluate("document.activeElement.className") == "term-help"
    review_tab("overview")(page, site)
    for term in ("gate", "pillar", "maturity level"):
        page.locator(f"#results [data-term='{term}'] > .term-help").first.click()
        assert TERMS[term]["definition"].split(".")[0] in page.inner_text("#results .term-pop:not([hidden])")
    assert not page.errors
