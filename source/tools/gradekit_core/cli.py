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
  report new       Start a report: all 35 benchmarks with weights and targets from the config.
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

from .common import FINDING_STATUSES, GAP_STATUSES, GradekitError, PENDING_NOTES, SEVERITIES
from .config import project_dir_from_args, report_folders
from .rollup import cmd_rollup
from .publishing import cmd_redact, cmd_rollup_repo
from .validate import cmd_validate
from .evidence import cmd_verify_evidence
from .compare import cmd_calibrate, cmd_diff, cmd_stability
from .settings import cmd_ci_pin, cmd_init, cmd_presets, cmd_resolve
from .orders import cmd_due, cmd_order_close, cmd_order_list, cmd_order_new, ORDER_ROLES
from .authoring import (
    cmd_finding_add, cmd_finding_update, cmd_report_action, cmd_report_check, cmd_report_cite,
    cmd_report_enforcement, cmd_report_feature, cmd_report_flag, cmd_report_gap, cmd_report_new, cmd_report_ran,
    cmd_report_remove, cmd_report_score, cmd_report_set, cmd_report_show, cmd_report_strength, cmd_report_update,
    CONFIDENCE, EDIT_REF_HELP, InOrderAppend, InOrderTrue, SETTABLE,
)
from .carry import cmd_carry, cmd_report_match
from .doctor import cmd_doctor
from .guard import cmd_guard_compare, cmd_guard_snapshot, GUARD_TIMEOUT
from .render import cmd_decide, cmd_decisions, cmd_render_check, cmd_render_log, cmd_render_pr, cmd_render_report
from .deliver import cmd_deliver
from .disputes import cmd_dispute_add, cmd_dispute_list, cmd_finding_accept, cmd_finding_answer
from .rubric import cmd_glossary, cmd_rubric
from .calibration import CALIBRATION_MD, CALIBRATION_RESULTS, cmd_calibration_add_run, cmd_calibration_run, GOLDEN_DIR
from .index import cmd_index
from .ci import cmd_ci
from .mcp import cmd_mcp


