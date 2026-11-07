# Code Grading Suite v3.1.0

A kit for having AI agents grade a codebase from 1 to 10 on **35 benchmarks** (29 core in 6 pillars, plus 6 that apply only to some projects), and then improve it against those grades. It is built so that **rising scores mean better code**, not just code tuned to the rubric.

## What's in the kit

```
code-grading-suite/
├── prompts/
│   ├── grader.md        Full audit prompt: process, rules, evidence, output format
│   ├── improver.md      Prompt for agents that improve the code against a report
│   └── pr-review.md     Quick mode for grading a single pull request
├── rubric/
│   ├── A-correctness-trust.md      A1–A5   correctness, security, robustness, idempotence, durability
│   ├── B-design-structure.md       B1–B6   architecture, modularity, structure, interfaces, flexibility, leanness
│   ├── C-code-health.md            C1–C4   readability, maintainability, consistency, tests
│   ├── D-value-fitness.md          D1–D4   features, gaps, practicality, intuitiveness
│   ├── E-adoption-experience.md    E1–E4   adopter friendliness, docs, dev experience, native tooling
│   ├── F-operations-delivery.md    F1–F6   deployability, CI/CD, observability, performance, portability, dependencies
│   ├── X-conditional.md            X1–X6   accessibility, API stability, concurrency, cost, compliance, agent-readiness
│   ├── weights.json                Source of truth for weights, targets, caps and maturity levels
│   └── weights.md                  Human-readable version of the same
├── schema/report.schema.json       JSON Schema every report must match
├── tools/gradekit.py               Validates reports, checks evidence, does all the arithmetic
├── tools/build_web.py              Builds the web version (static site agents can be pointed at)
├── DEPLOY.md                       How to host the web version on your server
├── calibration/                    Reference repos with expected scores, to catch grader drift
├── holdout/                        How to write hidden checks the improvers never see
├── dispositions/                   Human decisions: accepted findings and answers to decision questions
└── examples/                       A tiny sample repo and a complete example report
```

## Ground rules for whoever runs this

1. **Keep the suite outside the repo being graded**, read-only to improving agents. If an improver could edit the rubric, dispositions or hidden checks, it could game them.
2. **The grader is independent.** Use a fresh agent with no memory of the improvement work for every grading run, and ideally a different model from the improver. Give it only the repo, the suite and the previous *shared* report. Never give it the improver's notes or reasoning.
3. **Sandbox the grader.** It runs the repo's own scripts. Give it a throwaway environment with no production credentials or secrets, and network access only to package registries.
4. **Hidden checks stay hidden.** Improvers only ever see the redacted report (`gradekit redact`).
5. **Humans own decisions.** Improvers carry out an action marked `requires_human_decision` only after you approve it in `decisions.json`. Findings you deliberately accept go in `dispositions.json`.
6. **Use gradekit's numbers.** Pillar scores, the overall score, targets and maturity always come from `gradekit rollup`, never from the grader's own arithmetic.

## The loop

```
          ┌───────────────────────────────────────────────────────────────┐
          ▼                                                               │
  1. Grade (3 independent runs) ──► 2. Check ──► 3. Consensus ──► 4. Redact & share
                                                                          │
  7. PR quick mode on each change ◄── 6. Improve ◄── 5. Humans decide ◄───┘
```

**1. Grade.** Run `prompts/grader.md` three times on the same commit, each in a fresh, sandboxed agent. Pass in the project context, `SUITE_DIR`, the commit SHA, the previous shared report (if any), the dispositions, and the hidden-check directory.

**2. Check each run:**
```bash
K="python3 SUITE_DIR/tools/gradekit.py"
$K validate run1.json                          # schema + rules (weights, IDs, caps, 10s need enforcement, leak check)
$K verify-evidence run1.json --repo REPO       # every code quote must exist at the cited lines
```
A run that fails either check gets sent back to its grader to fix, or thrown out.

**3. Consensus:**
```bash
$K stability run1.json run2.json run3.json --out report.json
```
This takes the median score for each benchmark, and a majority vote on applicability. Benchmarks whose scores spread by more than 1 point, or whose applicability split, are flagged as unstable. If the same benchmarks keep coming up unstable, their rubric wording is too vague: tighten it and bump the suite version. (A single run is fine for low-stakes use; skip this step.)

**4. Redact and share:**
```bash
$K redact report.json --out report.shared.json     # removes hidden-check details
```
Keep `report.json` private. Give `report.shared.json` (and the grader's `report.md`) to improvers and to the next grading run.

**5. Humans decide.** Answer the `decision_question`s in `dispositions/decisions.json`. Record any findings you accept as-is in `dispositions/dispositions.json`.

**6. Improve.** Run `prompts/improver.md` with the shared report and decisions. It works through cap-clearing actions first, then maturity blockers, then priorities, and stops at each benchmark's target.

**7. Guard every change.** Run `prompts/pr-review.md` on each pull request, then:
```bash
$K diff last-full-report.json pr-report.json --fail-on-regression   # exit 2 = block the merge
```
Then go back to step 1 for the next full audit. `diff` between full audits shows progress, fixed and regressed findings, and **divergence**: visible scores rising while hidden checks fall, which is the clearest sign of rubric-gaming.

## Key concepts

- **Applicability.** Every benchmark is classified `full`, `limited` (scored at weight 1, with a reason) or `not_applicable` (excluded, with a reason). The decision is based on the project's purpose, never on current quality.
- **Targets.** Choose `proportional` (default: 10 / 9 / 8 for weights 3 / 2 / 1), `maximal` (10 everywhere) or `level:L3` (just enough to reach a maturity level). You can also override individual benchmarks. Improvers stop at the target.
- **Maturity ladder.** L0 Not viable → L1 Prototype → L2 Usable → L3 Production-ready → L4 Exemplary. Each report names the exact scores blocking the next level.
- **Stable findings.** Findings get IDs like `A3-007` that persist across runs, with a status of new, open, fixed, regressed or accepted. Together the reports form a running backlog.
- **Metrics.** Raw measurements (coverage, vulnerability counts, complexity, setup re-run success, time to first success…) are recorded alongside the scores, so trends can be tracked without relying on grader consistency.
- **Integrity flags.** Text in the repo that tries to influence the grader caps maturity at L1 for that run.

## Calibration

Before relying on the suite, and after any rubric change, follow `calibration/README.md`: grade 2–3 reference repos whose expected scores you've set by hand, and confirm the grader lands within tolerance.

## Monorepos

List the components in the project context. The grader writes one report per component plus a `repo` report for shared concerns. Combine them with:
```bash
$K rollup-repo repo.json api.json web.json --out monorepo.json
```
The repo-wide overall score is weighted by component; repo-wide maturity is the lowest component's level.

## Try it

```bash
cd code-grading-suite
python3 tools/gradekit.py validate examples/sample-report.json
python3 tools/gradekit.py verify-evidence examples/sample-report.json --repo examples/sample-repo
python3 tools/gradekit.py rollup examples/sample-report.json
```

`gradekit.py` needs Python 3.9+ and uses only the standard library. If the `jsonschema` package is installed, it also runs full schema validation.

## Web version

To host the suite on a web server and point agents at a URL instead of handing them files, see `DEPLOY.md`. `python3 tools/build_web.py --out ../web` builds the site from this kit.

## Versioning

See `CHANGELOG.md`. Scores are comparable only between reports with the same **major** suite version.
