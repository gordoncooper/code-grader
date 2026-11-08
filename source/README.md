# Code Grading Suite v4.2.2

A kit for having AI agents grade a codebase from 1 to 10 on **35 benchmarks** (29 core in 6 pillars, plus 6 that apply only to some projects), and then improve it against those grades. It is built so that **rising scores mean better code**, not just code tuned to the rubric.

**New here? Start with [Getting started](GETTING-STARTED.md).** It walks through a full cycle using the website, with nothing to install. This page is the reference.

## The pieces

| Piece | What it does |
|---|---|
| **The website** | Built from this kit with `tools/build_web.py` and hosted anywhere. Three browser tools: **Set up a project**, **Start a run** and **Review a report**. They run `gradekit.py` in the browser via Pyodide, so nothing is installed or uploaded. Also includes `AGENT.md`, the entry point for agents. |
| **The prompts** | One per job: `grader.md`, `reviewer.md`, `improver.md`, `pr-review.md`. Each starts with a table of inputs (code, grading repo and project, delivery, permissions) with sensible defaults. |
| **The rubric** | One file per pillar, with anchors, caps and "Not this" boundaries for each benchmark. |
| **The config** | `config/defaults.toml` holds every tunable setting. Each project has its own `project.toml` on top. |
| **`gradekit.py`** | Does all the arithmetic and checking: weights, gates, zones, validation, evidence checks, the rollup, ranked priorities, consensus, comparisons. Use it from the command line (Python 3.11+, standard library only), or let the website run it. |

## Where things live

Code repos stay untouched. Grading lives in **one central grading repo** (or local folders with the same layout):

```
grading/
├── README.md
├── org.toml                         optional house rules for every project
└── projects/
    └── <project>/                   one folder per graded codebase (name defaults to the code repo's)
        ├── project.toml             settings: preset, answers, zones, targets, code_repo, path   ← people
        ├── decisions.json           answers to decision questions (append-only)                    ← people
        ├── dispositions.json        findings accepted as-is (append-only)                          ← people
        ├── hidden-checks/           optional; graders run them, improvers aren't pointed at them
        └── reports/
            └── <date>-<commit>/     one folder per report, never overwritten                        ← graders, via PR
                ├── report.json
                ├── report.md
                └── runs/            only for three-grader audits
```

- **Latest and previous:** the newest report folder is the latest report, and the one before it is what it's compared with.
- **Branch names:** report PRs use `report/<project>/<date>-<commit>`; follow-up decision PRs use `decisions/<project>/<date>`.
- **Monorepos:** one project per part, each with a `path` (subfolder) in its `project.toml`.

## The cycle

| Step | Who | How | Permissions |
|---|---|---|---|
| 0. Set up (once) | You | **Set up a project** → `projects/<name>/project.toml` (+ starter `decisions.json`, `dispositions.json`) | write to grading repo |
| 1. Grade | A fresh agent session | **Start a run** → *Grade the code*. Default: a PR adding one report folder. Or save locally, or return in chat. | read code; push branches + open PRs on grading repo |
| 2. Review and decide | You (an agent can help) | **Review a report** → check, compare, answer decisions → updated `decisions.json` on the report PR → merge | write to grading repo |
| 3. Improve | Another fresh agent session | **Start a run** → *Improve the code*. Reads the latest report + decisions (or is handed the files), opens a PR on the code. | push branches + open PRs on code repo; read grading repo |
| 4. Guard | An agent, or CI | **Start a run** → *Check a pull request*: PASS or FAIL against the latest merged report | read both; comment on code PR |

Repeat from step 1. Optionally, use three graders for milestone audits; the Review page merges their runs into a consensus.

## Ground rules

