"""The MCP server, for agents without a shell (`gradekit mcp`)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys

from .common import die, emit, GradekitError, kit_version


# `gradekit mcp` speaks the Model Context Protocol over stdin/stdout (JSON-RPC 2.0, one message per line). Its tools
# are the command line's own commands, with input schemas made from their arguments, so the two never drift apart.
# Each call runs the command in-process with --json and returns the usual envelope.

MCP_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_SKIP = {("mcp",)}


def mcp_tools(ap=None) -> list[dict]:
    from .cli import build_parser, leaf_parsers
    ap = ap or build_parser()
    tools = []
    for leaf in leaf_parsers(ap):
        words = tuple(leaf.prog.split()[1:])
        if not words or words in MCP_SKIP:
            continue
        props, required, order = {}, [], []
        for a in leaf._actions:
            if isinstance(a, (argparse._HelpAction, argparse._SubParsersAction)) or a.dest in ("json", "help"):
                continue
            if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                schema = {"type": "boolean"}
            elif isinstance(a, argparse._AppendAction) or a.nargs in ("+", "*"):
                schema = {"type": "array", "items": {"type": "string"}}
            elif a.type is int:
                schema = {"type": "integer"}
            elif a.type is float:
                schema = {"type": "number"}
            else:
                schema = {"type": "string"}
            if a.choices is not None and schema["type"] in ("string", "integer"):
                schema["enum"] = [c for c in a.choices]
            if a.help and a.help != argparse.SUPPRESS:
                schema["description"] = a.help % {"default": a.default} if "%(" in a.help else a.help
            props[a.dest] = schema
            order.append(a.dest)
            if not a.option_strings and a.nargs not in ("?", "*"):
                required.append(a.dest)
            elif a.required:
                required.append(a.dest)
        props["cwd"] = {"type": "string", "description": "folder to run in (default: the server's), e.g. the grading repo root"}
        tools.append({"name": "_".join(words).replace("-", "_"), "description": leaf.description or leaf_help(ap, words) or " ".join(words),
                      "inputSchema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
                      "_words": words, "_order": order})
    return tools


def leaf_help(ap, words) -> str | None:
    parser = ap
    help_ = None
    for w in words:
        sub = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub is None or w not in sub.choices:
            return help_
        help_ = next((c.help for c in sub._choices_actions if c.dest == w), help_)
        parser = sub.choices[w]
    return help_


def mcp_argv(tool: dict, leaf, arguments: dict) -> list[str]:
    """Command-line arguments for a tool call: positionals in order, then the options."""
    by_dest = {a.dest: a for a in leaf._actions}
    unknown = sorted(set(arguments) - set(tool["inputSchema"]["properties"]))
    if unknown:
        die(f"unknown argument(s) for {tool['name']}: {', '.join(unknown)}")
    argv = list(tool["_words"])
    for dest in tool["_order"]:
        a = by_dest[dest]
        if dest not in arguments or arguments[dest] is None:
            continue
        v = arguments[dest]
        if not a.option_strings:
            argv += [str(x) for x in v] if isinstance(v, list) else [str(v)]
            continue
        flag = a.option_strings[-1] if a.option_strings[-1].startswith("--") else a.option_strings[0]
        if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            if bool(v) == isinstance(a, argparse._StoreTrueAction):
                argv.append(flag)
        elif isinstance(a, argparse._AppendAction):
            for x in v if isinstance(v, list) else [v]:
                argv += [flag, str(x)]
        elif a.nargs in ("+", "*"):
            argv += [flag] + [str(x) for x in (v if isinstance(v, list) else [v])]
        else:
            argv += [flag, str(v)]
    return argv


def mcp_call(name: str, arguments: dict, tools: dict, leaves: dict) -> dict:
    from .cli import main
    tool = tools.get(name)
    if tool is None:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    arguments = dict(arguments or {})
    cwd = arguments.pop("cwd", None)
    try:
        argv = mcp_argv(tool, leaves[tool["_words"]], arguments) + ["--json"]
    except GradekitError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    buf, err = io.StringIO(), io.StringIO()
    here = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            try:
                main(argv)
            except SystemExit as e:   # bad arguments: argparse exits with its usage message
                env = {"ok": False, "exit_code": e.code if isinstance(e.code, int) else 64, "command": " ".join(tool["_words"]),
                       "result": None, "text": "", "error": err.getvalue().strip()}
                return {"content": [{"type": "text", "text": json.dumps(env, ensure_ascii=False)}], "structuredContent": env, "isError": True}
    except OSError as e:
        return {"content": [{"type": "text", "text": f"can't run in {cwd}: {e}"}], "isError": True}
    finally:
        os.chdir(here)
    try:
        env = json.loads(buf.getvalue())
    except json.JSONDecodeError:
        env = {"ok": False, "exit_code": 1, "command": " ".join(tool["_words"]), "result": None, "text": buf.getvalue(),
               "error": err.getvalue().strip() or "no JSON output"}
    return {"content": [{"type": "text", "text": json.dumps(env, ensure_ascii=False)}], "structuredContent": env,
            "isError": not env.get("ok", False)}


def mcp_handle(msg: dict, state: dict) -> dict | None:
    """One JSON-RPC message in, its response out (None for notifications)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def fail(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if mid is None:
        return None   # notifications/initialized and the like
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in MCP_PROTOCOLS else MCP_PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "gradekit", "version": kit_version()},
                   "instructions": "The Code Grading Suite's gradekit commands as tools. Start with the card for your role "
                                   "(prompts/cards/ in the kit) and `rubric` for one benchmark at a time. Every tool returns "
                                   "{ok, exit_code, command, result, text}; `cwd` sets the folder a tool runs in."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{k: v for k, v in t.items() if not k.startswith("_")} for t in state["tools"].values()]})
    if method == "tools/call":
        return ok(mcp_call(params.get("name"), params.get("arguments") or {}, state["tools"], state["leaves"]))
    return fail(-32601, f"method not found: {method}")


def cmd_mcp(args) -> int:
    from .cli import build_parser, leaf_parsers
    ap = build_parser()
    tools = mcp_tools(ap)
    if args.list:
        emit(args, {"tools": [t["name"] for t in tools]}, "\n".join(f"{t['name']}: {t['description']}" for t in tools))
        return 0
    state = {"tools": {t["name"]: t for t in tools}, "leaves": {tuple(p.prog.split()[1:]): p for p in leaf_parsers(ap)}}
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError) as e:   # json.JSONDecodeError is a ValueError; deep nesting recurses
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e or 'nested too deeply'}"}}
        else:
            try:
                resp = mcp_handle(msg, state) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None,
                                                                             "error": {"code": -32600, "message": "invalid request"}}
            except Exception as e:   # noqa: BLE001 - one bad message never takes the server down
                resp = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                        "error": {"code": -32603, "message": f"internal error ({type(e).__name__}: {e})"}}
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_mcp(sub):
    p = sub.add_parser("mcp", help="run as an MCP server on stdin/stdout: every command becomes a tool, for agents without a shell")
    p.add_argument("--list", action="store_true", help="print the tools it offers, and exit")
    p.set_defaults(fn=cmd_mcp)
