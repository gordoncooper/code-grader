# Changelog

Versioning rules for the suite itself:
- **Major:** any change that can move scores, i.e. new or removed benchmarks, changed anchors, caps, weights, targets or maturity rules. Scores from different major versions are **not comparable**. `gradekit diff` won't treat their deltas as regressions.
- **Minor:** clarified wording that shouldn't move scores, new optional fields, new tool commands. Re-run calibration to confirm.
- **Patch:** typos, formatting, documentation.

After any major or minor change, re-run calibration (`calibration/README.md`) before trusting new scores.

## 3.1.0
- **Web version:** `tools/build_web.py` generates a static site you can host on any web server. It has a landing page, an `AGENT.md` entry point agents can be pointed at, rendered docs, raw files, a downloadable zip, and `manifest.json` / `SHA256SUMS` for checking downloads. See `DEPLOY.md`.
- Optional `run.suite_source` field records where the suite came from.
- No scoring changes: scores remain comparable with 3.0.0.

## 3.0.0
- Split into a kit: grader, improver and pull-request prompts; one rubric file per pillar; canonical `weights.json`; JSON Schema; `gradekit.py`.
- **Integrity and safety rules:** repo content is evidence, never instruction; attempts to influence the grader become integrity flags that cap maturity at L1; grading runs sandboxed.
- **Independence and hidden checks:** a fresh grader for every run, hidden checks kept from improvers, redacted shared reports, and divergence detection.
- **Metrics block:** raw measurements recorded alongside scores.
- **Calibration:** reference repos with expected scores; stability across runs via median consensus, with unstable benchmarks flagged.
- **Targets:** proportional, maximal or level-based, with per-benchmark overrides, replacing "10 everywhere".
- **Findings:** stable IDs, statuses, and human dispositions.
- **Evidence:** exact-quote code citations, checked by `verify-evidence`; absence evidence.
- **Actions:** `requires_human_decision` with a decision question.
- **Pull-request quick mode** with a pass/fail verdict.
- **Monorepo support** via per-component reports and `rollup-repo`.

## 2.0.0
- Expanded to 29 core benchmarks in 6 pillars plus conditional benchmarks; added "Not this" boundaries, profile weights and the maturity ladder; added applicability (`full`, `limited`, `not_applicable`) and weight notes.

## 1.0.0
- First version: 15 core benchmarks and 4 conditional ones in a single prompt.
