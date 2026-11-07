# Changelog

Versioning rules for the suite itself:
- **Major:** any change that can move scores, i.e. new or removed benchmarks, changed anchors, caps, weights, targets or maturity rules. Scores from different major versions are **not comparable**. `gradekit diff` won't treat their deltas as regressions.
- **Minor:** clarified wording that shouldn't move scores, new optional fields, new tool commands. Re-run calibration to confirm.
- **Patch:** typos, formatting, documentation.

After any major or minor change, re-run calibration (`calibration/README.md`) before trusting new scores.

## 4.2.0
Scoring rules are unchanged; scores remain comparable with 4.x.
- **A central grading repo** replaces the `.grading/` folder inside code repos. Each project gets `projects/<name>/` with `project.toml`, `decisions.json`, `dispositions.json` and `reports/<date>-<commit>/` (one folder per report, never overwritten). Code repos stay untouched.
- **Decisions and accepted findings are separate files again** (`decisions.json`, `dispositions.json`), append-only.
- **Graders deliver by pull request by default** (branch `report/<project>/<date>-<commit>`; never to the default branch), or save locally, or return in chat. Decisions go on the report PR, or in a follow-up `decisions/<project>/<date>` PR.
- **Every prompt states the permissions** each delivery option needs.
- **Review a report** loads a whole project: from the grading repo (including a report PR, with deep links), a local folder, or a zip. It picks the latest and previous reports automatically, and lets you choose others.
- **Set up a project** adds the code repo, project name (defaulting to the repo's name) and subfolder for monorepos.
- **Start a run** asks for the grading repo and project name, and the improver can either read from the grading repo or be handed files.
- `gradekit`: `--project NAME` / `--project-dir`; `init --project`; `diff` defaults to the latest two reports; `scan_zip` for the website.
- Removed: `.grading/`, CODEOWNERS guidance, and the pull-request rule about grading files.

## 4.1.0
Scoring rules are unchanged, so scores remain comparable with 4.0.0. Config fingerprints changed: re-run `resolve` before validating older reports.
- **The website is now a set of tools:** **Set up a project**, **Start a run** and **Review a report** run `gradekit.py` in the browser via Pyodide. Nothing to install, and nothing uploaded. Plus a new **Getting started** tutorial with common setups.
- **One grading folder:** `.grading/` in the repo (or anywhere else) holds `project.toml` and the latest `report.json` / `report.md`. Graders read the previous report from there, and git history keeps the older ones.
- **Accepted findings and decisions moved into `project.toml`** as `[[dispositions]]` and `[[decisions]]`, replacing the separate JSON files. Decisions are matched to actions by ID and question text. Agent answers count only when `[review] allow_agent_decisions = true`.
- **Flexible delivery:** graders deliver by pull request, commit, saved files, or back in the chat. Every prompt starts with an inputs table with defaults. New **reviewer** prompt for agent reviewers.
- **Pull-request checks** read their baseline from the base commit, and fail improvement PRs that touch the grading folder.
- Hidden-check details stay next to the checks instead of in the report.
- `gradekit`: `init --grading-dir`; finds `.grading/project.toml` and `.grading/report.json` automatically; `verify-evidence` accepts a repo `.zip`; reusable library functions and a `web_api()` used by the website.
- The config fingerprint now covers only what affects scoring; project prose, dispositions and decisions are excluded.

## 4.0.0
Weights changed, so scores are **not comparable** with 3.x.
- **Everything tunable is now config:** `config/defaults.toml` (commented), layered with an optional org config and a per-project `project.toml`. Replaces `rubric/weights.json`; the benchmark list moved to `rubric/catalog.json`.
- **Weights from questions instead of fixed profile columns:** eight questions about the project (data sensitivity, audience, lifespan, failure impact, team, change rate, delivery, scale) adjust base weights. Presets supply typical answers; overrides need a written reason. `gradekit resolve --explain` shows the reasoning behind each weight.
- **Gates:** Correctness and Security always, plus benchmarks added by answers (e.g. handling money makes Idempotence and Durability gates). A failed gate caps the overall score; maturity levels set gate minimums (replacing "Pillar A minimum").
- **Criticality zones:** hot, normal and cold code. Findings get an effective severity shifted by zone. Maturity levels limit open findings by effective severity and zone, and hot-zone work ranks first.
- **Ranked priorities** computed by `gradekit rollup` (tiers, then weight × gain × zone ÷ effort), instead of being ranked by the grader.
- **New commands:** `init`, `resolve`, `presets`. Every command that scores takes `--config`. Reports record the config hash, and `validate` rejects a report checked against a different config.
- **Report changes:** `config` block replaces `profile` / `target_mode` / `target_overrides`; `config_weight` replaces `profile_weight`; findings may carry `paths`.
- Requires Python 3.11+ (built-in TOML reader).
- New `TUNING.md` and `config/project.example.toml`; `rubric/weights.md` now explains how scoring works.

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
