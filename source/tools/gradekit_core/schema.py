"""The report schema check, done with the standard library."""
from __future__ import annotations

import re

from .common import die


# The kit's own JSON Schema checker, so every install checks a report's structure the same way, with nothing to
# install: the command line, the grading CI and the website. It covers the keywords the kit's schemas use (draft
# 2020-12): type, enum, const, pattern, required, properties, additionalProperties, items, $ref (within the schema),
# oneOf, minimum, maximum, exclusiveMinimum, minLength and minItems. tests/test_schema_check.py holds it to the
# jsonschema package's answers. One difference, on purpose: "integer" means a JSON integer, so 8.0 isn't one (a
# float score would otherwise pass here and then drop out of every average).

SCHEMA_KEYWORDS = {"type", "enum", "const", "pattern", "required", "properties", "additionalProperties", "items", "$ref", "oneOf",
                   "minimum", "maximum", "exclusiveMinimum", "minLength", "minItems",
                   "$schema", "$id", "$defs", "title", "description"}   # the last five only describe


def _json_type_ok(value, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, {"string": str, "object": dict, "array": list}[name])


def _json_equal(a, b) -> bool:
    """JSON equality: true is not 1, and 1 is 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _schema_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#"):
        die(f"schema: only references within the schema are supported, not {ref!r}")
    node = root
    for part in [p.replace("~1", "/").replace("~0", "~") for p in ref[1:].split("/") if p]:
        node = node[part]
    return node


def schema_errors(value, schema: dict, root: dict | None = None, path: tuple = ()):
    """Yield (path, message) for every way `value` breaks `schema`."""
    root = root if root is not None else schema
    if schema is True or schema == {}:
        return
    if schema is False:
        yield path, f"{value!r} isn't allowed here"
        return
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        die(f"schema: keyword(s) {', '.join(sorted(unknown))} aren't supported by gradekit's schema check")
    if "$ref" in schema:
        yield from schema_errors(value, _schema_ref(root, schema["$ref"]), root, path)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_json_type_ok(value, n) for n in names):
            yield path, f"{value!r} is not of type {', '.join(repr(n) for n in names)}"
            return   # the other keywords' messages would only repeat it
    if "enum" in schema and not any(_json_equal(value, e) for e in schema["enum"]):
        yield path, f"{value!r} is not one of {schema['enum']!r}"
    if "const" in schema and not _json_equal(value, schema["const"]):
        yield path, f"{schema['const']!r} was expected"
    if "oneOf" in schema:
        valid = [i for i, sub in enumerate(schema["oneOf"]) if next(schema_errors(value, sub, root, path), None) is None]
        if not valid:
            yield path, f"{value!r} is not valid under any of the given schemas"
        elif len(valid) > 1:
            yield path, f"{value!r} is valid under each of {', '.join(str(i) for i in valid)}"
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            yield path, f"{value!r} should be non-empty" if schema["minLength"] == 1 else f"{value!r} is too short"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            yield path, f"{value!r} does not match {schema['pattern']!r}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            yield path, f"{value!r} is less than the minimum of {schema['minimum']!r}"
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            yield path, f"{value!r} is less than or equal to the minimum of {schema['exclusiveMinimum']!r}"
        if "maximum" in schema and value > schema["maximum"]:
            yield path, f"{value!r} is greater than the maximum of {schema['maximum']!r}"
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            yield path, f"{value!r} should be non-empty" if schema["minItems"] == 1 else f"{value!r} is too short"
        if "items" in schema:
            for i, item in enumerate(value):
                yield from schema_errors(item, schema["items"], root, path + (i,))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                yield path, f"{key!r} is a required property"
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                yield from schema_errors(value[key], sub, root, path + (key,))
        extra = [k for k in value if k not in props]
        if extra and schema.get("additionalProperties") is False:
            yield path, (f"Additional properties are not allowed ({', '.join(repr(k) for k in extra)} "
                         f"{'was' if len(extra) == 1 else 'were'} unexpected)")
        elif extra and isinstance(schema.get("additionalProperties"), dict):
            for key in extra:
                yield from schema_errors(value[key], schema["additionalProperties"], root, path + (key,))


def schema_messages(value, schema: dict) -> list[str]:
    """`schema: PATH: MESSAGE` lines, in path order."""
    found = sorted(schema_errors(value, schema), key=lambda e: [(0, p, "") if isinstance(p, int) else (1, 0, p) for p in e[0]])
    return [f"schema: {'/'.join(str(p) for p in loc) or '(root)'}: {msg}" for loc, msg in found]
