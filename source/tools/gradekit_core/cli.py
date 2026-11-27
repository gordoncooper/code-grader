"""gradekit: companion tool for the Code Grading Suite (v6).

Never trust a grader's arithmetic or citations; check them.

Configuration:
  init             Write a starter project.toml from a preset.
  resolve          Combine defaults + your configs into the effective config (weights, gates, zones…).
  presets          Compare weights and gates across presets.

Reports:
  validate         Check a report against the schema, the config and the suite's rules.
  verify-evidence  Confirm every code citation exists in the repo and the quote matches.
  rollup           Compute gates, zones, pillar/overall scores, targets, maturity and ranked priorities.
  stability        Merge several independent runs on one commit into a median consensus.
  diff             Compare two reports (score deltas, findings, regressions, divergence).
  calibrate        Compare a report against human-expected scores for a reference repo.
  redact           Strip hidden-check details so a report can be shared with improvers.
  rollup-repo      Combine per-component reports for a monorepo.

Writing a report (graders):
  report new       Start a report: all 31 benchmarks with weights and targets from the config.
  report cite      Print an evidence object for FILE:LINES with the exact quote.
  report finding   Add or update a finding (next free ID, quotes copied from the code).
  report score     Score a benchmark, or mark it limited / not applicable.
  report strength | enforcement | action | gap | feature | flag | ran | set
  report show | update | remove   List records numbered, then correct or remove one.
  report check     List what's missing or wrong; --write stores the rollup when it's complete.
  carry            Start the next report from the last one: IDs kept, citations moved to the new code.
  report match     Suggest which earlier finding each new one is, to keep its ID.
  doctor           Preflight: Python, kit, config, code, git and push access, the suite website.
  deliver          Hand back a finished report: pr (git steps printed, or run), save or return.
  index            Grading repos: projects/index.json, every project's latest score, history and decisions waiting.
  ci               Grading repos: check a pull request and write its summary comment and labels.
  glossary         The suite's terms and what they mean.
  render           Markdown from data: report.md, the PR title and body, the PR-check comment, the improvement log.

Projects: in a grading repo, pass --project NAME (folder projects/NAME/) and commands find the
project's settings, decisions, accepted findings and latest report themselves; `diff` compares
the latest two reports. --project-dir works for a project folder anywhere.
--config (repeatable) takes TOML files layered over config/defaults.toml in order, or one
effective-config JSON produced by `resolve --out`.

The website runs this same engine in the browser (Pyodide) through web_api().

Python 3.11+ (uses tomllib); standard library only, including the report schema check.
Every command takes --json: one JSON object on stdout, {ok, exit_code, command, result, text}
(with "error" when it failed), so agents never parse text.

Exit codes: 0 ok, 1 invalid/failed check/error, 2 regression (diff --fail-on-regression),
3 unstable runs (stability --strict), 4 calibration failed, 5 report not finished (report check),
64 bad arguments.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys

from .common import GradekitError, PENDING_NOTES
from .config import project_dir_from_args, report_folders
from .rollup import add_rollup
from .publishing import add_redact, add_rollup_repo
from .validate import add_validate
from .evidence import add_verify_evidence
from .compare import add_calibrate, add_diff, add_stability
from .settings import add_ci_pin, add_init, add_presets, add_resolve
from .orders import add_due, add_order
from .authoring import (
    add_finding_add, add_finding_update, add_report_action, add_report_check, add_report_cite,
    add_report_enforcement, add_report_feature, add_report_flag, add_report_gap, add_report_new, add_report_ran,
    add_report_remove, add_report_score, add_report_set, add_report_show, add_report_strength, add_report_update,
)
from .carry import add_carry, add_report_match
from .doctor import add_doctor
from .guard import add_guard
from .render import add_decide, add_decisions, add_render
from .deliver import add_deliver
from .disputes import add_dispute, add_finding_accept, add_finding_answer
from .rubric import add_glossary, add_rubric
from .calibration import add_calibration
from .index import add_index
from .ci import add_ci
from .mcp import add_mcp


def build_parser() -> argparse.ArgumentParser:
    ap = CliParser(prog="gradekit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for add in (add_init, add_ci_pin, add_resolve, add_presets, add_validate, add_verify_evidence, add_rollup,
                add_stability, add_diff, add_calibrate, add_redact, add_decisions, add_decide, add_rollup_repo):
        add(sub)
    # ------------------------------------------------------------ report authoring
    p = sub.add_parser("report", help="build a report step by step (graders): new, cite, finding, score, check…",
                       description="Build a report without typing JSON. Weights, targets, quotes and IDs come from the tool; "
                                   "every command re-checks the report against the project's config.")
    rsub = p.add_subparsers(dest="report_cmd", required=True, metavar="ACTION")
    for add in (add_report_new, add_report_cite):
        add(rsub)
    q = rsub.add_parser("finding", help="add or update a finding")
    fsub = q.add_subparsers(dest="finding_cmd", required=True, metavar="add|update|answer|accept")
    for add in (add_finding_add, add_finding_update, add_finding_answer, add_finding_accept):
        add(fsub)
    for add in (add_report_score, add_report_strength, add_report_enforcement, add_report_action, add_report_show,
                add_report_update, add_report_remove, add_report_gap, add_report_feature, add_report_flag,
                add_report_ran, add_report_set, add_report_check, add_report_match):
        add(rsub)
    for add in (add_carry, add_doctor, add_deliver, add_ci, add_index, add_calibration, add_dispute, add_order,
                add_due, add_mcp, add_rubric, add_glossary, add_render, add_guard):
        add(sub)
    for leaf in leaf_parsers(ap):
        leaf.add_argument("--json", action="store_true",
                          help="print one JSON object instead: {ok, exit_code, command, result, text}")
        leaf.set_defaults(_leaf=leaf)   # so a stray argument is reported with the command's own usage
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args, extra = ap.parse_known_args(argv)
    if extra:
        getattr(args, "_leaf", ap).error(f"unrecognized arguments: {' '.join(extra)}")
    if not getattr(args, "json", False):
        return run_command(ap, args)
    buf = io.StringIO()
    error = None
    with contextlib.redirect_stdout(buf):
        try:
            rc = run_command(ap, args, raise_errors=True)
        except GradekitError as e:
            rc, error = 1, str(e)
        except Exception as e:   # noqa: BLE001 - --json promises exactly one JSON object, whatever goes wrong
            import traceback
            traceback.print_exc(file=sys.stderr)
            rc, error = 1, f"internal error ({type(e).__name__}: {e}): a gradekit bug; the traceback is on stderr"
    out = {"ok": rc == 0, "exit_code": rc, "command": command_name(args), "result": getattr(args, "_result", None),
           "text": buf.getvalue()}
    if error:
        out["error"] = error
    try:
        print(json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False))   # NaN and Infinity aren't JSON
    except (TypeError, ValueError) as e:
        print(json.dumps({"ok": False, "exit_code": 1, "command": out["command"], "result": None, "text": out["text"],
                          "error": f"internal error (the result isn't JSON: {e}): a gradekit bug"}, indent=2, ensure_ascii=False))
        return 1
    return rc


def command_name(args) -> str:
    return " ".join(x for x in (args.cmd, getattr(args, "report_cmd", None), getattr(args, "finding_cmd", None),
                                 getattr(args, "render_cmd", None), getattr(args, "guard_cmd", None),
                                 getattr(args, "order_cmd", None), getattr(args, "dispute_cmd", None),
                                 getattr(args, "calibration_cmd", None)) if x)


def run_command(ap, args, raise_errors: bool = False) -> int:
    if args.cmd in ("validate", "rollup", "verify-evidence", "redact") and args.report is None:
        pdir = project_dir_from_args(args)
        found = report_folders(pdir) if pdir else []
        if not found:
            ap.error("give a report file, or --project NAME with at least one report in projects/NAME/reports/")
        args.report = str(found[-1] / "report.json")
        print(f"note: using {args.report}")
    if args.cmd == "diff" and (args.old is None or args.new is None):
        pdir = project_dir_from_args(args)
        found = report_folders(pdir) if pdir else []
        if args.new is None and args.old is None:
            if len(found) < 2:
                ap.error("give two reports, or --project NAME with at least two reports")
            args.old, args.new = str(found[-2] / "report.json"), str(found[-1] / "report.json")
        elif args.new is None:
            if not found:
                ap.error("give the new report too, or --project NAME")
            args.new = str(found[-1] / "report.json")
        print(f"note: comparing {args.old} → {args.new}")
    PENDING_NOTES.clear()
    try:
        return args.fn(args)
    except GradekitError as e:
        if raise_errors:
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


EXIT_USAGE = 64   # bad arguments (BSD sysexits EX_USAGE), so it never looks like diff's "regression" (2)


class CliParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def leaf_parsers(parser):
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        yield parser
    for a in subs:
        for sp in dict.fromkeys(a.choices.values()):
            yield from leaf_parsers(sp)
