"""The MCP server (A7): every command as a tool, over stdio, for agents without a shell. Work orders (C4): the
request behind a run, closed by the report that answers it."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
PROJ = "projects/orders-api"


def cli(*args, cwd, code=0):
    r = subprocess.run(KIT + [str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if code is not None:
        assert r.returncode == code, r.stdout + r.stderr
    return r


def session(messages, cwd=EXAMPLE):
    """Send JSON-RPC messages to `gradekit mcp` and return its responses by id."""
    data = "".join(json.dumps(m) + "\n" for m in messages)
    r = subprocess.run(KIT + ["mcp"], input=data, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}


def call(i, name, arguments):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}


# --------------------------------------------------------------------------- MCP

def test_the_handshake_and_the_tool_list():
    out = session([INIT, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "ping"}])
    init = out[1]["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["serverInfo"]["name"] == "gradekit" and "tools" in init["capabilities"]
    tools = {t["name"]: t for t in out[2]["result"]["tools"]}
    assert {"report_finding_add", "report_score", "rubric", "validate", "carry", "guard_compare", "order_new"} <= set(tools)
    assert "mcp" not in tools and len(out) == 3, "no response to a notification; the server itself isn't a tool"
    add = tools["report_finding_add"]["inputSchema"]
    assert add["required"] == ["report", "benchmark", "title", "severity"]
    assert add["properties"]["severity"]["enum"] == ["critical", "major", "minor"]
    assert add["properties"]["sensitive"]["type"] == "boolean" and add["properties"]["cite"]["type"] == "array"
    assert tools["report_score"]["inputSchema"]["properties"]["score"]["type"] == "integer"


def test_an_unknown_protocol_version_gets_the_newest():
    init = {**INIT, "params": {**INIT["params"], "protocolVersion": "1999-01-01"}}
    assert session([init])[1]["result"]["protocolVersion"] == "2025-06-18"


def test_tools_run_the_commands():
    out = session([INIT, call(2, "rubric", {"ids": ["A3"]}), call(3, "validate", {"project": "orders-api"}),
                   call(4, "glossary", {"term": ["gate"]})])
    rub = out[2]["result"]
    assert rub["isError"] is False and rub["structuredContent"]["result"]["benchmarks"][0]["id"] == "A3"
    assert json.loads(rub["content"][0]["text"]) == rub["structuredContent"]
    val = out[3]["result"]["structuredContent"]
    assert val["ok"] and val["result"]["valid"] and val["command"] == "validate"
    assert "gate" in out[4]["result"]["structuredContent"]["text"].lower()


def test_a_whole_report_through_tools(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    out = session([INIT, call(2, "report_new", {"project": "orders-api", "commit": "b2c3d4e5f6", "model": "m"})], cwd=g)
    rel = out[2]["result"]["structuredContent"]["result"]["report"]
    out = session([INIT, call(2, "report_finding_add", {"report": rel, "benchmark": "A2", "title": "Amount unchecked", "severity": "minor",
                                                        "cite": ["src/payments/api.py:5"], "repo": str(EXAMPLE.parent / "sample-repo")}),
                   call(3, "report_score", {"report": rel, "benchmark": "A2", "score": 6, "confidence": "high"}),
                   call(4, "report_check", {"report": rel})], cwd=g)
    assert out[2]["result"]["structuredContent"]["ok"] and out[3]["result"]["structuredContent"]["ok"]
    check = out[4]["result"]["structuredContent"]
    assert check["exit_code"] == 5 and check["result"]["status"] == "incomplete"
    r = json.loads((g / rel).read_text())
    assert r["findings"][0]["evidence"][0]["quote"] and next(b for b in r["benchmarks"] if b["id"] == "A2")["score"] == 6


def test_bad_calls_are_errors_not_crashes(tmp_path):
    out = session([INIT, call(2, "nope", {}), call(3, "report_score", {"report": "x.json", "benchmark": "A1", "score": "eleven"}),
                   call(4, "rubric", {"whatever": 1}), call(5, "rubric", {"cwd": str(tmp_path / "missing")}),
                   {"jsonrpc": "2.0", "id": 6, "method": "resources/list"}])
    assert out[2]["result"]["isError"] and "unknown tool" in out[2]["result"]["content"][0]["text"]
    assert out[3]["result"]["isError"] and out[3]["result"]["structuredContent"]["exit_code"] == 64
    assert out[4]["result"]["isError"] and "unknown argument" in out[4]["result"]["content"][0]["text"]
    assert out[5]["result"]["isError"]
    assert out[6]["error"]["code"] == -32601


def test_list():
    r = cli("mcp", "--list", cwd=EXAMPLE)
    assert "report_finding_add:" in r.stdout and "\nmcp:" not in r.stdout


# --------------------------------------------------------------------------- work orders

@pytest.fixture
def grading(tmp_path):
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    return g


def new_order(g, *extra):
    out = cli("order", "new", "--project", "orders-api", "--role", "grade", "--by", "gordon", "--json", *extra, cwd=g)
    return json.loads(out.stdout)["result"]["order"]


def test_an_order_is_closed_by_the_report_that_answers_it(grading):
    o = new_order(grading, "--commit", "b2c3d4e", "--note", "after the refactor")
    assert o["status"] == "open" and o["id"].endswith("-grade-1") and (grading / PROJ / "orders" / f"{o['id']}.json").exists()
    assert new_order(grading)["id"].endswith("-grade-2")
    listed = json.loads(cli("order", "list", "--json", cwd=grading).stdout)["result"]["orders"]
    assert [x["id"] for x in listed] == [o["id"], o["id"][:-1] + "2"]
    cli("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--work-order", o["id"], cwd=grading)
    rows = json.loads(cli("order", "list", "--all", "--json", cwd=grading).stdout)["result"]["orders"]
    done = next(x for x in rows if x["id"] == o["id"])
    assert done["status"] == "done" and done["report"].endswith("-b2c3d4e")
    cli("index", cwd=grading)
    entry = json.loads((grading / "projects" / "index.json").read_text())["projects"][0]
    assert [x["id"] for x in entry["open_orders"]] == [o["id"][:-1] + "2"]


def test_close_by_hand(grading):
    o = new_order(grading)
    cli("order", "close", o["id"], "--project", "orders-api", "--status", "cancelled", "--by", "gordon", cwd=grading)
    saved = json.loads((grading / PROJ / "orders" / f"{o['id']}.json").read_text())
    assert saved["status"] == "cancelled" and saved["closed"]["by"] == "gordon"
    assert "no open work orders" in cli("order", "list", cwd=grading).stdout


def test_a_report_naming_an_unknown_order_gets_a_warning(grading):
    out = cli("report", "new", "--project", "orders-api", "--commit", "b2c3d4e5f6", "--model", "m", "--work-order", "2026-01-01-grade-9",
              "--json", cwd=grading)
    rel = json.loads(out.stdout)["result"]["report"]
    r = cli("report", "check", rel, "--json", cwd=grading, code=None)
    assert any("no orders/2026-01-01-grade-9.json" in w for w in json.loads(r.stdout)["result"]["warnings"])


def test_orders_validate_against_their_schema(gk, grading):
    jsonschema = pytest.importorskip("jsonschema")
    o = new_order(grading, "--commit", "abc")
    jsonschema.validate(o, json.loads((SRC / "schema" / "work-order.schema.json").read_text()))
    assert gk.order_problems(o, f"{o['id']}.json") == []
    assert gk.order_problems({**o, "role": "deploy"}) and gk.order_problems(o, "other.json")


def test_ci_checks_orders_as_settings(grading):
    def git(*a):
        subprocess.run(["git", "-C", str(grading), *a], env=ENV, capture_output=True, check=True)
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("switch", "-q", "-c", "pr")
    o = new_order(grading)
    git("add", "-A")
    git("commit", "-qm", "order")
    res = json.loads(subprocess.run(KIT + ["ci", "--base", "main", "--json"], cwd=grading, env=ENV, capture_output=True, text=True).stdout)["result"]
    assert res["ok"] and res["kind"] == "settings", res
    git("switch", "-q", "main")
    git("merge", "-q", "pr")
    git("switch", "-q", "-c", "edit")
    p = grading / PROJ / "orders" / f"{o['id']}.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), "role": "improve"}))
    git("commit", "-qam", "edit")
    res = json.loads(subprocess.run(KIT + ["ci", "--base", "main", "--json"], cwd=grading, env=ENV, capture_output=True, text=True).stdout)["result"]
    assert not res["ok"] and any("only changes when it's closed" in x for x in res["problems"])
