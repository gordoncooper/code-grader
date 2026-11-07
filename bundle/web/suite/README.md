# Code Grading Suite v4.1.0

A kit for having AI agents grade a codebase from 1 to 10 on **35 benchmarks** (29 core in 6 pillars, plus 6 that apply only to some projects), and then improve it against those grades. It is built so that **rising scores mean better code**, not just code tuned to the rubric.

**New here? Start with [Getting started](GETTING-STARTED.md).** It walks through a full cycle using the website, with nothing to install. This page is the reference.

## The pieces

| Piece | What it does |
|---|---|
| **The website** | Built from this kit with `tools/build_web.py` and hosted anywhere. Three browser tools: **Set up a project**, **Start a run** and **Review a report**. They run `gradekit.py` in the browser via Pyodide, so nothing is installed or uploaded. Also includes `AGENT.md`, the entry point for agents. |
| **The prompts** | One per job: `grader.md`, `reviewer.md`, `improver.md`, `pr-review.md`. Each starts with a table of inputs (code, grading folder, delivery) with sensible defaults. |
| **The rubric** | One file per pillar, with anchors, caps and "Not this" boundaries for each benchmark. |
| **The config** | `config/defaults.toml` holds every tunable setting. Each project has its own `project.toml` on top. |
| **`gradekit.py`** | Does all the arithmetic and checking: weights, gates, zones, validation, evidence checks, roll-ups, ranked priorities, consensus, comparisons. Use it from the command line (Python 3.11+, standard library only), or let the website run it. |

## Where things live

```
your-repo/
└── .grading/                  the grading folder
    ├── README.md              explains the folder to contributors
    ├── project.toml           settings + accepted findings + decision answers   ← people only
    ├── report.json            latest report (older ones: git history)           ← graders
    ├── report.md              the same, readable
    └── runs/                  only when several graders grade one commit
```

- **Hidden checks** (optional) live *outside* the repo, somewhere only graders can reach. Their per-check results stay next to them; reports only carry the pass rate.
- **Stricter setup:** keep the same folder layout in a separate private repo or folder instead, so improvers can't even read it. Every prompt takes the grading folder's location as an input.
- **Protecting the folder:** add a CODEOWNERS line (`/.grading/ @your-team`). The pull-request check also fails any improvement PR that touches `.grading/`.

## The cycle

| Step | Who | How |
|---|---|---|
| 0. Set up (once) | You | **Set up a project** page → `.grading/project.toml` |
| 1. Grade | A fresh agent session | **Start a run** → *Grade the code*. Delivers `report.json` / `report.md` as a PR, a commit, saved files, or back in the chat. |
| 2. Review and decide | You (an agent can help) | **Review a report** → check it, answer decision questions → paste `[[decisions]]` into `project.toml` on the grader's PR → merge |
| 3. Improve | Another fresh agent session | **Start a run** → *Improve the code*. Reads `.grading/`, follows the ranked priorities, opens a PR. |
| 4. Guard | An agent, or CI | **Start a run** → *Check a pull request*: PASS or FAIL against the base report |

Repeat from step 1. Optionally, use three graders for milestone audits; the Review page merges their runs into a consensus.

## Ground rules

1. **Graders are independent.** Use a fresh session every time, ideally a different model from the improver, and never the session that did the improving.
2. **Graders run sandboxed.** They run the repo's own scripts, so give them a disposable environment with no production credentials.
3. **People own `project.toml`.** It holds the weights, gates, zones, accepted findings and decisions. Agents only ever *read* it, except an agent reviewer explicitly allowed to answer decision questions (`[review] allow_agent_decisions = true`).
4. **Hidden checks stay hidden.** They live outside the repo, and only aggregate pass rates appear in reports.
5. **Trust `gradekit`'s numbers.** Weights, gates, effective severities, pillar scores, the overall score, targets, maturity and priorities always come from `gradekit`, never from the grader's own arithmetic.

## Key concepts

- **Weights.** Each benchmark counts 1 (minor) to 3 (critical). Weights start from base values and move with the project's answers to eight questions, e.g. "handles money" raises Security, Idempotence and Durability.
- **Gates.** Correctness and Security always, plus whatever the answers add. A gate at or below 3 caps the overall score at 4.0: an average can't make up for a security hole.
- **Criticality zones.** Hot code (money, auth, data writes) counts more than cold code (scripts, examples). Findings are one severity higher in hot zones and one lower in cold, and hot-zone work is ranked first.
- **Applicability.** Every benchmark is classified `full`, `limited` (counts at weight 1) or `not_applicable` (excluded), each with a reason. The decision is based on the project's purpose, never on current quality.
- **Targets.** `proportional` (default: 10 / 9 / 8 by weight), `maximal` or `level:L3`, plus per-benchmark overrides. Improvers stop at the target.
- **Maturity ladder.** L0 Not viable → L1 Prototype → L2 Usable → L3 Production-ready → L4 Exemplary. Each report names the exact blockers.
- **Decisions.** Fixes that change behavior or public interfaces carry a yes/no question. Improvers skip them until a `[[decisions]]` entry in `project.toml` approves them. Entries are only ever appended, and the newest answer wins.
- **Stable findings.** Findings get IDs like `A3-007` that persist across runs, with a status of new, open, fixed, regressed or accepted. Accepted findings need a `[[dispositions]]` entry in `project.toml`.
- **Metrics.** Raw measurements (coverage, vulnerability counts, complexity, setup re-run success, time to first success…) are recorded alongside the scores.
- **Integrity flags.** Text in the repo that tries to influence the grader caps maturity at L1 for that run.

All of these are tunable: see [TUNING.md](TUNING.md), and [rubric/weights.md](rubric/weights.md) for how the numbers combine.

## Command-line reference

Inside a repo that has a `.grading/` folder, `gradekit` finds `project.toml` and `report.json` by itself.

```bash
K="python3 SUITE_DIR/tools/gradekit.py"
$K init --preset service --name myapp --grading-dir .grading   # create .grading/project.toml + README
$K resolve [--explain A4]                                      # weights, gates, zones (and why)
$K presets                                                     # compare presets side by side
$K validate                                                    # schema, config and rule checks
$K verify-evidence [--repo PATH_OR_ZIP]                        # every quoted line exists
$K rollup [--write]                                            # gates, maturity, targets, ranked priorities
$K stability runs/run-1.json runs/run-2.json runs/run-3.json --out .grading/report.json
$K diff OLD.json NEW.json [--fail-on-regression]               # exit 2 = something got worse
$K calibrate report.json expected.json                         # grader drift check
$K redact report.json                                          # strip hidden-check details
$K rollup-repo components/*.json                               # monorepos
```

Try it on the bundled sample:

```bash
cd examples/sample-repo
python3 ../../tools/gradekit.py resolve
python3 ../../tools/gradekit.py validate && python3 ../../tools/gradekit.py rollup
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
├── calibration/            checking graders against known scores
├── holdout/                writing hidden checks
└── examples/sample-repo/   a tiny repo with a .grading/ folder and a full example report
```

## Calibration and monorepos

- **Calibration:** before relying on the suite, and after big config or model changes, grade 2–3 reference repos with hand-set expected scores. See [calibration/README.md](calibration/README.md).
- **Monorepos:** define `[[components]]` in `project.toml`, each with its own preset, answers and zones. The grader writes one report per component (`components/NAME.json`) plus a repo-level `report.json`; `gradekit rollup-repo` combines them. Repo-wide maturity is the lowest component's level.

## Versioning

See [CHANGELOG.md](CHANGELOG.md). Scores are comparable only between reports with the same **major** suite version.
