"""gradekit's own schema check (5.1.0), held to the jsonschema package's answers.

Before 5.1.0 the structural check needed `jsonschema`, so a kit run with Python alone (the documented install) passed a
score of 11 or an unknown mode. Now every install runs the same check. These tests feed both checkers the kit's real
documents and thousands of one-change variants of them, and require the same verdict and the same places."""
import copy
import json
import random
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC
from test_severity import five

jsonschema = pytest.importorskip("jsonschema")

SCHEMAS = {n: json.loads((SRC / "schema" / f"{n}.schema.json").read_text()) for n in ("report", "report-4", "index", "work-order")}


def documents(gk, tmp_path):
    docs = [("report-4", json.loads(p.read_text())) for p in sorted((EXAMPLE / "projects" / "orders-api" / "reports").glob("*/report.json"))]
    docs.append(("report", five(gk)))
    docs.append(("index", json.loads((EXAMPLE / "projects" / "index.json").read_text())))
    order, _ = gk.write_order(tmp_path / "proj", "grade", requested_by="schedule", commit="0badc0ffee11", delivery="pr", notes="Scheduled")
    docs.append(("work-order", order))
    return docs


def nodes(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from nodes(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from nodes(v, path + (i,))


def mutations(value):
    """One-change variants of a value: another type, out of range, an unknown word, a key removed or added."""
    other = {str: 12345, int: "seven", float: "x", bool: "yes", type(None): "x", list: {}, dict: []}
    yield other[type(value)]
    if isinstance(value, bool):
        yield None
    elif isinstance(value, (int, float)):
        yield from (-5, 999, 0.5)
    elif isinstance(value, str):
        yield from ("", "not-a-valid-value $$")
    elif isinstance(value, list):
        yield []
        if value:
            yield value + [copy.deepcopy(value[0])]
            yield [12345]
    elif isinstance(value, dict):
        for k in list(value)[:3]:
            yield {kk: vv for kk, vv in value.items() if kk != k}
        yield {**value, "zz_unexpected": 1}


def replaced(doc, path, new):
    if not path:
        return new
    out = copy.deepcopy(doc)
    node = out
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = new
    return out


def theirs(doc, schema):
    return sorted({tuple(e.path) for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)}, key=repr)


def ours(gk, doc, schema):
    return sorted({loc for loc, _ in gk.schema_errors(doc, schema)}, key=repr)


def test_the_kits_documents_pass_both(gk, tmp_path):
    for name, doc in documents(gk, tmp_path):
        assert theirs(doc, SCHEMAS[name]) == [] and ours(gk, doc, SCHEMAS[name]) == [], name


def test_every_one_change_variant_gets_the_same_verdict(gk, tmp_path):
    rng = random.Random(51)
    checked = 0
    for name, doc in documents(gk, tmp_path):
        places = list(nodes(doc))
        for path, value in rng.sample(places, min(len(places), 140)):
            for new in mutations(value):
                if isinstance(new, float) and new.is_integer():
                    continue   # the one deliberate difference (below)
                variant = replaced(doc, path, new)
                want, got = theirs(variant, SCHEMAS[name]), ours(gk, variant, SCHEMAS[name])
                assert bool(got) == bool(want) and got == want, (name, path, new, want, got)
                checked += 1
    assert checked > 1500


def test_an_integral_float_isnt_an_integer(gk):
    """Deliberately stricter than jsonschema: a score of 8.0 would pass there, then drop out of every average."""
    r = five(gk)
    next(b for b in r["benchmarks"] if b.get("score") is not None)["score"] = 8.0
    assert any("8.0 is not of type 'integer'" in m for m in gk.schema_messages(r, SCHEMAS["report"]))


def test_the_messages_read_like_jsonschemas(gk):
    r = five(gk)
    r["mode"] = "bogus"
    b = next(b for b in r["benchmarks"] if b.get("score") is not None)
    b["score"], b["confidence"] = 11, "very high"
    del r["limitations"]
    msgs = gk.schema_messages(r, SCHEMAS["report"])
    i = r["benchmarks"].index(b)
    assert f"schema: benchmarks/{i}/confidence: 'very high' is not one of ['high', 'medium', 'low', None]" in msgs
    assert f"schema: benchmarks/{i}/score: 11 is greater than the maximum of 10" in msgs
    assert "schema: mode: 'bogus' is not one of ['full', 'pr']" in msgs
    assert "schema: (root): 'limitations' is a required property" in msgs


def test_a_keyword_the_check_doesnt_know_is_refused(gk):
    with pytest.raises(gk.GradekitError, match="aren't supported"):
        list(gk.schema_errors("x", {"type": "string", "format": "email"}))


def test_the_kits_schemas_use_only_known_keywords(gk):
    def keywords(schema):
        if not isinstance(schema, dict):
            return set()
        out = set(schema)
        for key in ("properties", "$defs"):
            for sub in (schema.get(key) or {}).values():
                out |= keywords(sub)
        for key in ("items", "additionalProperties"):
            out |= keywords(schema.get(key))
        for sub in schema.get("oneOf", []):
            out |= keywords(sub)
        return out
    for name, schema in SCHEMAS.items():
        assert keywords(schema) <= gk.SCHEMA_KEYWORDS, (name, keywords(schema) - gk.SCHEMA_KEYWORDS)


def test_validate_checks_structure_with_python_alone(tmp_path):
    """The review's probe, with jsonschema made unimportable: a score of 11 used to pass with 0 errors."""
    import shutil
    repo = tmp_path / "grading"
    shutil.copytree(EXAMPLE, repo)
    rpath = sorted((repo / "projects" / "orders-api" / "reports").glob("*/report.json"))[-1]
    r = json.loads(rpath.read_text())
    next(b for b in r["benchmarks"] if b.get("score") is not None)["score"] = 11
    rpath.write_text(json.dumps(r, indent=2))
    blocker = ("import sys, runpy\n"
               "class Block:\n"
               "    def find_spec(self, name, path=None, target=None):\n"
               "        if name.split('.')[0] == 'jsonschema':\n"
               "            raise ImportError(name)\n"
               "sys.meta_path.insert(0, Block())\n"
               f"sys.argv = ['gradekit.py'] + sys.argv[1:]\n"
               f"runpy.run_path({str(SRC / 'tools' / 'gradekit.py')!r}, run_name='__main__')\n")
    out = subprocess.run([sys.executable, "-I", "-c", blocker, "validate", "--project", "orders-api", "--json"], cwd=repo,
                         capture_output=True, text=True)
    res = json.loads(out.stdout)
    assert out.returncode == 1 and any("is greater than the maximum of 10" in e for e in res["result"]["errors"]), out.stdout