def build_parser() -> argparse.ArgumentParser:
    ap = CliParser(prog="gradekit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def provenance(p):
        p.add_argument("--model", help="the model grading, e.g. claude-opus-5-5 (a finished report needs it)")
        p.add_argument("--session", help="the agent session's ID or URL, so reviewers can see who graded")
        p.add_argument("--work-order", help="the work order this run answers (its ID)")
        p.add_argument("--started", metavar="UTC_TIME", help="when the run began, if before this command (e.g. "
                       "the `date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ` you noted before preflight); usage.minutes counts from it")

    def with_config(p):
        p.add_argument("--project", metavar="NAME", help="project folder projects/NAME in the grading repo")
        p.add_argument("--grading-repo", metavar="DIR", help="grading repo root (default: current folder)")
        p.add_argument("--project-dir", metavar="DIR", help="a project folder anywhere (project.toml, decisions.json, reports/…)")
        p.add_argument("--config", action="append", metavar="FILE",
                       help="config TOML (repeatable, layered in order over defaults) or one effective-config JSON; "
                            "default: the project's project.toml (+ org.toml at the grading repo root)")
        p.add_argument("--component", help="monorepo component name from the project config")

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

    p = sub.add_parser("ci-pin", help="pin the grading CI to an exact kit version and hash (the deliberate way to upgrade it)")
    p.add_argument("--grading-repo", metavar="DIR")
    p.add_argument("--version", metavar="X.Y.Z", help="a released kit version (default: this kit's)")
    p.add_argument("--kit-url", metavar="URL", help="another copy of the zip")
    p.add_argument("--kit-sha256", metavar="HEX", help="its SHA-256 (then nothing is downloaded)")
    p.set_defaults(fn=cmd_ci_pin)

    p = sub.add_parser("resolve", help="show / write the effective config")
    with_config(p)
    p.add_argument("--explain", metavar="ID", help="explain one benchmark's weight and gate status")
    p.add_argument("--out", help="write the effective config JSON here")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("presets", help="compare weights and gates across presets")
    p.add_argument("--config", action="append", metavar="FILE", help="org-level config to layer in")
    p.add_argument("--markdown", action="store_true")
    p.set_defaults(fn=cmd_presets)

    p = sub.add_parser("validate", help="schema + config + semantic checks")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--publish", action="store_true", help="also fail unless the report is safe to commit to a public grading repo")
    with_config(p)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("verify-evidence", help="check code citations against the repo")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--repo", default=".", help="repo folder, or a .zip of it (default: current folder)")
    p.add_argument("--tolerance", type=int, default=2, help="line drift allowed around the cited range (default 2)")
    p.set_defaults(fn=cmd_verify_evidence)

    p = sub.add_parser("rollup", help="compute gates, zones, scores, targets, maturity and priorities")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    with_config(p)
    p.add_argument("--write", action="store_true", help="write rollup and targets back into the report")
    p.add_argument("--out", help="write the updated report here instead")
    p.set_defaults(fn=cmd_rollup)

    p = sub.add_parser("stability", help="median consensus across independent runs")
    p.add_argument("reports", nargs="+")
    with_config(p)
    p.add_argument("--out", help="write the consensus report here")
    p.add_argument("--strict", action="store_true", help="exit 3 if any benchmark is unstable")
    p.set_defaults(fn=cmd_stability)

    p = sub.add_parser("diff", help="compare two reports (default: the project's previous and latest)")
    p.add_argument("old", nargs="?")
    p.add_argument("new", nargs="?")
    with_config(p)
    p.add_argument("--old-config", action="append", metavar="FILE", help="config the old report was graded with, if different")
    p.add_argument("--fail-on-regression", action="store_true")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("calibrate", help="compare a report with expected scores")
    p.add_argument("report")
    p.add_argument("expected")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("redact", help="make a copy safe to publish: no hidden-check details, sensitive findings withheld")
    p.add_argument("report", nargs="?", help="report JSON (default: the project's latest report)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--out", help="where to write the public copy (default: REPORT.shared.json)")
    g.add_argument("--in-place", action="store_true",
                   help="for grading repos: move the full report to REPORT.private.json and write the public one in its place")
    p.set_defaults(fn=cmd_redact)

    p = sub.add_parser("decisions", help="the newest report's decision questions and their answers")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--approved", action="store_true", help="only the approved ones: exactly what may be acted on")
    p.set_defaults(fn=cmd_decisions)

    p = sub.add_parser("decide", help="record answers to decision questions in decisions.json (by ID, or from a PR checklist)")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--approve", nargs="+", metavar="ACTION_ID")
    p.add_argument("--decline", nargs="+", metavar="ACTION_ID")
    p.add_argument("--from-checklist", metavar="FILE", help="a report PR's description ('-' for stdin): each ticked box approves its action")
    p.add_argument("--by", required=True, help="who decided (a name, email or code-host login)")
    p.add_argument("--answer", help="an answer or conditions, recorded with each decision")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="default: today (UTC)")
    p.set_defaults(fn=cmd_decide)

    p = sub.add_parser("rollup-repo", help="combine per-component reports (each must already have a rollup)")
    p.add_argument("reports", nargs="+", help="the component reports, or one report folder (with components/)")
    p.add_argument("--out")
    p.add_argument("--write", action="store_true", help="with a folder: store the result in its report.json as repo_rollup")
    p.set_defaults(fn=cmd_rollup_repo)

    # ------------------------------------------------------------ report authoring
    p = sub.add_parser("report", help="build a report step by step (graders): new, cite, finding, score, check…",
                       description="Build a report without typing JSON. Weights, targets, quotes and IDs come from the tool; "
                                   "every command re-checks the report against the project's config.")
    rsub = p.add_subparsers(dest="report_cmd", required=True, metavar="ACTION")

    def report_arg(q):
        q.add_argument("report", help="the report JSON being written")
        with_config(q)

    def evidence_args(q, cite_help="FILE:LINE or FILE:START-END; the quote is copied from the file (repeatable)"):
        q.add_argument("--cite", action=InOrderAppend, metavar="FILE:LINES", help=cite_help)
        q.add_argument("--repo", metavar="DIR_OR_ZIP", help="the code checkout (or a zip of it) that --cite reads")
        q.add_argument("--command", action=InOrderAppend, metavar="CMD",
                       help="evidence from a command you ran (@N: the Nth command recorded with `report ran`; repeatable)…")
        q.add_argument("--excerpt", action=InOrderAppend, metavar="TEXT",
                       help="…and the relevant part of its output, copied ('@file' or '-' for stdin); one per --command, in order")
        q.add_argument("--no-output", action=InOrderTrue, help="…or: it printed nothing (say what happened in --note)")
        q.add_argument("--absence", action=InOrderAppend, metavar="WHAT", help="evidence that something is missing: what you looked for (repeatable)…")
        q.add_argument("--method", action=InOrderAppend, metavar="HOW", help="…and how you searched; one per --absence, in order")
        q.add_argument("--note", action=InOrderAppend, help="a note on the evidence given just before it (repeatable); "
                       "given once, it goes on every evidence item of this command")

    q = rsub.add_parser("new", help="start a report: every benchmark with its weight and target filled in")
    with_config(q)
    q.add_argument("--commit", required=True, help="the commit being graded")
    q.add_argument("--base-commit", help="pr mode: the pull request's base commit")
    q.add_argument("--mode", choices=["full", "pr"], default="full")
    q.add_argument("--grader", default="unknown", help="the agent or person grading, e.g. Claude Code")
    provenance(q)
    q.add_argument("--run", metavar="N/COUNT", help="for several independent graders: e.g. 2/3 (writes runs/run-2.json)")
    q.add_argument("--suite-source", default="local", help="where the suite came from, e.g. the AGENT.md URL and version")
    q.add_argument("--out", metavar="FILE", help="write here instead of projects/NAME/reports/<date>-<commit>/report.json")
    q.add_argument("--force", action="store_true", help="overwrite an existing report")
    q.set_defaults(fn=cmd_report_new)

    q = rsub.add_parser("cite", help="print an evidence object for FILE:LINES with the exact quote")
    q.add_argument("spec", metavar="FILE:LINES")
    q.add_argument("--repo", required=True, metavar="DIR_OR_ZIP")
    q.add_argument("--note")
    q.add_argument("--compact", action="store_true", help="one line")
    q.set_defaults(fn=cmd_report_cite)

    q = rsub.add_parser("finding", help="add or update a finding")
    fsub = q.add_subparsers(dest="finding_cmd", required=True, metavar="add|update|answer|accept")
    q = fsub.add_parser("add", help="add a finding; its ID is the next free one for the benchmark")
    report_arg(q)
    q.add_argument("--benchmark", required=True, metavar="ID")
    q.add_argument("--title", required=True)
    q.add_argument("--severity", required=True, choices=SEVERITIES[::-1])
    q.add_argument("--status", default="new", choices=FINDING_STATUSES,
                   help="new (caused by the graded code), noticed (already there before, first recorded now), open, …")
    q.add_argument("--first-seen", metavar="COMMIT", help="default: the graded commit")
    q.add_argument("--id", help="reuse an ID from the previous report (default: next free ID)")
    q.add_argument("--paths", nargs="+", metavar="GLOB", help="areas the finding concerns, for zones when there's no code evidence")
    q.add_argument("--sensitive", action="store_true", help="details must not be public (security); see `redact`")
    q.add_argument("--cap", metavar="CAP_ID", help="the rubric cap this finding triggers, e.g. E1-cap-1: it holds while the finding is open")
    evidence_args(q)
    q.set_defaults(fn=cmd_finding_add)
    q = fsub.add_parser("update", help="change a finding or add evidence to it")
    report_arg(q)
    q.add_argument("id")
    q.add_argument("--title")
    q.add_argument("--severity", choices=SEVERITIES[::-1])
    q.add_argument("--status", choices=FINDING_STATUSES)
    q.add_argument("--disposition-concern", metavar="TEXT", help="why an accepted finding should be reconsidered ('' clears it)")
    q.add_argument("--paths", nargs="+", metavar="GLOB")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--sensitive", dest="sensitive", action="store_true", default=None)
    g.add_argument("--not-sensitive", dest="sensitive", action="store_false")
    q.add_argument("--replace-evidence", action="store_true", help="replace the evidence instead of adding to it")
    q.add_argument("--cap", metavar="CAP_ID", help="the rubric cap this finding triggers ('' removes it)")
    evidence_args(q)
    q.set_defaults(fn=cmd_finding_update)
    q = fsub.add_parser("answer", help="answer a dispute on a finding: uphold it, or withdraw the finding")
    report_arg(q)
    q.add_argument("id")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--uphold", action="store_true", help="the finding stands")
    g.add_argument("--withdraw", action="store_true", help="the finding was wrong: status withdrawn, and it counts nowhere")
    q.add_argument("--note", required=True, help="why, for the person who disputed it")
    q.set_defaults(fn=cmd_finding_answer)
    q = fsub.add_parser("accept", help="mark a finding accepted, as an entry people added to dispositions.json says")
    report_arg(q)
    q.add_argument("id")
    q.add_argument("--entry", type=int, metavar="N", help="the dispositions.json entry (1 = first) when it's a `match` entry, "
                                                          "not one naming the finding's ID")
    q.set_defaults(fn=cmd_finding_accept)

    q = rsub.add_parser("score", help="score a benchmark, or mark it limited / not applicable")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--score", type=int, choices=range(1, 11), metavar="1-10")
    q.add_argument("--confidence", choices=CONFIDENCE)
    q.add_argument("--applicability", choices=["full", "limited", "not_applicable"])
    q.add_argument("--reason", help="why it's limited or not applicable (the project's purpose, not its quality)")
    q.add_argument("--rationale", help="one line: why this score (shown in the scorecard)")
    q.add_argument("--why", help="what changed since the previous report")
    q.add_argument("--weight-note", help="if the configured weight looks wrong for this code, say why")
    q.add_argument("--cap", action="append", metavar="CAP_ID",
                   help="a rubric cap that holds for this benchmark, e.g. E1-cap-1 (repeatable). Better: put it on the finding that triggers it")
    q.add_argument("--gaming-flag", action="append", help="a gaming pattern you found (repeatable)")
    q.set_defaults(fn=cmd_report_score)

    q = rsub.add_parser("strength", help="add a strength (positive evidence) to a benchmark")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--text", required=True, help="what is good")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_strength)

    q = rsub.add_parser("enforcement", help="add evidence that a benchmark's quality is enforced (CI, lint rule, test)")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--text", required=True, help="what enforces it, e.g. 'CI runs mypy --strict on every PR'")
    evidence_args(q)
    q.set_defaults(fn=cmd_report_enforcement)

    q = rsub.add_parser("action", help="add a step on a benchmark's path to its target")
    report_arg(q)
    q.add_argument("benchmark", metavar="ID")
    q.add_argument("--action", required=True, help="what to do")
    q.add_argument("--resolves", nargs="*", default=[], metavar="ID", help="finding or gap IDs it resolves")
    q.add_argument("--new-score", type=int, required=True, choices=range(1, 11), metavar="1-10", help="the benchmark's expected score once this action is done, counting this benchmark's earlier actions as done too (so a second step that takes it from 6 to 8 says 8)")
    q.add_argument("--effort", required=True, choices=["S", "M", "L"])
    q.add_argument("--decision", metavar="QUESTION", help="a yes/no question a person must answer first")
    q.add_argument("--optional", action="store_true", help="beyond the target; only done when asked")
    q.add_argument("--why-first", metavar="TEXT", help="one line for top_priorities on why it comes first (default: a line from its tier)")
    q.set_defaults(fn=cmd_report_action)

    q = rsub.add_parser("show", help="list a report's strengths, enforcement, findings and actions, numbered for update and remove")
    q.add_argument("report", help="the report JSON")
    q.add_argument("what", nargs="?", metavar="ID|features|gaps|metrics|commands",
                   help="one benchmark, or the features, gaps, metrics or commands (default: every benchmark with records)")
    q.set_defaults(fn=cmd_report_show)

    q = rsub.add_parser("update", help="change a strength, enforcement item, action or gap (findings: `report finding update`)")
    report_arg(q)
    q.add_argument("ref", metavar="REF", help=EDIT_REF_HELP.replace(", feature/N, or, for remove, a finding ID", ""))
    q.add_argument("--text", help="strength or enforcement: the new text")
    evidence_args(q)
    q.add_argument("--replace-evidence", action="store_true", help="strength or enforcement: replace its evidence instead of adding to it")
    q.add_argument("--action", help="action: what to do")
    q.add_argument("--new-score", type=int, choices=range(1, 11), metavar="1-10", help="action: see `report action --help`")
    q.add_argument("--effort", choices=["S", "M", "L"])
    q.add_argument("--resolves", nargs="*", metavar="ID", help="action: the finding or gap IDs it resolves (replaces the list)")
    q.add_argument("--decision", metavar="QUESTION", help="action: a question a person must answer first ('' for none)")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--optional", dest="optional", action="store_true", default=None, help="action: beyond the target, done only when asked")
    g.add_argument("--not-optional", dest="optional", action="store_false", help="action: needed to reach the target")
    q.add_argument("--why-first", metavar="TEXT", help="action: one line for top_priorities ('' for the default)")
    q.add_argument("--gap", help="gap: its text")
    q.add_argument("--severity", choices=SEVERITIES[::-1])
    q.add_argument("--necessity", choices=["must-have", "nice-to-have"])
    q.add_argument("--status", choices=GAP_STATUSES)
    q.add_argument("--rationale")
    q.add_argument("--benchmarks", nargs="+", metavar="ID", help="gap: the benchmarks it affects (replaces the list)")
    q.add_argument("--command-text", metavar="CMD", help="command/N: exactly what ran (evidence quoting the old text follows it)")
    q.add_argument("--exit-code", type=int, help="command/N")
    q.add_argument("--summary", help="command/N: what it showed")
    q.add_argument("--workdir", metavar="DIR", help="command/N ('' to clear)")
    q.add_argument("--env", metavar="TEXT", help="command/N ('' to clear)")
    q.set_defaults(fn=cmd_report_update)

    q = rsub.add_parser("remove", help="remove a strength, enforcement item, action, feature, or a finding or gap new in this report")
    report_arg(q)
    q.add_argument("ref", metavar="REF", help=EDIT_REF_HELP + " (only one no earlier report has: IDs that were reported stay)")
    q.set_defaults(fn=cmd_report_remove)

    q = rsub.add_parser("gap", help="add a gap (something the code should do but doesn't)")
    report_arg(q)
    q.add_argument("--gap", required=True)
    q.add_argument("--severity", required=True, choices=SEVERITIES[::-1])
    q.add_argument("--necessity", required=True, choices=["must-have", "nice-to-have"])
    q.add_argument("--status", default="new", choices=GAP_STATUSES)
    q.add_argument("--rationale")
    q.add_argument("--benchmarks", nargs="+", required=True, metavar="ID")
    q.set_defaults(fn=cmd_report_gap)

    q = rsub.add_parser("feature", help="add a feature to the inventory (the same name again updates it: status, source, evidence)")
    report_arg(q)
    q.add_argument("--feature", required=True)
    q.add_argument("--source", required=True, help="where it's claimed, e.g. README")
    q.add_argument("--status", required=True, choices=["complete", "partial", "stub", "broken", "undocumented"])
    evidence_args(q)
    q.set_defaults(fn=cmd_report_feature)

    q = rsub.add_parser("flag", help="record an integrity flag: repo text that tries to influence grading")
    report_arg(q)
    q.add_argument("--description", required=True)
    evidence_args(q)
    q.set_defaults(fn=cmd_report_flag)

    q = rsub.add_parser("ran", help="record a command you ran")
    report_arg(q)
    q.add_argument("--command", "--command-text", dest="command_text", required=True, metavar="CMD",
                   help="exactly what you ran, so others (and `guard snapshot --from-report`) can run it again; notes go in --summary")
    q.add_argument("--exit-code", type=int)
    q.add_argument("--summary", required=True)
    q.add_argument("--workdir", metavar="DIR", help="where it ran, if not the code checkout (e.g. 'a copy of CODE')")
    q.add_argument("--output", metavar="FILE", help="its output (saved to a file, or '-' for stdin): gradekit keeps a fingerprint, "
                   "so `report check` can tell whether excerpts were copied from it")
    q.add_argument("--env", metavar="TEXT", help="what it ran with, e.g. 'Python 3.13 venv with requirements-dev.txt'")
    q.set_defaults(fn=cmd_report_ran)

    q = rsub.add_parser("set", help=f"set a field: {', '.join(SETTABLE)} (dotted keys, e.g. metrics.line_coverage_pct)")
    report_arg(q)
    q.add_argument("key", help="e.g. summary, metrics.line_coverage_pct, or limitations.2 (one item of a list)")
    q.add_argument("value", nargs="?", help="JSON (a number, true, an object…) or plain text")
    q.add_argument("--append", action="store_true", help="append to a list")
    q.add_argument("--remove", action="store_true", help="remove one item of a list (key LIST.N)")
    q.set_defaults(fn=cmd_report_set)

    q = rsub.add_parser("check", help="what's missing or wrong; with --write, store the rollup when it's complete")
    report_arg(q)
    q.add_argument("--repo", metavar="DIR_OR_ZIP", help="also verify every citation against the code")
    q.add_argument("--tolerance", type=int, default=2)
    q.add_argument("--write", action="store_true", help="store the rollup and the finish time")
    q.set_defaults(fn=cmd_report_check)

    q = rsub.add_parser("match", help="suggest which earlier finding each newly written finding is, to keep its ID")
    report_arg(q)
    q.add_argument("--baseline", required=True, help="the previous report")
    q.add_argument("--threshold", type=float, default=0.35, help="lowest similarity to suggest (0–1)")
    q.add_argument("--apply", action="store_true", help="rename unambiguous matches to their earlier IDs")
    q.add_argument("--apply-at", type=float, default=0.6, help="lowest similarity --apply acts on")
    q.set_defaults(fn=cmd_report_match)

    # ------------------------------------------------------------ carry
    p = sub.add_parser("carry", help="start the next report from the last one, with citations moved to the new code")
    p.add_argument("baseline", help="the last report (the full one, not the public copy, if it withholds findings)")
    p.add_argument("--repo", required=True, metavar="DIR_OR_ZIP", help="the code at the new commit")
    p.add_argument("--commit", required=True, help="the new commit")
    p.add_argument("--mode", choices=["pr", "full"], default="pr")
    p.add_argument("--base-commit", help="pr mode: the pull request's base commit")
    p.add_argument("--changed", nargs="+", metavar="FILE", help="files the change touched (default: from git, if --repo is a checkout)")
    p.add_argument("--touched", nargs="+", metavar="ID", help="more benchmarks to re-grade, on top of those suggested from the changed files")
    p.add_argument("--out", metavar="FILE", help="where to write (required in pr mode; full mode defaults to a new report folder)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-withheld", action="store_true", help="carry from a public copy anyway")
    p.add_argument("--grader", help="the agent or person grading now (default: the baseline's)")
    provenance(p)
    with_config(p)
    p.set_defaults(fn=cmd_carry)

    # ------------------------------------------------------------ doctor
    p = sub.add_parser("doctor", help="preflight: check Python, the kit, the config, the code and delivery access before a run")
    p.add_argument("--repo", metavar="DIR_OR_ZIP", help="the code to grade")
    p.add_argument("--delivery", choices=["pr", "save", "return"], help="also check what this delivery needs (pr: git, identity, push)")
    p.add_argument("--open", choices=["github", "gitlab"], help="pr: also check gh / glab sign-in")
    p.add_argument("--remote", default="origin")
    p.add_argument("--site", metavar="URL", help="the suite website: check it's reachable and serves this kit's version")
    with_config(p)
    p.set_defaults(fn=cmd_doctor)

    # ------------------------------------------------------------ deliver
    p = sub.add_parser("deliver", help="hand back a finished report: pr, save or return (prints the git steps, or runs them)",
                       description="Checks the report is finished, withholds sensitive findings if the grading repo is public, "
                                   "renders report.md, then delivers. For pr it prints the branch, commit, title and body "
                                   "(or does the git steps with --run); pushing and opening the pull request are opt-in.")
    p.add_argument("report", help="the finished report.json, in projects/NAME/reports/<folder>/")
    p.add_argument("--delivery", choices=["pr", "save", "return"], default="pr")
    p.add_argument("--repo", metavar="DIR_OR_ZIP", help="also verify every citation against the code first")
    p.add_argument("--run", action="store_true", help="pr: create the branch and commit (otherwise just print the steps)")
    p.add_argument("--push", action="store_true", help="pr, with --run: push the branch")
    p.add_argument("--open", choices=["github", "gitlab"], help="pr, with --push: open it with gh or glab (needs them installed and signed in)")
    p.add_argument("--base", metavar="BRANCH", help="pr: branch to start from and target (default: the remote's default branch)")
    p.add_argument("--remote", default="origin")
    p.add_argument("--branch", help="default: report/<project>/<date>-<commit>")
    p.add_argument("--body-file", metavar="FILE", help="where to write the pull request body (default: a temp file)")
    p.add_argument("--site", metavar="URL", help="the suite website, for a Review-page link in the body")
    p.add_argument("--grading-repo-url", metavar="URL", help="the grading repo's address, for that link")
    with_config(p)
    p.set_defaults(fn=cmd_deliver)

    # ------------------------------------------------------------ ci
    p = sub.add_parser("ci", help="grading repos: check a pull request (one report, or settings), write a comment and labels",
                       description="Run in a grading repo's CI on a pull request. Templates for GitHub Actions and GitLab CI "
                                   "are in the kit's ci/ folder (`gradekit init --ci github|gitlab` adds one).")
    p.add_argument("--base", required=True, help="the target branch, e.g. origin/main")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--grading-repo", metavar="DIR", help="the grading repo checkout (default: current folder)")
    p.add_argument("--changed", nargs="+", metavar="[A|M|D:]PATH", help="the changed files, if git can't list them")
    p.add_argument("--site", metavar="URL", help="the suite website, for a Review-page link")
    p.add_argument("--grading-repo-url", metavar="URL", help="this repo's address, for that link")
    p.add_argument("--branch", help="the pull request's branch, for that link")
    p.add_argument("--comment-file", metavar="FILE", help="write the summary comment (markdown) here")
    p.add_argument("--labels-file", metavar="FILE", help="write the labels to set, one per line, here")
    p.set_defaults(fn=cmd_ci)

    # ------------------------------------------------------------ index
    p = sub.add_parser("index", help="grading repos: write projects/index.json (latest scores, history, decisions waiting)")
    p.add_argument("--grading-repo", metavar="DIR", help="grading repo root (default: current folder)")
    p.add_argument("--out", metavar="FILE", help="default: projects/index.json")
    p.add_argument("--check", action="store_true", help="don't write; exit 1 if the file is missing or out of date")
    p.set_defaults(fn=cmd_index)

    # ------------------------------------------------------------ glossary
    p = sub.add_parser("calibration", help="the calibration program: golden repos, repeated runs, published results")
    csub = p.add_subparsers(dest="calibration_cmd", required=True, metavar="STEP")
    q = csub.add_parser("add-run", help="save a grader's scores for a golden repo as runs/run-N.json")
    q.add_argument("golden", help="the golden repo's folder, e.g. calibration/golden/schedule")
    q.add_argument("report", help="the grader's report.json for the golden commit")
    q.add_argument("--note", help="e.g. which model or session, anything unusual")
    q.set_defaults(fn=cmd_calibration_add_run)
    q = csub.add_parser("run", help="score every run against its golden repo; write results.json and RESULTS.md")
    q.add_argument("--golden-dir", default=str(GOLDEN_DIR))
    q.add_argument("--min-runs", type=int, default=3, help="independent runs each golden repo needs (default 3)")
    q.add_argument("--out", default=str(CALIBRATION_RESULTS))
    q.add_argument("--markdown", default=str(CALIBRATION_MD))
    q.add_argument("--check", action="store_true", help="only check the written results are up to date (exit 1 if not)")
    q.set_defaults(fn=cmd_calibration_run)

    p = sub.add_parser("dispute", help="say a finding is wrong (people): the next grader must answer it")
    dsub = p.add_subparsers(dest="dispute_cmd", required=True, metavar="STEP")
    q = dsub.add_parser("add", help="append a dispute to projects/NAME/disputes.json")
    with_config(q)
    q.add_argument("finding", metavar="FINDING_ID")
    q.add_argument("--reason", required=True, help="why the finding is wrong")
    q.add_argument("--by", required=True, help="who disputes it")
    q.add_argument("--report", metavar="FOLDER", help="the report folder it's in (default: the newest with that finding)")
    q.set_defaults(fn=cmd_dispute_add)
    q = dsub.add_parser("list", help="open disputes (with --all, every one), for a project or the whole grading repo")
    with_config(q)
    q.add_argument("--all", action="store_true")
    q.set_defaults(fn=cmd_dispute_list)

    p = sub.add_parser("order", help="work orders: the request behind a run (new, list, close)")
    osub = p.add_subparsers(dest="order_cmd", required=True, metavar="STEP")
    q = osub.add_parser("new", help="write projects/NAME/orders/<id>.json, and print the ID to give the agent")
    with_config(q)
    q.add_argument("--role", required=True, choices=ORDER_ROLES)
    q.add_argument("--commit", help="the commit to grade or check")
    q.add_argument("--base-commit", help="prcheck: the change's base commit")
    q.add_argument("--change", metavar="URL", help="prcheck: the pull request")
    q.add_argument("--delivery", help="how the agent hands back its work, e.g. pr")
    q.add_argument("--budget", help="improve: how much to do, e.g. \"tier 0 and 1\"")
    q.add_argument("--by", help="who asked")
    q.add_argument("--note", help="anything else the agent should know")
    q.set_defaults(fn=cmd_order_new)
    q = osub.add_parser("list", help="open work orders (with --all, every one), for a project or the whole grading repo")
    with_config(q)
    q.add_argument("--all", action="store_true")
    q.set_defaults(fn=cmd_order_list)
    q = osub.add_parser("close", help="mark a work order done or cancelled (a report that records its ID closes it by itself)")
    with_config(q)
    q.add_argument("id")
    q.add_argument("--status", choices=["done", "cancelled"], default="done")
    q.add_argument("--by")
    q.add_argument("--note")
    q.set_defaults(fn=cmd_order_close)

    p = sub.add_parser("due", help="which projects are due for a grade under their [schedule]; --write-orders asks for each")
    p.add_argument("--project", metavar="NAME"); p.add_argument("--grading-repo", metavar="DIR"); p.add_argument("--project-dir", metavar="DIR")
    p.add_argument("--check-code", action="store_true", help="read each code repo's newest commit with `git ls-remote` (needs read access)")
    p.add_argument("--code-head", action="append", metavar="NAME=SHA", help="a project's newest code commit, if you know it (repeatable)")
    p.add_argument("--write-orders", action="store_true", help="write a grade work order for each project that's due")
    p.add_argument("--by", default="schedule", help="requested_by on the orders (default: schedule)")
    p.add_argument("--today", metavar="YYYY-MM-DD", help="default: today (UTC)")
    p.set_defaults(fn=cmd_due)

    p = sub.add_parser("mcp", help="run as an MCP server on stdin/stdout: every command becomes a tool, for agents without a shell")
    p.add_argument("--list", action="store_true", help="print the tools it offers, and exit")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("rubric", help="the rubric for one benchmark or pillar (e.g. A3, or B), as text or --json")
    p.add_argument("ids", nargs="*", metavar="ID", help="benchmarks (A3) or pillars (B); none: all")
    p.add_argument("--out", metavar="FILE", help="write the whole rubric as JSON (rubric/rubric.json)")
    p.set_defaults(fn=cmd_rubric)

    p = sub.add_parser("glossary", help="the suite's terms and what they mean (one, or all)")
    p.add_argument("term", nargs="*", help="a term to look up, e.g. gate or effective severity")
    p.add_argument("--markdown", action="store_true", help="the whole glossary as GLOSSARY.md")
    p.add_argument("--out", metavar="FILE", help="with --markdown: write it here")
    p.set_defaults(fn=cmd_glossary)

    # ------------------------------------------------------------ render
    p = sub.add_parser("render", help="markdown from report data: report.md, PR title/body, PR-check comment, improvement log")
    rsub = p.add_subparsers(dest="render_cmd", required=True, metavar="WHAT")

    def render_dest(q, default_note):
        q.add_argument("--out", metavar="FILE", help=f"where to write ('-' for stdout; default: {default_note})")
        q.add_argument("--stdout", action="store_true", help="print instead of writing the default file")

    q = rsub.add_parser("report", help="report.md from report.json (sensitive findings withheld in public grading repos)")
    q.add_argument("report")
    render_dest(q, "beside the report, e.g. report.md")
    with_config(q)
    q.set_defaults(fn=cmd_render_report)

    q = rsub.add_parser("pr", help="the grading pull request: branch, title and body (title on the first line)")
    q.add_argument("report")
    q.add_argument("--site", metavar="URL", help="the suite website, for a link to its Review page")
    q.add_argument("--grading-repo-url", metavar="URL", help="the grading repo (e.g. https://github.com/acme/grading), for that link")
    q.add_argument("--branch", help="default: report/<project>/<date>-<commit>")
    with_config(q)
    q.set_defaults(fn=cmd_render_pr)

    q = rsub.add_parser("check", help="the PR-check comment, comparing the baseline report with the PR report")
    q.add_argument("old", help="baseline report (newest merged report)")
    q.add_argument("new", help="the PR report (mode pr)")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_check)

    q = rsub.add_parser("log", help="the improver's log, from a small JSON file (see prompts/improver.md)")
    q.add_argument("log", help="improve-log.json")
    q.add_argument("--report", help="the report worked from: adds pending decisions as blocked and declined ones as skipped")
    q.add_argument("--guard", metavar="FILE", help="the `guard compare` result: adds the before → after table of the code's checks")
    render_dest(q, "stdout")
    with_config(q)
    q.set_defaults(fn=cmd_render_log)

    # ------------------------------------------------------------ guard
    p = sub.add_parser("guard", help="improvers: run the code's checks before changing it, then prove nothing got worse")
    gsub = p.add_subparsers(dest="guard_cmd", required=True, metavar="STEP")
    q = gsub.add_parser("snapshot", help="before any change: run the checks and record the results (in .git/, never committed)")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--check", action="append", metavar="NAME=COMMAND",
                   help='a check to run, e.g. tests="pytest -q" (repeatable; run from the code folder, or --path)')
    q.add_argument("--from-report", metavar="REPORT", help="also use the tests, lint, type-check, coverage, build and audit commands the grader ran")
    q.add_argument("--path", metavar="SUBDIR", help="only this part of the code (the project's `path`): checks run there, and only it is scanned")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write it (default: .git/gradekit/guard-before.json)")
    q.add_argument("--list", action="store_true", help="show the checks it would run, and run nothing")
    q.set_defaults(fn=cmd_guard_snapshot)
    q = gsub.add_parser("compare", help="after changing: run the same checks again; exit 2 if anything got worse")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--before", metavar="FILE", help="the snapshot (default: .git/gradekit/guard-before.json)")
    q.add_argument("--after", metavar="FILE", help="compare with this snapshot instead of running the checks now")
    q.add_argument("--explain", action="append", metavar="KEY=REASON",
                   help='a deliberate change, e.g. tests.passed="removed the tests of the deleted export helper" (repeatable)')
    q.add_argument("--coverage-tolerance", type=float, default=0.1, metavar="POINTS", help="coverage may move this much (default 0.1)")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write the result (default: .git/gradekit/guard-compare.json)")
    q.set_defaults(fn=cmd_guard_compare)

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