1. **Graders are independent.** Use a fresh session every time, ideally a different model from the improver, and never the session that did the improving.
2. **Graders run sandboxed.** They run the repo's own scripts, so give them a disposable environment with no production credentials.
3. **People own the project files** (`project.toml`, `decisions.json`, `dispositions.json`). Graders only add report folders, by PR; they never push to the grading repo's default branch. An agent reviewer may append decisions only if `[review] allow_agent_decisions = true`.
4. **Keep security details out of public reports.** A grading repo is treated as public. Graders mark findings that would help an attacker as sensitive, and `gradekit redact --in-place` withholds their details from the committed report without changing any score. The full report, `report.private.json`, is never committed. Set `[publishing] public = false` if only trusted people can read the grading repo ([TUNING.md](TUNING.md)).
5. **Trust `gradekit`'s numbers.** Weights, gates, effective severities, pillar scores, the overall score, targets, maturity and priorities always come from `gradekit`, never from the grader's own arithmetic.

## Key concepts

- **Weights.** Each benchmark counts 1 (minor) to 3 (critical). Weights start from base values and move with the project's answers to eight questions, e.g. "handles money" raises Security, Idempotence and Durability.
- **Gates.** Correctness and Security always, plus whatever the answers add. A gate at or below 3 caps the overall score at 4.0: an average can't make up for a security hole.
- **Zones.** Hot code (money, auth, data writes) counts more than cold code (scripts, examples). Findings are one severity higher in hot zones and one lower in cold, and hot-zone work is ranked first.
- **Applicability.** Every benchmark is classified `full`, `limited` (counts at weight 1) or `not_applicable` (excluded), each with a reason. The decision is based on the project's purpose, never on current quality.
- **Targets.** `proportional` (default: 10 / 9 / 8 by weight), `maximal` or `level:L3`, plus per-benchmark overrides. Improvers stop at the target.
- **Maturity ladder.** L0 Not viable → L1 Prototype → L2 Usable → L3 Production-ready → L4 Exemplary. Each report names the exact blockers.
- **Decisions.** Fixes that change behavior or public interfaces carry a yes/no question. Improvers skip them until an entry in `decisions.json` approves them. Entries are only ever appended, and the newest answer wins.
- **Stable findings.** Findings get IDs like `A3-007` that persist across runs, with a status of new, open, fixed, regressed or accepted. Accepted findings need an entry in `dispositions.json`.
- **Metrics.** Raw measurements (coverage, vulnerability counts, complexity, setup re-run success, time to first success…) are recorded alongside the scores.
- **Integrity flags.** Text in the repo that tries to influence the grader caps maturity at L1 for that run.

All of these are tunable: see [TUNING.md](TUNING.md), and [rubric/weights.md](rubric/weights.md) for how the numbers combine.

## Command-line reference

Run from the root of the grading repo; `--project NAME` finds the project's settings, decisions, accepted findings and latest report. For a project folder anywhere else, use `--project-dir PATH`.

```bash
K="python3 SUITE_DIR/tools/gradekit.py"
$K init --project orders-api --code-repo URL --preset service   # create projects/orders-api/
$K resolve  --project orders-api [--explain A4]                 # weights, gates, zones (and why)
$K presets                                                       # compare presets side by side
$K doctor --project orders-api --repo CODE --delivery pr         # preflight: is everything a run needs in place?
$K report new --project orders-api --commit SHA                   # graders: start a report (weights and targets filled in)
$K report finding add REPORT --benchmark A3 --cite src/x.py:40 --repo CODE …   # quotes copied from the code; see `report --help`
$K report check REPORT --repo CODE [--write]                     # what's missing or wrong; --write stores the rollup
$K carry LAST_REPORT --repo CODE --commit SHA [--mode full|pr …]  # next report from the last: IDs kept, citations moved
$K report match REPORT --baseline LAST_REPORT [--apply]           # which earlier finding each new one is
$K deliver REPORT --delivery pr|save|return [--run --push --open github|gitlab]   # hand back a finished report
$K index [--check]                                               # grading repos: projects/index.json (scores, history, decisions waiting)
$K ci --base origin/main                                         # grading repos: check a pull request (see ci/README.md)
$K render report REPORT                                          # report.md from report.json
$K render pr REPORT                                             # the grading pull request's branch, title and body
$K render check BASELINE PR_REPORT                               # the PR-check comment
$K render log improve-log.json --report REPORT                   # the improver's log
$K validate --project orders-api [--publish]                     # schema, config and rule checks (latest report); --publish: safe to commit?
$K verify-evidence --project orders-api --repo CODE_DIR_OR_ZIP   # every quoted line exists
$K rollup   --project orders-api [--write]                       # gates, maturity, targets, ranked priorities
$K diff     --project orders-api [--fail-on-regression]          # latest vs previous report
$K stability projects/orders-api/reports/<folder>/runs/run-*.json --project orders-api --out projects/orders-api/reports/<folder>/report.json
$K calibrate report.json expected.json                           # grader drift check
$K redact report.json [--in-place]                               # withhold sensitive findings and hidden-check details
```

