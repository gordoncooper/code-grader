"""Operating cards and the rubric as data (A4): one page per role, the rubric one benchmark at a time, and an
inventory proving no rule was lost on the way from the long prompts to the cards."""
import json
import subprocess
import sys

import pytest

from conftest import SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
CARDS = SRC / "prompts" / "cards"
RULES = json.loads((SRC / "prompts" / "rules.json").read_text())["rules"]
ROLES = {"grader", "pr-check", "improver", "reviewer"}


def words(text: str) -> int:
    return len(text.split())


def test_every_role_has_a_card():
    assert {p.stem for p in CARDS.glob("*.md")} == ROLES


# --------------------------------------------------------------------------- no rule is lost

def test_every_rule_is_kept_by_a_check_or_a_card():
    sources = (SRC / "tools" / "gradekit.py").read_text() + (SRC / "schema" / "report.schema.json").read_text()
    missing = []
    for r in RULES:
        assert bool(r.get("check")) != bool(r.get("card")), f"{r['id']}: a rule is kept by a check or by a card"
        if r.get("check") and r["check"] not in sources:
            missing.append(f"{r['id']}: no gradekit check says {r['check']!r}")
        if r.get("card") and r["says"] not in (CARDS / f"{r['card']}.md").read_text():
            missing.append(f"{r['id']}: the {r['card']} card doesn't say {r['says']!r}")
    assert not missing, "\n".join(missing)


def test_the_inventory_is_well_formed():
    ids = [r["id"] for r in RULES]
    assert len(ids) == len(set(ids)) and len(ids) >= 50
    assert {r["role"] for r in RULES} == ROLES


# --------------------------------------------------------------------------- the word budget

def test_a_roles_must_read_context_fits_in_3000_words(gk):
    rubric = gk.parse_rubric()
    largest = max(words(gk.rubric_text(b, rubric["pillars"][b["pillar"]])) for b in rubric["benchmarks"])
    card = {r: words((CARDS / f"{r}.md").read_text()) for r in ROLES}
    assert all(n <= 1500 for n in card.values()), card
    assert card["grader"] + largest <= 3000
    assert card["pr-check"] + card["grader"] + largest <= 3000, "the PR checker also reads the grader card's rules"


# --------------------------------------------------------------------------- the rubric as data

def test_rubric_json_is_generated_from_the_rubric_files(gk):
    have = json.loads((SRC / "rubric" / "rubric.json").read_text())
    assert have == gk.parse_rubric(), "run `gradekit rubric --out rubric/rubric.json`"


def test_every_benchmark_is_in_the_rubric(gk):
    data = gk.parse_rubric()
    catalog = gk.load_catalog()
    assert [b["id"] for b in data["benchmarks"]] == [b["id"] for b in catalog["benchmarks"]]
    for b in data["benchmarks"]:
        assert b["measures"], b["id"]
        if b["pillar"] != "X":
            assert set(b["anchors"]) == {"1–3", "4–6", "7–8", "9–10"} and b["assess"], b["id"]
    a4 = next(b for b in data["benchmarks"] if b["id"] == "A4")
    assert "Idempotence:" in a4["measures"] and "Determinism:" in a4["measures"], "sub-points are kept"


def test_one_benchmark_or_one_pillar():
    one = subprocess.run(KIT + ["rubric", "A3"], capture_output=True, text=True).stdout
    assert one.startswith("A3. Robustness & Error Handling") and "Caps: A3-cap-1:" in one and "A4." not in one
    pillar = json.loads(subprocess.run(KIT + ["rubric", "b", "--json"], capture_output=True, text=True).stdout)["result"]
    assert [b["id"] for b in pillar["benchmarks"]] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    bad = subprocess.run(KIT + ["rubric", "Z9"], capture_output=True, text=True)
    assert bad.returncode == 1 and "unknown benchmark or pillar: Z9" in bad.stderr


# --------------------------------------------------------------------------- agents are sent to the cards

def test_agent_md_and_start_a_run_point_at_the_cards(built):
    agent = (built / "web" / "AGENT.md").read_text()
    for role in ROLES:
        assert f"suite/prompts/cards/{role}.md" in agent
        assert (built / "web" / "suite" / "prompts" / "cards" / f"{role}.md").is_file()
    run_js = (SRC / "tools" / "web" / "run.js").read_text()
    assert all(f'"prompts/cards/{r}.md"' in run_js for r in ROLES)