**For agents and scripts:** add `--json` to any command to get exactly one JSON object on stdout: `{"ok", "exit_code", "command", "result", "text"}`, plus `"error"` when the command failed. `result` holds the command's data (validation errors, the rollup, a diff, the path written…) and `text` holds what it would have printed.

| Exit code | Meaning |
|:-:|---|
| 0 | OK |
| 1 | Failed check, invalid report or other error |
| 2 | Regression (`diff --fail-on-regression`) |
| 3 | Unstable runs (`stability --strict`) |
| 4 | Calibration failed (`calibrate`) |
| 5 | Report not finished yet (`report check`) |
| 64 | Bad arguments (the usage message says which) |

Try it on the bundled example grading repo:

```bash
cd examples/grading-repo
python3 ../../tools/gradekit.py rollup --project orders-api
python3 ../../tools/gradekit.py diff --project orders-api
python3 ../../tools/gradekit.py verify-evidence --project orders-api --repo ../sample-repo
```

## What's in the kit

```
code-grading-suite/
├── GETTING-STARTED.md      operator tutorial and common setups
├── README.md               this reference
├── TUNING.md               customizing weights, gates, zones, targets
├── DEPLOY.md               hosting the website
├── CHANGELOG.md
├── prompts/                grader, reviewer, improver, pr-review
├── rubric/                 one file per pillar, catalog.json, weights.md
├── config/                 defaults.toml, project.example.toml
├── schema/                 report.schema.json
├── tools/
│   ├── gradekit.py         the engine (CLI + the browser API)
│   ├── build_web.py        builds the website
│   └── web/                website sources (pages, styles, scripts)
├── ci/                     the grading check for grading repos (GitHub Actions, GitLab CI, any host)
├── calibration/            checking graders against known scores
├── holdout/                writing hidden checks
└── examples/
    ├── sample-repo/        a tiny code repo
    └── grading-repo/       an example grading repo with two reports for it
```

## CI for grading repos

`gradekit ci` checks every pull request to a grading repo. Each one must be a single kind of change: either one new report folder, or a project's settings. It validates the report, its rollup and its folder name, and makes sure no private report or withheld detail is published. It keeps `decisions.json` and `dispositions.json` append-only. Then it comments a summary with a link to the Review page, and labels the pull request.

To add it, run `gradekit init --project NAME --ci github|gitlab --site URL`. It works on other hosts too. [ci/README.md](ci/README.md) covers setup and the permissions each host needs.

## Calibration and monorepos

- **Calibration:** before relying on the suite, and after big config or model changes, grade 2–3 reference repos with hand-set expected scores. See [calibration/README.md](calibration/README.md).
- **Monorepos:** the simple way is one project per part, each with a `path`. If you need a single combined score, the advanced alternative is `[[components]]` in one `project.toml`: the grader writes `components/NAME.json` per component inside the report folder, and `gradekit rollup-repo` combines them.

## Versioning

See [CHANGELOG.md](CHANGELOG.md). Scores are comparable only between reports with the same **major** suite version.
