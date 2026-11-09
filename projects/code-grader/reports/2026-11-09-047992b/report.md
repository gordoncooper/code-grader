# Grading report: code-grader @ 047992b (2026-11-09)

*Graded by Claude Code (claude-opus-5-5) · 29.8 min · session `https://claude.ai/code/session_01CznWn91XgZCCBMGDL9PSqK`*

## Summary

Overall **7.0**, maturity **L2** (next: L3).

A careful, unusually self-checking kit: 709 tests pass (88% line and 79% branch coverage on the engine, the website tested in Chromium with zero axe violations), releases are signed and versioned, and the website is well hardened. The weakest places are in the hot zone that every grade depends on: a report can escape the open-critical score limit by leaving a finding off its benchmark's list, deliver can ship a stored rollup that no longer matches the scores, writes aren't atomic, and the 7,900-line engine is one untyped, lint-free module with extreme complexity hotspots. The grading-repo CI templates run whatever kit the website serves with write tokens, and this repo's own grading CI isn't installed. The grader prompt misstates 4.x/5.x score comparability, and scoring 5.0 shipped before passing its own calibration. Both gates sit at 7; see the rollup for the overall score and maturity.

## Gates and maturity

| Gate | Score | Status |
|---|:-:|---|
| A1 Correctness & Functional Behavior | 7 | passed (always) |
| A2 Security & Privacy | 7 | passed (always) |

Blocking L3: overall ≥ 8.0 (now 7.0); gate ≥ 8 (A1 now 7); gate ≥ 8 (A2 now 7); no benchmark < 6 (A5 now 4); no benchmark < 6 (B2 now 5); no benchmark < 6 (X5 now 5); no major must-have gaps (now 1); at most 0 open major findings in hot zones (A1-001, A1-002, A5-001, B2-001, C2-001, E2-001, X5-001 now 7)

## Scorecard

Gates are marked ★. Weight is the weight used, after applicability.

| ID | Benchmark | Score | Target | Weight | Confidence | Applicability | Notes |
|---|---|:-:|:-:|:-:|---|---|---|
| A1 ★ | Correctness & Functional Behavior | 7 | 10 | 3 | high | full | Tests pass and edge cases are deliberate, but two latent hot-zone defects let a report escape its limits or ship a stale rollup |
| A2 ★ | Security & Privacy | 7 | 10 | 3 | medium | full | No exploitable flaw found and the website is well hardened, but the CI templates run unpinned code with write tokens and inline branch names; no security scanning in CI |
| A3 | Robustness & Error Handling | 7 | 9 | 2 | high | full | Consistent error model with context and timeouts; a few uncaught config errors and one write-before-refuse path |
| A4 | Idempotence & Determinism | 8 | 9 | 2 | high | full | Scripts and mutations are safe to repeat and builds reproduce; the CI kit isn't pinned (A2-001), so runs aren't fully reproducible over time |
| A5 | Durability & Recoverability | 4 | 8 | 1 | high | limited | Committed history is append-only and CI-enforced, but every write in progress is non-atomic (A5-cap-1) |
| | **A Correctness & Trust** | **6.9** | | | | | |
| B1 | Architecture & Design Fitness | 7 | 9 | 2 | high | full | A clear, fitting shape (one engine behind CLI, MCP and website, pure core vs commands) with a few I/O leaks into the core |
| B2 | Modularity & Decoupling | 5 | 9 | 2 | high | full | Cohesive sections and testable pure functions, but one god module with shared global state for every concern |
| B3 | Structure & Organization | 8 | 8 | 1 | high | full | Predictable and documented; the generated bundle sits in the tree (by design, for Pages) and doubles every search |
| B4 | Interface Design & Contracts | 6 | 10 | 3 | high | full | Schema-checked formats and a careful CLI contract, but partial, unchecked typing inside a large hot-zone engine |
| B5 | Flexibility & Extensibility | 8 | 9 | 2 | medium | full | Most likely changes (weights, questions, presets, rules versions) are config-only; host support is hard-coded in a few places |
| B6 | Leanness | 7 | 9 | 2 | high | full | Tight for what it does, with a few leftovers and one duplicated code path |
| | **B Design & Structure** | **6.7** | | | | | |
| C1 | Readability & Clarity | 7 | 9 | 2 | high | full | Generally clear, intent-revealing code with why-comments; dense one-liners and very long functions take effort |
| C2 | Maintainability & Complexity | 6 | 10 | 3 | high | full | Small helpers and no debt markers, but the most-changed functions in the hot zone are extreme complexity hotspots |
| C3 | Consistency & Idiomatic Code | 7 | 8 | 1 | high | full | Uniform, idiomatic conventions by one author, but nothing enforces them (no formatter or linter) |
| C4 | Test Suite Quality | 8 | 10 | 3 | high | full | A large, specific, deterministic suite with 79% branch coverage on the engine, gated in CI; the release scripts are the gap |
| | **C Code Health** | **7.0** | | | | | |
| D1 | Feature Completeness | 7 | 9 | 2 | high | full | Nearly every claimed feature is complete and tested; the repo's own grading CI, which its README relies on, isn't installed |
| D2 | Gap Coverage | 6 | 9 | 2 | medium | full | Little a user would miss, except automated checking of evidence at merge time, which the suite's trust model leans on |
| D3 | Practicality | 7 | 9 | 2 | medium | full | Sensible, cheap-to-run choices with recorded trade-offs; the grading accuracy it exists for is not yet demonstrated by its calibration |
| D4 | Intuitiveness | 7 | 9 | 2 | high | full | Mostly obvious and self-explaining, with a couple of gotchas in setup and command naming |
| | **D Value & Fitness for Purpose** | **6.8** | | | | | |
| E1 | Adopter Friendliness | 8 | 10 | 3 | high | full | Smooth start within minutes on the CLI or the website; one placeholder step in the README quickstart |
| E2 | Documentation | 6 | 10 | 3 | high | full | Extensive, layered and mostly verified docs, but the grader prompt states the 4.x/5.x scoring comparability wrongly |
| E3 | Developer Experience & Inner Loop | 7 | 8 | 1 | high | full | Quick setup and clear test commands; a slow engine suite described as seconds, and no lint/format loop |
| E4 | Native Tooling & Ecosystem Fit | 6 | 8 | 1 | high | full | Standard test tooling, but no packaging, linter or formatter; custom build and release scripts are documented |
| | **E Adoption & Experience** | **6.9** | | | | | |
| F1 | Ease of Deployability | 8 | 9 | 2 | medium | full | Releases and the site publish themselves, signed and versioned; the release path itself isn't tested (C4-001) and rollback is by tag, untested |
| F2 | Build, CI/CD & Automation | 7 | 9 | 2 | medium | full | Tests, bundle sync and releases are automated; no lint, format, type or audit job (see C3-001, B4-001, F6-001), and merge blocking isn't visible from the repo |
| F3 | Observability & Debuggability | 7 | 8 | 1 | high | full | Clear errors, exit codes and machine-readable output; no debug mode for the unexpected |
| F4 | Performance, Efficiency & Scalability | 8 | 8 | 1 | medium | full | Efficient for its scale (sub-second commands); the test loop is slow from process start-up |
| F5 | Portability | 7 | 8 | 1 | medium | full | Works on the claimed runtime versions and avoids platform assumptions; the OS matrix is untested |
| F6 | Dependency Health & Longevity | 6 | 8 | 1 | high | full | Minimal and pinned, but stale with no automated updates or audit |
| | **F Operations & Delivery** | **7.2** | | | | | |
| X1 | Accessibility, UX & Internationalization | 8 | 9 | 2 | high | full | Accessible, responsive and tested in CI; English-only UI with no translation path |
| X2 | Public API Stability & Upgradeability | 9 | 10 | 3 | high | full | Semantic majors, pins, read-old/write-new formats, a migration command and compatibility tests; only doc slips remain (E2-001) |
| X3 | Concurrency Safety | 7 | 8 | 1 | medium | limited | The documented concurrent uses are serialised or separated; parallel edits to one report aren't guarded |
| X4 | Cost Efficiency | – | – | 0 | – | not_applicable | The code runs on free CI and static hosting and calls no paid API itself; the agent runs it organises are paid for by whoever starts them (it only records their cost). It would apply if gradekit called a paid model API |
| X5 | Compliance & Licensing | 5 | 9 | 2 | medium | full | Clear own license, but a published artifact redistributes third-party code without its notices; no SBOM |
| X6 | Agent-Readiness | 7 | 8 | 1 | high | full | An agent can verify a change with documented commands and machine-readable output; repo-specific rules aren't collected for agents |
| | **X Conditional** | **7.4** | | | | | |
| | **Overall** | **7.0** | | | | | |

## Applicability and weight notes

- **A5** limited: gradekit runs no service and keeps no database: what it writes (reports, decisions, settings) is committed to git, so only a report being written between commands, and files not yet committed, must survive a crash. It would fully apply if gradekit kept state of its own
- **X3** limited: gradekit itself is single-threaded, but its documented use has several graders, CI jobs and people writing to one grading repo at once; it would fully apply if the tool ran work in parallel itself
- **X4** not applicable: The code runs on free CI and static hosting and calls no paid API itself; the agent runs it organises are paid for by whoever starts them (it only records their cost). It would apply if gradekit called a paid model API

## Top priorities

1. **E2-act-1** (tier 1, hot zone, +2, effort S): Fix prompts/grader.md Part 7 and source/README.md line 75 to say 5.x scores with scoring version 5.0.0 and 4.x reports are compared as notes only; fix the schema list in source/README.md; add a test that greps the prompts and READMEs for the scoring version and compares it with config/defaults.toml
2. **X5-act-1** (tier 1, hot zone, +3, effort S): Make vendor_pyodide.py also copy Pyodide's LICENSE and a THIRD-PARTY-NOTICES file (Pyodide MPL-2.0 with a source link, the PSF license for the stdlib, each lock-file package's license) into SITE_DIR/pyodide/, and list them in DEPLOY.md — **decision pending:** Add third-party license notices to the website-with-Pyodide release zip (a licensing change to a published artifact)?
3. **A5-act-1** (tier 1, hot zone, +4, effort S): Make write_json and every write_text in gradekit.py write to a temp file in the same folder, fsync, then os.replace onto the target (one helper, used everywhere); add a test that simulates an interrupted write and checks the old file is intact
4. **A1-act-1** (tier 1, hot zone, +1, effort S): In score_limits (source/tools/gradekit.py), find each benchmark's open critical findings by benchmark_id, not by finding_ids; and make validate_report error (not warn) when an open finding is listed under no benchmark or under another benchmark. Add a test that edits finding_ids by hand and expects validate to fail
5. **A1-act-2** (tier 1, hot zone, +1, effort S): In prepare_delivery always call apply_rollup (or refuse when the stored rollup differs from compute_rollup), and make report check compare the stored rollup's overall, level and priorities with a fresh one; test that a score edited after check --write is caught
6. **A2-act-3** (tier 1, hot zone, +1, effort S): In the decide job, skip ticks whose sender is the pull request's author (github.event.sender.login == github.event.pull_request.user.login), and say so in the comment; or record such answers with decided_by 'agent:LOGIN' — **decision pending:** Stop counting the report PR's author (the grader) as a person who can approve its own decision questions?
7. **C2-act-1** (tier 1, hot zone, +2, effort M): Split validate_report into per-area checks (schema, benchmarks, findings, actions, holdout, publishing) that each return errors and warnings; do the same for resolve_layers (answers, weights, gates, zones, settings) and ci_check (report, settings, index); add 'radon cc --min D' (or ruff's C901 with a threshold) to CI
8. **B2-act-1** (tier 1, hot zone, +3, effort L): Split source/tools/gradekit.py into a package (gradekit/config.py, validate.py, rollup.py, authoring.py, deliver.py, ci.py, guard.py, render.py, mcp.py, webapi.py) with gradekit.py as a thin entry point; update engine.js SUITE_FILES and build_web.py to ship the package to Pyodide; replace PENDING_NOTES and args side channels with return values — **decision pending:** Restructure gradekit.py into a package of modules (the single-file kit and the website's file list change)?
9. **A2-act-1** (tier 1, normal zone, +1, effort M): Pin the kit in source/ci/github-grading.yml and gitlab-grading.yml: put the kit version and its zip's sha256 in the template (written by gradekit init --ci, updated by a migrate-like command), and have fetch-kit.py take the expected hash as an argument instead of reading it from the site's manifest — **decision pending:** Pin the grading CI to an exact kit version and hash (so users upgrade it deliberately), instead of following the website's latest?
10. **A1-act-3** (tier 1, hot zone, +0, effort S): Round with decimal.Decimal(...).quantize(Decimal('0.1'), ROUND_HALF_UP) in weighted() and repo_rollup, and compare maturity thresholds against the unrounded mean; add boundary tests (6.25, 6.45, 7.95) — **decision pending:** Rounding .x5 overall scores half-up can move a project across a maturity threshold; approve the change (it alters some existing rollups)?

## Decisions needed

- [ ] **X5-act-1:** Add third-party license notices to the website-with-Pyodide release zip (a licensing change to a published artifact)?
- [ ] **A2-act-3:** Stop counting the report PR's author (the grader) as a person who can approve its own decision questions?
- [ ] **B2-act-1:** Restructure gradekit.py into a package of modules (the single-file kit and the website's file list change)?
- [ ] **A2-act-1:** Pin the grading CI to an exact kit version and hash (so users upgrade it deliberately), instead of following the website's latest?
- [ ] **A1-act-3:** Rounding .x5 overall scores half-up can move a project across a maturity threshold; approve the change (it alters some existing rollups)?
- [ ] **D4-act-1:** Change what init writes to project.toml (preset answers as comments instead of explicit answers)?
- [ ] **D1-act-1:** Install the grading CI workflow in this repository's .github/workflows (it gets contents: write on the decide and index jobs)?
- [ ] **D2-act-1:** Let the grading CI read each project's code repo (with a read token for private code) to verify citations?
- [ ] **D3-act-1:** Make passing calibration a release gate for any change to the scoring rules?
- [ ] **E4-act-1:** Publish gradekit as a Python package with a 'gradekit' command, alongside the single-file kit?

Answers go in `decisions.json`: tick the boxes in this report's pull request (the grading CI records them), run `gradekit decide --approve ID --by NAME`, or use the suite website's *Review a report* page.

## Metrics

| Metric | Value | Note |
|---|---|---|
| build_passes | yes |  |
| tests_total | 709 | 391 engine/CLI tests (pytest -m 'not browser') + 318 browser tests (317 passed, 1 skipped: the screenshot comparison, which only runs on CI's platform) |
| tests_failed | 0 |  |
| tests_skipped | 1 |  |
| flaky_tests_detected | 0 | the engine suite ran twice (with and without subprocess coverage): 391 passed both times; the browser suite ran once |
| line_coverage_pct | 87.3 | Python only (source/tools and .github/scripts), coverage.py 7.17 with patch = subprocess so the CLI tests' child processes count; the website's JavaScript was not measured |
| branch_coverage_pct | 78.9 | as line_coverage_pct; without subprocess tracing the same run reports 41% for gradekit.py, because most CLI tests run it as a child process |
| core_branch_coverage_pct | 79.4 | source/tools/gradekit.py, the scoring and report engine (88.0% lines) |
| mutation_score_pct | – | no mutation tool was run |
| lint_errors | 236 | ruff 0.17.4 check --isolated (its defaults) over source/tools, .github/scripts and tests: no linter is configured or run in CI or named in contributor docs. 62 of the 236 are in gradekit.py; pyflakes-class (F) findings: 61, 48 of them F811 in tests |
| lint_warnings | 0 | ruff reports no separate warning level |
| lint_suppressions | 12 | '# noqa' comments in source/tools, .github/scripts and tests (gradekit.py 3, each with a reason) |
| type_errors_strict | 616 | mypy 2.4.1 --strict on source/tools/gradekit.py; at default settings mypy reports 89 errors across gradekit.py, build_web.py and two .github scripts |
| type_escape_hatches | 4 | '# type: ignore' comments (all on optional imports in gradekit.py); no typing.Any or cast() |
| vulns_critical | 0 | runtime: none (gradekit is standard library only; the website's Pyodide is pinned by hash). Dev-only: pip-audit finds 39 advisories, all in the test pin pillow 12.3.0 (fix 13.0.0), without severity ratings |
| vulns_high | 0 |  |
| vulns_medium | 0 |  |
| vulns_low | 0 |  |
| secrets_found | 0 | grep for AWS keys, GitHub tokens, Slack tokens and private-key headers across the checkout: none |
| deps_direct | 0 | runtime dependencies: none (jsonschema optional). Test and build pins: 5 distinct packages (pytest, playwright, jsonschema, markdown-it-py, pillow) |
| deps_transitive | 0 | runtime: none |
| deps_outdated_major | – | not checked with an outdated tool; pip-audit shows pillow's fix is in 13.0.0, one major ahead |
| deps_unused | – | no unused-dependency tool run |
| loc_source | 7645 | radon raw SLOC of the Python in source/tools and .github/scripts (gradekit.py, build_web.py, vendor_pyodide.py, bundles.py, site_versions.py, visual_baselines.py) |
| loc_source_js | 2914 | non-blank, non-comment lines of source/tools/web/*.js (grep -cv '^\s*(//\|$)') |
| loc_tests | 4766 | radon raw SLOC of tests/*.py |
| complexity_p95 | 37 | radon cc over the Python tools, 367 functions and methods including nested ones |
| complexity_max | 150 | validate_report in gradekit.py |
| duplication_pct | – | no duplication tool run |
| functions_over_50_lines | 29 | from radon's line spans, nested functions included |
| dependency_cycles | 0 | the engine is one module with no local imports; the scripts import only the standard library (bundles.py imports nothing local) |
| todo_fixme_count | 0 |  |
| dead_code_items | 7 | vulture --min-confidence 60 on gradekit.py: 7 candidates, 2 of them false positives (InOrder is used by name in the parser; web_api is called from engine.js) |
| artifact_size_bytes | 445175 | bundle/web/downloads/code-grading-suite-5.0.0.zip, the kit download |
| ci_duration_seconds | – | CI runs aren't visible from the sandbox (gh can only use the REST API here, and wasn't asked to read Actions) |
| setup_second_run_passes | yes | the build (bundles.py build) run twice gives identical output; gradekit init run again refuses to overwrite without --force, by design |
| time_to_first_success_minutes | 0.02 | the README's init + resolve from a fresh clone took about 1 s |
| time_to_first_test_minutes | – | pip install time wasn't measured on its own; the engine suite itself takes 4.3 minutes |
| quickstart_steps | 2 | README.md 'Using the kit': init and resolve; the third line needs a report that doesn't exist yet |

## Findings

| ID | Severity | Zone | Status | Title |
|---|---|---|---|---|
| A1-001 | major | hot | new | The open-critical limit (max 5) is checked through finding_ids, so a report that leaves a critical finding off its benchmark's list escapes it |
| A1-002 | major | hot | new | deliver keeps a stored rollup that no longer matches the scores, so report.json and report.md disagree |
| A1-003 | minor | hot | new | Overall and pillar scores round .x5 means inconsistently (6.25 → 6.2 but 6.45 → 6.5), and maturity thresholds compare the rounded value |
| A2-001 | major | normal | new | The grading-repo CI templates download and run whatever kit the website serves at run time, checked only against a hash from that same website, in jobs that hold write tokens |
| A2-002 | minor | hot | new | Workflows interpolate the pull request's branch name (github.head_ref) straight into shell scripts |
| A2-003 | minor | hot | new | The decide job records ticks by the pull request's author, usually the grader's own account, as a person's decision |
| A3-001 | minor | hot | new | A non-numeric weight or target in project.toml crashes resolve with a Python traceback instead of a configuration error |
| A3-002 | minor | hot | new | deliver redacts and rewrites a runs/ file before refusing it, so a refused delivery still changes files |
| A3-003 | minor | hot | new | git calls in the grading CI path (file_at) have no timeout, unlike the rest of the tool |
| A5-001 | major | hot | new | Every write truncates the file in place: a crash or kill mid-write leaves an unparseable report.json, losing the report being written |
| B1-001 | minor | hot | new | The computing core reaches for disk and stdout: rollup, diff and consensus reload the catalog from disk, and load_config prints notes |
| B2-001 | major | hot | new | One 7,900-line module holds every concern (config, validation, rollup, authoring, delivery, CI, guard, MCP, rendering, web API), sharing a global notes list and an args namespace used as a side channel |
| B4-001 | major | normal | new | The engine's internal contracts are untyped in places and nothing checks them: mypy finds 89 errors at default settings and 616 at strict, and no type checker runs in CI |
| B5-001 | minor | hot | new | Adding a third code host means edits in several hard-coded places |
| B6-001 | minor | hot | new | Leftover dead code: unused helpers and constants, a no-op branch, and a second copy of the repo-rollup arithmetic |
| C1-001 | minor | hot | new | Dense, clever one-liners and very long lines in the engine: side effects inside comprehensions, 90 lines over 140 characters |
| C2-001 | major | hot | new | Complexity is concentrated in the hot core: validate_report (cyclomatic 150, 209 lines), resolve_layers (102), ci_check (99), render_report_md (95), compute_rollup (85) |
| C3-001 | minor | hot | new | No formatter or linter is configured or run: 47 of 48 Python files would be reformatted, and ruff reports 236 findings at its defaults |
| C4-001 | major | normal | new | The release path in the hot zone is barely tested: bundles.py's version and sync rules are 33% covered and release.sh has no test |
| C4-002 | minor | normal | new | Tests didn't catch two hot-zone defects of the kind they're written for (a limit escaped by editing finding_ids, a stale rollup delivered) |
| D1-001 | major | normal | new | This repo presents itself as a grading repo whose CI records ticked decisions, but it has no grading workflow, so report pull requests here are neither checked nor answered by ticking |
| D3-001 | major | normal | new | Scoring 5.0 shipped before passing its own calibration: one golden repo, 1 of the 3 runs it requires |
| D4-001 | minor | hot | new | init writes every preset answer into [answers], so the preset line it also writes stops doing anything: changing it later moves no weight |
| D4-002 | minor | hot | new | The tool's own messages say to run 'gradekit …', a command that doesn't exist; it's python3 SUITE_DIR/tools/gradekit.py |
| E1-001 | minor | normal | new | The README quickstart's third command validates a report that doesn't exist yet, with no pointer to how to get one |
| E2-001 | major | hot | new | The grader prompt and the kit README say 4.x and 5.x share scoring version 4.2.0, but 5.0 has its own scoring version (5.0.0) and the tools don't compare across it |
| E2-003 | minor | normal | new | The kit README's 'What's in the kit' lists one schema; the kit ships four (report formats 4 and 5, index, work order) |
| E3-001 | minor | normal | new | tests/README says the engine suite takes 'a few seconds'; it takes about four minutes, and there's no quicker subset documented |
| E3-002 | minor | normal | new | No contribution guide or task runner: lint, format and type commands don't exist, and the release rules are spread over README and bundles.py |
| E4-001 | minor | normal | new | No Python packaging: no pyproject.toml, no wheel or entry point, so gradekit is run by path and the ecosystem's tools have nothing to read |
| F3-001 | minor | hot | new | No verbose or debug mode: an unexpected error is either a one-line message or a raw traceback, with nothing in between |
| F5-001 | minor | hot | new | Only Linux is tested, though the CLI is offered to anyone with Python 3.11+ (and has Windows-specific code paths) |
| F6-001 | minor | hot | new | Pinned dependencies go stale unnoticed: the test pin pillow 12.3.0 carries 39 advisories, and nothing updates or audits dependencies or the third-party actions (pinned to mutable major tags) |
| X1-001 | minor | normal | new | UI text is hard-coded English in the page scripts, with no message catalogue for translation |
| X3-001 | minor | hot | new | Two commands editing the same report at once silently lose one edit (read, change, rewrite with no lock) |
| X5-001 | major | hot | new | The 'web with Pyodide' release zip redistributes Pyodide (MPL-2.0), CPython's standard library and Python packages with no license notices |
| X6-001 | minor | normal | new | No agent instructions for working on the kit itself (AGENTS.md or CLAUDE.md): build, test and release rules have to be pieced together from three READMEs |

## Feature inventory

| Feature | Claimed in | Status |
|---|---|---|
| Project setup from the command line (init, resolve, presets) | README.md, source/README.md | complete |
| Report checks: validate, verify-evidence, rollup, diff | source/README.md | complete |
| carry and report match (stable finding IDs across reports) | source/README.md | complete |
| deliver: pr, save or return | source/README.md | complete |
| Publishing safety: redact, sensitive findings, report.private.json | README.md | complete |
| guard snapshot/compare for improvers | source/README.md | complete |
| MCP server (every command as a tool) | source/README.md | complete |
| Monorepo components and rollup-repo | source/README.md | complete |
| migrate a project from 4.x to 5 | source/README.md | complete |
| Work orders, due and scheduled grading | source/README.md, GETTING-STARTED.md | complete |
| Calibration program (golden repos, repeated runs, published results) | source/README.md, CHANGELOG 5.0.0 | partial |
| Hidden checks | prompts/grader.md Part 1 rule 5, holdout/README.md | partial |
| Ticking decision boxes on a report PR in this repo (the grading CI records them) | README.md (The cycle, step 2) | broken |
| Report authoring for graders (report new/finding/score/strength/action/check) | source/README.md, prompts/cards/grader.md | complete |
| Grading-repo CI: gradekit ci, decide-by-ticking, index, schedule (GitHub and GitLab templates) | source/ci/README.md | complete |
| Disputes (people dispute a finding; the next grader answers) | source/README.md | complete |
| Website: Set up a project, Start a run, Review a report, Projects (gradekit in the browser via Pyodide) | README.md (Website) | complete |

## Gap register

| ID | Gap | Severity | Necessity | Status | Benchmarks |
|---|---|---|---|---|---|
| GAP-001 | The grading CI checks a report's shape and rollup but never checks its code citations against the code, so a fabricated quote merges unless a person loads the code's zip on the Review page | major | must-have | new | D2 |
| GAP-002 | No --version on the CLI (the version shows only through doctor or the catalog) | minor | nice-to-have | new | D2 |

## Benchmark detail

### A1 Correctness & Functional Behavior: 7 (target 10)

Why: Tests pass and edge cases are deliberate, but two latent hot-zone defects let a report escape its limits or ship a stale rollup

- Strength: The whole engine suite passes (391 tests), and the bundled example validates, rolls up and verifies all 23 citations (ran `TMPDIR=SCRATCH COVERAGE_FILE=SCRATCH/.coverage python -m coverage run --branch --source=source/tools,.github/scripts -m pytest tests -m "not browser" -q -p no:cacheprovider`; ran `python .github/scripts/bundles.py status; python .github/scripts/bundles.py sync --check; python .github/scripts/bundles.py smoke`)
- Strength: Score limits are enforced when they are written, not just reported: report score refuses a score above a cap or an open critical finding (`source/tools/gradekit.py:2925-2927`; ran `bash SCRATCH/scripts/probe_unlinked_critical.sh`)
- Strength: Earlier scoring rules ship as data, so 4.x reports recompute exactly as graded instead of being silently re-scored (`source/tools/gradekit.py:321-322`)
- Finding A1-001 (major, new): The open-critical limit (max 5) is checked through finding_ids, so a report that leaves a critical finding off its benchmark's list escapes it (`source/tools/gradekit.py:1143-1144`: score_limits counts only the IDs listed in the benchmark's finding_ids, not the findings whose benchmark_id it is; `source/tools/gradekit.py:875-877`: a finding listed nowhere is only a warning, so validate (and gradekit ci, which runs it) passes the report; ran `bash SCRATCH/scripts/probe_unlinked_critical.sh`: C4 scored 8 with an open critical C4 finding: no limit error after the ID was dropped from finding_ids)
- Finding A1-002 (major, new): deliver keeps a stored rollup that no longer matches the scores, so report.json and report.md disagree (`source/tools/gradekit.py:4012-4013`: the rollup is recomputed only when missing or the config changed; a score changed after report check --write is not caught, and report check itself never compares the stored rollup; ran `bash SCRATCH/scripts/probe_stale_rollup.sh`; ran `bash SCRATCH/scripts/probe_stale_rollup.sh`: report.md (rendered fresh) says 5.0 L1 while report.json stores 4.9 L0; only the grading CI, where installed, would catch it)
- Finding A1-003 (minor, new): Overall and pillar scores round .x5 means inconsistently (6.25 → 6.2 but 6.45 → 6.5), and maturity thresholds compare the rounded value (`source/tools/gradekit.py:1094-1096`: round() on a float: half-even for exactly representable values, float-repr-dependent otherwise; ran `python3 -I SCRATCH/scripts/probe_rounding.py`: 7.95 meets L3's overall_min 8.0; 8.25 becomes 8.2)
- Enforced by: CI runs the engine tests on Python 3.11, 3.12 and 3.13 for every pull request touching source/ or tests/ (`.github/workflows/tests.yml:33-34`; `.github/workflows/tests.yml:39-40`)
- Next: **A1-act-1** → 8 (effort S): In score_limits (source/tools/gradekit.py), find each benchmark's open critical findings by benchmark_id, not by finding_ids; and make validate_report error (not warn) when an open finding is listed under no benchmark or under another benchmark. Add a test that edits finding_ids by hand and expects validate to fail
- Next: **A1-act-2** → 9 (effort S): In prepare_delivery always call apply_rollup (or refuse when the stored rollup differs from compute_rollup), and make report check compare the stored rollup's overall, level and priorities with a fresh one; test that a score edited after check --write is caught
- Next: **A1-act-3** → 9 (effort S): Round with decimal.Decimal(...).quantize(Decimal('0.1'), ROUND_HALF_UP) in weighted() and repo_rollup, and compare maturity thresholds against the unrounded mean; add boundary tests (6.25, 6.45, 7.95) *(needs a decision)*

### A2 Security & Privacy: 7 (target 10)

Why: No exploitable flaw found and the website is well hardened, but the CI templates run unpinned code with write tokens and inline branch names; no security scanning in CI

- Strength: The website builds every element with textContent (no innerHTML anywhere) under a strict content-security policy with no unsafe-inline or eval (`source/tools/web/common.js:4-5`; `source/tools/build_web.py:163`)
- Strength: Pyodide is pinned to one release with SRI hashes, and every package it loads later is checked against its hash-pinned lock file (`source/tools/web/engine-config.js:22-23`; `source/tools/web/engine.js:65-67`)
- Strength: Untrusted input is kept away from paths and shells: citations can't escape the repo, archives are checked for unsafe paths, and the PR body reaches the shell only through an env var (`source/tools/gradekit.py:988-990`; `source/ci/fetch-kit.py:27-29`; `source/ci/github-grading.yml:122-123`)
- Strength: Security findings are withheld from public reports by design, with leak detection that refuses to publish withheld text found elsewhere (`source/tools/gradekit.py:1833-1835`)
- Finding A2-001 (major, new): The grading-repo CI templates download and run whatever kit the website serves at run time, checked only against a hash from that same website, in jobs that hold write tokens (`source/ci/github-grading.yml:60-61`: every job (check, decide, index, schedule) curls fetch-kit.py and runs it; nothing pins a version or a hash in the workflow; `source/ci/fetch-kit.py:21-23`: the manifest that carries the expected sha256 comes from the same site as the zip, so it can't catch a changed or compromised site, only a torn download; `source/ci/github-grading.yml:187-189`: the schedule job also exposes CODE_READ_TOKEN; decide, index and schedule run with contents: write)
- Finding A2-002 (minor, new): Workflows interpolate the pull request's branch name (github.head_ref) straight into shell scripts (`source/ci/github-grading.yml:69`: the template passes the PR body through an env var for exactly this reason, but not the branch name; a fork PR's token is read-only and same-repo branches need write access, so reach is limited; `source/ci/github-grading.yml:133-134`: the template passes the PR body through an env var for exactly this reason, but not the branch name; a fork PR's token is read-only and same-repo branches need write access, so reach is limited; `.github/workflows/tests.yml:68`: the template passes the PR body through an env var for exactly this reason, but not the branch name; a fork PR's token is read-only and same-repo branches need write access, so reach is limited)
- Finding A2-003 (minor, new): The decide job records ticks by the pull request's author, usually the grader's own account, as a person's decision (`source/ci/github-grading.yml:17-18`: documented: the PR author can tick, and the job runs for anyone but GitHub's Bot type; `source/tools/gradekit.py:1383`: the only agent check is a decided_by that starts with 'agent', which a GitHub login never does; a reviewer still sees the commit before merging)
- Enforced by: Browser tests (run in CI) load every page and state under the enforced content-security policy, and refuse Pyodide files that don't match their pins (`tests/README.md:13`; `.github/workflows/tests.yml:82-83`)
- Next: **A2-act-1** → 8 (effort M): Pin the kit in source/ci/github-grading.yml and gitlab-grading.yml: put the kit version and its zip's sha256 in the template (written by gradekit init --ci, updated by a migrate-like command), and have fetch-kit.py take the expected hash as an argument instead of reading it from the site's manifest *(needs a decision)*
- Next: **A2-act-2** → 8 (effort S): Pass github.head_ref (and pull_request.head.ref in .github/workflows/tests.yml) through env: variables and quote them in the scripts, as the decide job already does for the PR body
- Next: **A2-act-3** → 9 (effort S): In the decide job, skip ticks whose sender is the pull request's author (github.event.sender.login == github.event.pull_request.user.login), and say so in the comment; or record such answers with decided_by 'agent:LOGIN' *(needs a decision)*
- Next: **A2-act-4** → 9 (effort S): Add a security job to .github/workflows/tests.yml: pip-audit on tests/requirements.txt and actionlint/zizmor on .github/workflows and source/ci, failing the build on findings

### A3 Robustness & Error Handling: 7 (target 9)

Why: Consistent error model with context and timeouts; a few uncaught config errors and one write-before-refuse path

- Strength: One error model: every user-facing failure is a GradekitError with a message saying what to do, and a failed command says that nothing was saved (`source/tools/gradekit.py:111-113`)
- Strength: External calls are bounded: subprocesses and downloads carry timeouts, and a check that times out is reported as such (`source/tools/gradekit.py:3755-3757`; `source/tools/gradekit.py:3896`)
- Strength: The browser API turns any bad input into a structured error instead of a crash (`source/tools/gradekit.py:7233-7234`)
- Finding A3-001 (minor, new): A non-numeric weight or target in project.toml crashes resolve with a Python traceback instead of a configuration error (`source/tools/gradekit.py:424`: int() on config values; only GradekitError is caught by the CLI; `source/tools/gradekit.py:1089`: int() on config values; only GradekitError is caught by the CLI; ran `bash SCRATCH/scripts/probe_bad_override.sh`: int() on config values; only GradekitError is caught by the CLI)
- Finding A3-002 (minor, new): deliver redacts and rewrites a runs/ file before refusing it, so a refused delivery still changes files (`source/tools/gradekit.py:4087-4089`: prepare_delivery (which writes report.json, report.private.json and report.md) runs before this runs/ check)
- Finding A3-003 (minor, new): git calls in the grading CI path (file_at) have no timeout, unlike the rest of the tool (`source/tools/gradekit.py:5193`: every other subprocess and urlopen call is bounded (30-300 s))
- Next: **A3-act-1** → 8 (effort S): Validate numeric config values in resolve_layers and compute_targets (weights.overrides.*.weight, targets.overrides, targets.by_weight, limited_cap) and report them as configuration errors; add a timeout to file_at; move the runs/ check in cmd_deliver before prepare_delivery
- Next: **A3-act-2** → 9 (effort M): Add fault-injection tests for the CLI: unreadable files, a git that fails or hangs, a site that times out, each expecting a GradekitError message and no partial writes

### A4 Idempotence & Determinism: 8 (target 9)

Why: Scripts and mutations are safe to repeat and builds reproduce; the CI kit isn't pinned (A2-001), so runs aren't fully reproducible over time

- Strength: The build is deterministic: two builds from source/ give identical files, and bundle/ is rebuilt only by CI so zip bytes don't depend on a contributor's zlib (`.github/scripts/bundles.py:18-19`; ran `bash SCRATCH/scripts/build_twice.sh`)
- Strength: Repeated operations converge: decide skips answers already recorded, init refuses to overwrite, deliver resumes on its own branch, and the index has no timestamps so --check is exact (`source/tools/gradekit.py:5676-5677`; `source/tools/gradekit.py:4153-4154`; `source/tools/gradekit.py:4972-4974`)
- Strength: Time is injectable where it matters (--today, --date, --started), so schedule and decision logic is testable (`source/tools/gradekit.py:7719`; `source/tools/gradekit.py:5672`)
- Enforced by: Tests pin re-run behaviour, e.g. the same decision twice is recorded once (`tests/test_decide.py:61`)
- Next: **A4-act-1** → 9 (effort S): Once the CI kit is pinned (A2-act-1), record the kit version gradekit ci ran with in its comment, and add a test that runs bundles.py build twice and compares the trees (the smoke job builds once)

### A5 Durability & Recoverability: 4 (target 8)

Why: Committed history is append-only and CI-enforced, but every write in progress is non-atomic (A5-cap-1)

- Strength: History is append-only by design: each grade adds a report folder that's never rewritten, and decisions, dispositions and disputes only grow; the grading CI enforces both (`source/tools/gradekit.py:5162-5163`; `source/tools/gradekit.py:5225-5227`)
- Strength: migrate refuses to write anything if a migrated report's stored rollup would change (`source/tools/gradekit.py:4384-4385`)
- Finding A5-001 (major, new): Every write truncates the file in place: a crash or kill mid-write leaves an unparseable report.json, losing the report being written (`source/tools/gradekit.py:133-135`: write_json opens the target with 'w' and dumps into it; no temp file and rename; searched for atomic writes (temp file + os.replace) anywhere in gradekit.py (grep -n 'os.replace|rename(' source/tools/gradekit.py: no matches; 48 write_json/write_text calls): every report command rewrites the whole report, so a run of 100+ commands has 100+ chances; decisions.json and the index are written the same way)
- Limit: at most 4 while A5-cap-1: Important state written non-atomically or held only in memory (A5-001)
- Next: **A5-act-1** → 8 (effort S): Make write_json and every write_text in gradekit.py write to a temp file in the same folder, fsync, then os.replace onto the target (one helper, used everywhere); add a test that simulates an interrupted write and checks the old file is intact

### B1 Architecture & Design Fitness: 7 (target 9)

Why: A clear, fitting shape (one engine behind CLI, MCP and website, pure core vs commands) with a few I/O leaks into the core

- Strength: One engine for every surface: the CLI, the MCP server and the website all call the same functions (the site runs gradekit.py in Pyodide through web_api), so the browser can't drift from the command line (`source/tools/gradekit.py:44`; `source/tools/gradekit.py:7225-7227`)
- Strength: Pure computation (resolve, validate, rollup, diff, redact) is separate from the cmd_* functions that do I/O, and design decisions are recorded in the code and CHANGELOG (`source/tools/gradekit.py:164-166`)
- Finding B1-001 (minor, new): The computing core reaches for disk and stdout: rollup, diff and consensus reload the catalog from disk, and load_config prints notes (`source/tools/gradekit.py:1482`: the pure functions the website shares would be easier to test and reuse with the catalog passed in and notes returned; `source/tools/gradekit.py:636-637`: the pure functions the website shares would be easier to test and reuse with the catalog passed in and notes returned)
- Enforced by: A test checks that the website and the CLI use one engine (`tests/test_one_engine.py:1`)
- Next: **B1-act-1** → 8 (effort M): Pass the catalog into compute_consensus, compute_diff and resolve_layers instead of calling load_catalog() inside them, and have load_config return its 'note: using …' line instead of printing it
- Next: **B1-act-2** → 9 (effort S): Write a short ARCHITECTURE section (in source/README.md) with the module map once gradekit is split (B2-act-1): core, authoring, delivery, CI, guard, render, web API

### B2 Modularity & Decoupling: 5 (target 9)

Why: Cohesive sections and testable pure functions, but one god module with shared global state for every concern

- Strength: Inside the file, sections are cohesive and the pure functions take plain dicts, so they're testable alone (tests import the module and call them directly) (`tests/conftest.py:39-41`)
- Strength: No third-party dependencies at run time: the engine is standard library only, with jsonschema optional (`source/tools/gradekit.py:46`)
- Finding B2-001 (major, new): One 7,900-line module holds every concern (config, validation, rollup, authoring, delivery, CI, guard, MCP, rendering, web API), sharing a global notes list and an args namespace used as a side channel (`source/tools/gradekit.py:104`: PENDING_NOTES: module-level mutable state that commands and the MCP server share; `source/tools/gradekit.py:4010-4011`: results and exit codes travel back on args (_exit, _result, project_dir rewritten in authoring_config); ran `radon cc -s -a source/tools/gradekit.py`: all in source/tools/gradekit.py (7,889 lines, 429 KB), the hot zone; any change means loading and re-testing the whole file)
- Next: **B2-act-1** → 8 (effort L): Split source/tools/gradekit.py into a package (gradekit/config.py, validate.py, rollup.py, authoring.py, deliver.py, ci.py, guard.py, render.py, mcp.py, webapi.py) with gradekit.py as a thin entry point; update engine.js SUITE_FILES and build_web.py to ship the package to Pyodide; replace PENDING_NOTES and args side channels with return values *(needs a decision)*

### B3 Structure & Organization: 8 (target 8)

Why: Predictable and documented; the generated bundle sits in the tree (by design, for Pages) and doubles every search

- Strength: A predictable, documented layout: source/ is the kit, bundle/ is generated from it by CI, tests/ and .github/ are separate, and the README maps it (`README.md:40-42`)
- Strength: Repo hygiene: private reports, caches and fetched screenshot baselines are ignored, so they can't be committed (`.gitignore:10-11`; `.gitignore:13-14`)
- Enforced by: CI fails main if bundle/ doesn't match source/, so the generated copy can't drift (`.github/workflows/kit.yml:67-69`)
- Next: **B3-act-1** → 9 (effort S): Mark bundle/ as generated for tools (a .gitattributes with 'bundle/** linguist-generated' and a ripgrep/IDE ignore hint in README), so searches and reviews skip the copy

### B4 Interface Design & Contracts: 6 (target 10)

Why: Schema-checked formats and a careful CLI contract, but partial, unchecked typing inside a large hot-zone engine

- Strength: Every file format is a JSON Schema that validate checks (report formats 4 and 5, work orders, the index), and the schema says which fields gradekit writes (`source/tools/gradekit.py:727`)
- Strength: A deliberate CLI contract: one JSON envelope for every command, documented exit codes (64 for bad arguments, never confused with a regression), and argparse choices that reject bad values (`source/tools/gradekit.py:47-48`; `source/tools/gradekit.py:7865`)
- Strength: The MCP tool schemas are generated from the CLI's own arguments, so the two interfaces can't drift (`source/tools/gradekit.py:6771-6772`)
- Finding B4-001 (major, new): The engine's internal contracts are untyped in places and nothing checks them: mypy finds 89 errors at default settings and 616 at strict, and no type checker runs in CI (ran `mypy source/tools/gradekit.py .github/scripts/*.py source/tools/build_web.py source/tools/vendor_pyodide.py`: most are missing annotations, but 14 union-attr and 16 arg-type errors are real None/str confusions the code guards by hand; ran `mypy --strict source/tools/gradekit.py`: most are missing annotations, but 14 union-attr and 16 arg-type errors are real None/str confusions the code guards by hand; searched for a type checker in CI or a mypy/pyright config (read .github/workflows/*.yml; git ls-files | grep -E 'mypy|pyright|pyproject|setup.cfg': none): most are missing annotations, but 14 union-attr and 16 arg-type errors are real None/str confusions the code guards by hand)
- Enforced by: Tests validate reports, work orders and the index against their schemas (`tests/test_mcp_orders.py:152`)
- Next: **B4-act-1** → 8 (effort L): Annotate gradekit.py's public functions (start with resolve_layers, validate_report, compute_rollup, score_limits, redact_report) and add 'mypy source/tools/gradekit.py' to the engine job in .github/workflows/tests.yml, tightening to --strict per section as it's typed; use TypedDicts for the report and config shapes
- Next: **B4-act-2** → 9 (effort M): Run mypy --strict on the whole engine in CI with zero errors (after the split in B2-act-1)

### B5 Flexibility & Extensibility: 8 (target 9)

Why: Most likely changes (weights, questions, presets, rules versions) are config-only; host support is hard-coded in a few places

- Strength: What varies is data, not code: questions, presets, weights, gates, levels and targets live in defaults.toml, layered with org.toml and project.toml, and new questions need no code (`source/config/defaults.toml:100-101`; `source/config/defaults.toml:9-10`)
- Strength: Earlier scoring rules plug in as a file per major, so a rules change doesn't break old reports (`source/tools/gradekit.py:80-81`)
- Finding B5-001 (minor, new): Adding a third code host means edits in several hard-coded places (`source/tools/gradekit.py:4135-4136`: github/gitlab branches are spelled out in deliver, migrate, doctor and init; a third host touches each; `source/tools/gradekit.py:3952`: github/gitlab branches are spelled out in deliver, migrate, doctor and init; a third host touches each)
- Next: **B5-act-1** → 9 (effort S): Put the per-host commands (gh pr create / glab mr create, auth status, CI template path) in one table in gradekit.py used by deliver, migrate, doctor and install_ci

### B6 Leanness: 7 (target 9)

Why: Tight for what it does, with a few leftovers and one duplicated code path

- Strength: No runtime dependencies and a 434 KB kit; the website's only external runtime is one pinned Pyodide release (`source/tools/gradekit.py:46`)
- Finding B6-001 (minor, new): Leftover dead code: unused helpers and constants, a no-op branch, and a second copy of the repo-rollup arithmetic (`source/tools/gradekit.py:6757-6758`: if args.json: pass; `source/tools/gradekit.py:1966-1968`: cmd_rollup_repo's list mode re-implements repo_rollup() (and, unlike it, doesn't skip the repo report or default a None weight); ran `vulture source/tools/gradekit.py --min-confidence 60`)
- Next: **B6-act-1** → 9 (effort S): Delete _stripped, CYCLE, GUARD_LOWER, MIGRATE_REPORT_FILES and the 'if args.json: pass' branch; make cmd_rollup_repo's list mode call repo_rollup(); add 'vulture source/tools --min-confidence 80' to CI

### C1 Readability & Clarity: 7 (target 9)

Why: Generally clear, intent-revealing code with why-comments; dense one-liners and very long functions take effort

- Strength: Names say what things are, and comments explain why, often with the history behind a rule (`source/tools/gradekit.py:102-103`; `source/tools/gradekit.py:1596-1597`)
- Strength: Docstrings on nearly every function say what it returns in the domain's words (`source/tools/gradekit.py:3450-3452`)
- Finding C1-001 (minor, new): Dense, clever one-liners and very long lines in the engine: side effects inside comprehensions, 90 lines over 140 characters (`source/tools/gradekit.py:7132`: seen.add() inside a filter, relying on it returning None; `source/tools/gradekit.py:842`; `source/tools/gradekit.py:1440`: nested generator and conditional expressions on single lines)
- Next: **C1-act-1** → 8 (effort S): Unfold the densest expressions in gradekit.py (scan_layout's seen.add filter, print_rollup's zone line, the errors-or-warnings append) into plain loops, and wrap lines at 120 characters with ruff format (see C3-act-1)

### C2 Maintainability & Complexity: 6 (target 10)

Why: Small helpers and no debt markers, but the most-changed functions in the hot zone are extreme complexity hotspots

- Strength: No TODO/FIXME debt, and the rules a function applies are kept as named constants and data (`source/tools/gradekit.py:1102-1104`; searched for TODO, FIXME, XXX or HACK markers (grep -rnE 'TODO|FIXME|XXX|HACK' source/tools .github tests: 0))
- Finding C2-001 (major, new): Complexity is concentrated in the hot core: validate_report (cyclomatic 150, 209 lines), resolve_layers (102), ci_check (99), render_report_md (95), compute_rollup (85) (`source/tools/gradekit.py:721`: radon cc: max 150, p95 37 over 367 functions; 29 functions over 50 lines; gradekit.py is also the most-changed code file (29 commits); ran `radon cc -s -a source/tools/gradekit.py`: radon cc: max 150, p95 37 over 367 functions; 29 functions over 50 lines; gradekit.py is also the most-changed code file (29 commits))
- Next: **C2-act-1** → 8 (effort M): Split validate_report into per-area checks (schema, benchmarks, findings, actions, holdout, publishing) that each return errors and warnings; do the same for resolve_layers (answers, weights, gates, zones, settings) and ci_check (report, settings, index); add 'radon cc --min D' (or ruff's C901 with a threshold) to CI

### C3 Consistency & Idiomatic Code: 7 (target 8)

Why: Uniform, idiomatic conventions by one author, but nothing enforces them (no formatter or linter)

- Strength: One voice throughout: the same command shape (load_for_edit, change, save_edit, emit), the same error type, and the same message style in every command (`source/tools/gradekit.py:2948-2950`; `source/tools/gradekit.py:2952-2953`)
- Finding C3-001 (minor, new): No formatter or linter is configured or run: 47 of 48 Python files would be reformatted, and ruff reports 236 findings at its defaults (`source/tools/gradekit.py:7292`: e.g. statements joined with semicolons in the argument parser; ran `ruff format --check source/tools .github/scripts tests`: e.g. statements joined with semicolons in the argument parser; ran `ruff check --isolated source/tools .github/scripts tests`: e.g. statements joined with semicolons in the argument parser)
- Next: **C3-act-1** → 9 (effort S): Add a pyproject.toml with [tool.ruff] (line-length 120, a chosen rule set), run 'ruff format' once in its own PR, and add 'ruff check' and 'ruff format --check' to the engine job in .github/workflows/tests.yml

### C4 Test Suite Quality: 8 (target 10)

Why: A large, specific, deterministic suite with 79% branch coverage on the engine, gated in CI; the release scripts are the gap

- Strength: 709 tests, all passing: the engine and CLI (391) and the website in Chromium (317), including axe-core with zero violations, keyboard, the CSP and the real Pyodide engine (ran `TMPDIR=SCRATCH COVERAGE_FILE=SCRATCH/.coverage python -m coverage run --branch --source=source/tools,.github/scripts -m pytest tests -m "not browser" -q -p no:cacheprovider`; ran `TMPDIR=SCRATCH python -m pytest tests -m "browser" -q -p no:cacheprovider`)
- Strength: Tests read as a specification and assert exact behaviour (messages, files, exit codes); several pin earlier bugs and can be run against an older release to show they catch them (`tests/test_limits.py:77-78`; `tests/conftest.py:40-41`)
- Strength: With subprocesses traced, the engine is 88% line- and 79% branch-covered (ran `TMPDIR=SCRATCH COVERAGE_RCFILE=SCRATCH/covrc python -m coverage run -m pytest tests -m "not browser" -q -p no:cacheprovider; coverage combine; coverage report`)
- Finding C4-001 (major, new): The release path in the hot zone is barely tested: bundles.py's version and sync rules are 33% covered and release.sh has no test (ran `TMPDIR=SCRATCH COVERAGE_RCFILE=SCRATCH/covrc python -m coverage run -m pytest tests -m "not browser" -q -p no:cacheprovider; coverage combine; coverage report`; searched for tests of bundles.py state()/cmd_sync() (the rules for when bundle/ is rebuilt or a source change is refused) or of release.sh (DRY_RUN exists) (grep -ln 'release.sh|cmd_sync|sync(' tests/*.py: none; the coverage report's missing lines are bundles.py 54-186))
- Finding C4-002 (minor, new): Tests didn't catch two hot-zone defects of the kind they're written for (a limit escaped by editing finding_ids, a stale rollup delivered) (`tests/test_limits.py:77-78`: limits are tested through report score, never through validate on a hand-edited report; see A1-001 and A1-002)
- Enforced by: Both suites gate every PR touching source/, tests/ or .github/scripts (the engine on three Pythons, the website in Chromium) (`.github/workflows/tests.yml:6-7`; `.github/workflows/tests.yml:84-85`)
- Next: **C4-act-1** → 9 (effort M): Add tests/test_bundles.py: drive bundles.state() and cmd_sync() against a temp source/ + bundle/ (unreleased heading, released version unchanged, new release, hash mismatch), and run release.sh with DRY_RUN=1 and STAGE_DIR on a temp repo with a fake tag
- Next: **C4-act-2** → 10 (effort M): Add regression tests for A1-001 and A1-002 (validate a hand-edited report; deliver after a late score change), and run a mutation tool (mutmut) over score_limits, compute_rollup and redact_report once, keeping the survivors as tests

### D1 Feature Completeness: 7 (target 9)

Why: Nearly every claimed feature is complete and tested; the repo's own grading CI, which its README relies on, isn't installed

- Strength: Nearly everything claimed works end to end: every command the READMEs list ran or is covered by tests, and the four web tools pass their browser tests (ran `cd bundle/bare/examples/grading-repo && python3 ../../tools/gradekit.py rollup --project orders-api && python3 ../../tools/gradekit.py diff --project orders-api && python3 ../../tools/gradekit.py verify-evidence --project orders-api --repo ../sample-repo`; ran `TMPDIR=SCRATCH python -m pytest tests -m "browser" -q -p no:cacheprovider`)
- Strength: Unfinished parts are labelled as such rather than presented as done (hidden checks, calibration status) (`README.md:68`; `source/calibration/RESULTS.md:5`)
- Finding D1-001 (major, new): This repo presents itself as a grading repo whose CI records ticked decisions, but it has no grading workflow, so report pull requests here are neither checked nor answered by ticking (`README.md:3`: the workaround is gradekit decide; but nothing validates a report PR's rollup, folder or publishing safety before merge; `README.md:56`: the workaround is gradekit decide; but nothing validates a report PR's rollup, folder or publishing safety before merge; searched for a grading workflow (gradekit ci / decide / index) in .github/workflows (ls .github/workflows: kit.yml, pages.yml, release.yml, tests.yml; grep -l 'gradekit.py ci\|decide --from-checklist' .github/workflows/*: none): the workaround is gradekit decide; but nothing validates a report PR's rollup, folder or publishing safety before merge)
- Next: **D1-act-1** → 8 (effort S): Install the grading check in this repo: gradekit init --ci github --site https://gordoncooper.github.io/code-grader/ (writes .github/workflows/grading.yml), scoped to projects/** so kit PRs are unaffected; or, if reports aren't meant to land on main, change README.md's cycle to say where they go *(needs a decision)*

### D2 Gap Coverage: 6 (target 9)

Why: Little a user would miss, except automated checking of evidence at merge time, which the suite's trust model leans on

- Strength: Scope is documented and peers' norms are covered: help on every command, meaningful exit codes, machine-readable output, a preflight, and an MCP server for agents without a shell (`source/tools/gradekit.py:50-52`)
- Next: **D2-act-1** → 8 (effort M): Add --code DIR_OR_ZIP to gradekit ci (and a step in the CI templates that fetches the project's code_repo at run.commit with git, using CODE_READ_TOKEN for private code) so ci_check also runs verify_evidence and fails on missing quotes *(needs a decision)*
- Next: **D2-act-2** → 9 (effort S): Add 'gradekit --version' (prints the kit and scoring versions)

### D3 Practicality: 7 (target 9)

Why: Sensible, cheap-to-run choices with recorded trade-offs; the grading accuracy it exists for is not yet demonstrated by its calibration

- Strength: Grounded technology choices: standard-library Python, a static site that runs the same engine in the browser, and plain git repos as the database, so nothing needs a server (`source/tools/web/engine.js:1`; `source/README.md:15`)
- Strength: Trade-offs are written down where they're made, e.g. baselines kept on their own branch to stop the repo growing (`.github/scripts/visual_baselines.py:4-6`)
- Finding D3-001 (major, new): Scoring 5.0 shipped before passing its own calibration: one golden repo, 1 of the 3 runs it requires (`source/calibration/RESULTS.md:5`; `source/calibration/RESULTS.md:15`: one counted run on the only golden repo; `source/CHANGELOG.md:73`: the changelog promises no scoring change ships unmeasured; it was measured once, against expected scores the results call provisional)
- Next: **D3-act-1** → 9 (effort L): Before the next scoring release, run calibration to its own bar: at least 3 independent runs per golden repo and at least two golden repos of different kinds (e.g. a service and a CLI), with expected scores reviewed by a person; make bundles.py refuse a release whose scoring_fingerprint has calibration status other than pass *(needs a decision)*

### D4 Intuitiveness: 7 (target 9)

Why: Mostly obvious and self-explaining, with a couple of gotchas in setup and command naming

- Strength: Errors say exactly what to do next, often with the corrected command (this report was written with them) (`source/tools/gradekit.py:2524-2525`; `source/tools/gradekit.py:2649`)
- Strength: Commands share one shape and vocabulary (report new/finding/score/check, --project or --project-dir everywhere), and terms are defined once in a glossary the tool can look up (ran `gradekit rubric A3; gradekit glossary effective severity; gradekit mcp (initialize, tools/list, tools/call glossary); gradekit report score nonexist.json A1 --score 11`)
- Finding D4-001 (minor, new): init writes every preset answer into [answers], so the preset line it also writes stops doing anything: changing it later moves no weight (`source/tools/gradekit.py:2348`: all eight answers come out as '(project)', though the file's comment says answers override the preset; ran `git clone CODE qs/code-grader && cd qs/code-grader && python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api && python3 bundle/bare/tools/gradekit.py resolve --project orders-api && python3 bundle/bare/tools/gradekit.py validate projects/orders-api/reports/<date>-<commit>/report.json`: all eight answers come out as '(project)', though the file's comment says answers override the preset)
- Finding D4-002 (minor, new): The tool's own messages say to run 'gradekit …', a command that doesn't exist; it's python3 SUITE_DIR/tools/gradekit.py (`source/tools/gradekit.py:2392`; ran `git clone CODE qs/code-grader && cd qs/code-grader && python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api && python3 bundle/bare/tools/gradekit.py resolve --project orders-api && python3 bundle/bare/tools/gradekit.py validate projects/orders-api/reports/<date>-<commit>/report.json`)
- Next: **D4-act-1** → 8 (effort S): In cmd_init write only the answers given with --answer (and comment out the preset's, as hints), so the preset keeps working; and print commands as the user can run them (python3 <path to gradekit.py> …) or ship a 'gradekit' launcher *(needs a decision)*

### E1 Adopter Friendliness: 8 (target 10)

Why: Smooth start within minutes on the CLI or the website; one placeholder step in the README quickstart

- Strength: A quickstart that works in a second from a fresh clone, with nothing to install but Python, plus a bundled example grading repo and a guided tour on the website (`README.md:13`; ran `git clone CODE qs/code-grader && cd qs/code-grader && python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api && python3 bundle/bare/tools/gradekit.py resolve --project orders-api && python3 bundle/bare/tools/gradekit.py validate projects/orders-api/reports/<date>-<commit>/report.json`)
- Strength: Clear license, versioned releases with checksums and provenance, a version per major on the site, and a migration command between majors (`README.md:86`; `README.md:99`)
- Finding E1-001 (minor, new): The README quickstart's third command validates a report that doesn't exist yet, with no pointer to how to get one (`README.md:77`; ran `git clone CODE qs/code-grader && cd qs/code-grader && python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api && python3 bundle/bare/tools/gradekit.py resolve --project orders-api && python3 bundle/bare/tools/gradekit.py validate projects/orders-api/reports/<date>-<commit>/report.json`)
- Enforced by: CI's smoke test runs the bundled example's commands on every kit PR (`.github/scripts/bundles.py:128-130`)
- Next: **E1-act-1** → 9 (effort S): In README.md's 'Using the kit' block, replace the validate line with one that works as written (validate the bundled example: python3 bundle/bare/tools/gradekit.py validate --project-dir bundle/bare/examples/grading-repo/projects/orders-api), and add a test that runs every command in that block

### E2 Documentation: 6 (target 10)

Why: Extensive, layered and mostly verified docs, but the grader prompt states the 4.x/5.x scoring comparability wrongly

- Strength: Layered docs for every audience: a tutorial, a reference, tuning and hosting guides, a glossary, per-folder READMEs, a detailed changelog, and why-comments in the code (`source/README.md:5`; `source/README.md:148-150`)
- Strength: Docs that can be generated are: the glossary and rubric.json come from their sources, with a note saying where to edit (`source/GLOSSARY.md:5`)
- Finding E2-001 (major, new): The grader prompt and the kit README say 4.x and 5.x share scoring version 4.2.0, but 5.0 has its own scoring version (5.0.0) and the tools don't compare across it (`source/prompts/grader.md:368`: graders are told 4.x→5.x score deltas are comparable and to explain them; `source/README.md:75`: the same claim, contradicted by line 184 of the same file; `source/config/defaults.toml:28-30`: the code: 5.0.0 changed what severity means, and diff treats a different scoring major as not comparable)
- Finding E2-003 (minor, new): The kit README's 'What's in the kit' lists one schema; the kit ships four (report formats 4 and 5, index, work order) (`source/README.md:157`)
- Enforced by: Tests keep the generated docs and the rubric data in step with their sources (`tests/test_glossary.py:1`)
- Next: **E2-act-1** → 8 (effort S): Fix prompts/grader.md Part 7 and source/README.md line 75 to say 5.x scores with scoring version 5.0.0 and 4.x reports are compared as notes only; fix the schema list in source/README.md; add a test that greps the prompts and READMEs for the scoring version and compares it with config/defaults.toml

### E3 Developer Experience & Inner Loop: 7 (target 8)

Why: Quick setup and clear test commands; a slow engine suite described as seconds, and no lint/format loop

- Strength: Two documented commands set up and run everything, with markers to pick the engine or the browser suite, and a status/smoke script for the kit (`tests/README.md:29-31`; `README.md:95`)
- Strength: Tests can run against another copy of the engine (GRADEKIT=…) to prove a test catches the bug it pins (`tests/README.md:36`)
- Finding E3-001 (minor, new): tests/README says the engine suite takes 'a few seconds'; it takes about four minutes, and there's no quicker subset documented (`tests/README.md:32`; ran `TMPDIR=SCRATCH COVERAGE_FILE=SCRATCH/.coverage python -m coverage run --branch --source=source/tools,.github/scripts -m pytest tests -m "not browser" -q -p no:cacheprovider`)
- Finding E3-002 (minor, new): No contribution guide or task runner: lint, format and type commands don't exist, and the release rules are spread over README and bundles.py (searched for CONTRIBUTING.md, Makefile/justfile/noxfile or pyproject scripts (git ls-files | grep -iE 'contributing|makefile|justfile|noxfile|pyproject': none))
- Next: **E3-act-1** → 8 (effort S): Add a CONTRIBUTING section (or file) with the inner loop: one test (pytest tests/test_x.py -k name), the fast in-process subset, lint/format/type once added (C3-act-1, B4-act-1), and the release rules; correct the timing in tests/README.md; run most CLI tests in-process through gradekit.main(argv) (as the MCP server does) or with pytest-xdist, since each spawns an interpreter that parses the 430 KB module

### E4 Native Tooling & Ecosystem Fit: 6 (target 8)

Why: Standard test tooling, but no packaging, linter or formatter; custom build and release scripts are documented

- Strength: Standard tools where they matter: pytest with markers and fixtures, Playwright, pip requirements, GitHub Actions; the bespoke build and release scripts say why they exist (`tests/conftest.py:25-27`; `.github/scripts/bundles.py:2`)
- Finding E4-001 (minor, new): No Python packaging: no pyproject.toml, no wheel or entry point, so gradekit is run by path and the ecosystem's tools have nothing to read (`README.md:75`: every user runs python3 <path>/tools/gradekit.py; searched for pyproject.toml, setup.cfg or a console-script entry point (git ls-files | grep -E 'pyproject|setup\.(py|cfg)': none): every user runs python3 <path>/tools/gradekit.py)
- Next: **E4-act-1** → 8 (effort M): Add a pyproject.toml declaring the tool (requires-python >=3.11, an optional [jsonschema] extra, a 'gradekit' console script pointing at tools/gradekit.py:main, and the ruff/mypy settings), keeping the single-file download working *(needs a decision)*

### F1 Ease of Deployability: 8 (target 9)

Why: Releases and the site publish themselves, signed and versioned; the release path itself isn't tested (C4-001) and rollback is by tag, untested

- Strength: Release and publishing are automatic: merging a release PR tags it, builds the zips with SHA256SUMS, signs them with build provenance and publishes the release; the site deploys from main (`.github/workflows/release.yml:53-55`; `.github/scripts/release.sh:129-131`)
- Strength: Every major stays installable at its own site path, each copy checked against its checksums before it's published, so a project pinned to an older major isn't broken by a release (`.github/scripts/site_versions.py:7-9`; `.github/scripts/site_versions.py:14`)
- Strength: Hosting elsewhere is documented, including a website zip with Pyodide inside for air-gapped hosts (`.github/scripts/release.sh:81-83`)
- Next: **F1-act-1** → 9 (effort S): Document and test a rollback: a workflow_dispatch input on pages.yml that publishes a given tag's bundle/web at the root, exercised once on a fork

### F2 Build, CI/CD & Automation: 7 (target 9)

Why: Tests, bundle sync and releases are automated; no lint, format, type or audit job (see C3-001, B4-001, F6-001), and merge blocking isn't visible from the repo

- Strength: CI tests the engine on three Pythons and the website in a real browser, keeps bundle/ generated from source/, and refuses a source change without a new version (`.github/workflows/tests.yml:33-34`; `.github/scripts/bundles.py:170-172`)
- Strength: Concurrency groups cancel stale runs, and screenshot baselines are saved by one job at a time (`.github/workflows/tests.yml:22-24`)
- Next: **F2-act-1** → 9 (effort S): Add a 'static' job to .github/workflows/tests.yml running ruff check, ruff format --check, mypy and pip-audit (C3-act-1, B4-act-1, F6-act-1), and require it with the tests in branch protection

### F3 Observability & Debuggability: 7 (target 8)

Why: Clear errors, exit codes and machine-readable output; no debug mode for the unexpected

- Strength: Actionable output for a CLI: documented exit codes, a JSON envelope with the error, a preflight that says how to fix each failure, and a CI comment that lists every problem (`source/tools/gradekit.py:3966-3967`; `source/tools/gradekit.py:7820-7821`)
- Finding F3-001 (minor, new): No verbose or debug mode: an unexpected error is either a one-line message or a raw traceback, with nothing in between (`source/tools/gradekit.py:7858-7860`: only GradekitError is caught; there's no --verbose/--debug or GRADEKIT_DEBUG to show context)
- Next: **F3-act-1** → 8 (effort S): Add a global --debug flag (or GRADEKIT_DEBUG=1) that prints the traceback and the resolved config sources on any error, and catch unexpected exceptions in run_command with a one-line message pointing at it

### F4 Performance, Efficiency & Scalability: 8 (target 8)

Why: Efficient for its scale (sub-second commands); the test loop is slow from process start-up

- Strength: Fast on real inputs: a full report check with every citation verified takes 0.4 s, and doctor scans a 466-file repo in 0.27 s (ran `time gradekit report check REPORT --repo CODE --project-dir PROJECT_DIR; time gradekit doctor --project-dir PROJECT_DIR --repo CODE`)

### F5 Portability: 7 (target 8)

Why: Works on the claimed runtime versions and avoids platform assumptions; the OS matrix is untested

- Strength: Portable by construction: pathlib throughout, repo paths normalised to '/', no shell in the engine except the guard's user-given commands, and three Python versions tested (`source/tools/gradekit.py:646-648`; `.github/workflows/tests.yml:33-34`)
- Finding F5-001 (minor, new): Only Linux is tested, though the CLI is offered to anyone with Python 3.11+ (and has Windows-specific code paths) (`.github/workflows/tests.yml:29`: guard_detect special-cases Windows, but every job runs on ubuntu-latest; `source/tools/gradekit.py:6350`: guard_detect special-cases Windows, but every job runs on ubuntu-latest)
- Next: **F5-act-1** → 8 (effort S): Add windows-latest and macos-latest to the engine job's matrix in .github/workflows/tests.yml (Python 3.11 and 3.13 are enough)

### F6 Dependency Health & Longevity: 6 (target 8)

Why: Minimal and pinned, but stale with no automated updates or audit

- Strength: Minimal and pinned: the engine needs only the standard library, test and build dependencies are pinned exactly, and Pyodide is pinned to one release by hash (`tests/requirements.txt:2-4`; `source/tools/web/engine-config.js:20-21`)
- Finding F6-001 (minor, new): Pinned dependencies go stale unnoticed: the test pin pillow 12.3.0 carries 39 advisories, and nothing updates or audits dependencies or the third-party actions (pinned to mutable major tags) (`tests/requirements.txt:6`: test-only: screenshots of the project's own pages; actions/* are pinned to @vN tags, not SHAs; `.github/workflows/release.yml:53-54`: test-only: screenshots of the project's own pages; actions/* are pinned to @vN tags, not SHAs; ran `pip-audit -r tests/requirements.txt -r .github/scripts/requirements-build.txt`: test-only: screenshots of the project's own pages; actions/* are pinned to @vN tags, not SHAs)
- Next: **F6-act-1** → 8 (effort S): Add .github/dependabot.yml for pip (tests/requirements.txt, .github/scripts/requirements-build.txt) and github-actions, pin actions to commit SHAs, bump pillow to 13.x, and run pip-audit in CI (F2-act-1)

### X1 Accessibility, UX & Internationalization: 8 (target 9)

Why: Accessible, responsive and tested in CI; English-only UI with no translation path

- Strength: Accessibility is tested, not hoped for: axe-core with zero violations on every page and state at desktop and phone width, plus keyboard checks (reachability with visible focus, skip link, arrow keys in tabs, file choosing) (`tests/test_accessibility.py:1`; `tests/test_accessibility.py:112`; `tests/test_accessibility.py:121`)
- Strength: Components carry the semantics: fields wire labels, help and errors for screen readers, and loading, empty and error states have roles (`source/tools/web/common.js:101-103`; `source/tools/web/common.js:63-64`)
- Finding X1-001 (minor, new): UI text is hard-coded English in the page scripts, with no message catalogue for translation (`source/tools/web/projects.js:156`: lang is fixed to en; strings live inline in each page's JavaScript; `source/tools/build_web.py:188`: lang is fixed to en; strings live inline in each page's JavaScript)
- Enforced by: The accessibility and layout tests run in CI on every pull request (`.github/workflows/tests.yml:82-83`)
- Next: **X1-act-1** → 9 (effort M): Move the page strings in source/tools/web/*.js into one messages object (per page), so a translation can be added without touching the logic

### X2 Public API Stability & Upgradeability: 9 (target 10)

Why: Semantic majors, pins, read-old/write-new formats, a migration command and compatibility tests; only doc slips remain (E2-001)

- Strength: Versioning is designed in: a kit version, a scoring version and a report format, each with its own job; projects pin a major, and the tools refuse to write a pinned project's report with another major (`source/tools/gradekit.py:164-166`; `source/tools/gradekit.py:215-217`)
- Strength: Old formats keep working: 5.x reads and recomputes 4.x reports under their own rules, and migrate upgrades a project in one reviewable PR that CI checks by redoing it (`source/tools/gradekit.py:4193-4195`; `source/ci/README.md:5`)
- Strength: Each major stays on the site at its own path, and the changelog explains every change and how to move (`README.md:22`)
- Enforced by: Tests pin compatibility: 4.x reports stay valid, older majors are refused, and pinned projects only get reports from their major (`tests/test_versions.py:53`; `tests/test_versions.py:124`)
- Next: **X2-act-1** → 10 (effort S): Add a short deprecation policy to source/README.md 'Versions and pins': how long a major's site path and read support last after the next major

### X3 Concurrency Safety: 7 (target 8)

Why: The documented concurrent uses are serialised or separated; parallel edits to one report aren't guarded

- Strength: Concurrent writers are handled where the docs put them: several graders write separate runs/run-N.json, the decide job is serialised per pull request, and baseline saves use a compare-and-swap push with retries (`source/ci/github-grading.yml:101-103`; `.github/scripts/visual_baselines.py:116-117`)
- Finding X3-001 (minor, new): Two commands editing the same report at once silently lose one edit (read, change, rewrite with no lock) (`source/tools/gradekit.py:2795-2797`: an agent running report commands in parallel (or the MCP server serving two clients) gets last-writer-wins; `source/tools/gradekit.py:2801-2803`: an agent running report commands in parallel (or the MCP server serving two clients) gets last-writer-wins)
- Next: **X3-act-1** → 8 (effort S): Make load_for_edit/save_edit take an exclusive lock file beside the report (fcntl/msvcrt, or O_EXCL on REPORT.lock) for the duration of a command, and say in the grader card that report commands run one at a time

### X5 Compliance & Licensing: 5 (target 9)

Why: Clear own license, but a published artifact redistributes third-party code without its notices; no SBOM

- Strength: The project's own license is clear and covers everything in the repo, reports included (`README.md:99`; `LICENSE:1`)
- Finding X5-001 (major, new): The 'web with Pyodide' release zip redistributes Pyodide (MPL-2.0), CPython's standard library and Python packages with no license notices (`source/tools/vendor_pyodide.py:29`: only the runtime files are copied; no LICENSE or notice file; `.github/scripts/release.sh:85-87`: the zip is published as a release asset; searched for license or notice files for third-party code in release.sh, vendor_pyodide.py, DEPLOY.md (grep -in licen .github/scripts/release.sh source/tools/vendor_pyodide.py source/DEPLOY.md: none))
- Next: **X5-act-1** → 8 (effort S): Make vendor_pyodide.py also copy Pyodide's LICENSE and a THIRD-PARTY-NOTICES file (Pyodide MPL-2.0 with a source link, the PSF license for the stdlib, each lock-file package's license) into SITE_DIR/pyodide/, and list them in DEPLOY.md *(needs a decision)*

### X6 Agent-Readiness: 7 (target 8)

Why: An agent can verify a change with documented commands and machine-readable output; repo-specific rules aren't collected for agents

- Strength: Clear signals for agents: exact test commands, --json on every command with documented exit codes, generated files marked 'never edit by hand', and CI that refuses a hand-edited bundle (`tests/README.md:31-32`; `README.md:90`)
- Finding X6-001 (minor, new): No agent instructions for working on the kit itself (AGENTS.md or CLAUDE.md): build, test and release rules have to be pieced together from three READMEs (searched for AGENTS.md, CLAUDE.md or an equivalent contributor file at the repo root or in source/ (git ls-files | grep -iE 'agents?\.md|claude\.md|contributing': only bundle/web/AGENT.md, which is for agents using the suite))
- Next: **X6-act-1** → 8 (effort S): Add AGENTS.md at the repo root: edit source/ never bundle/, the CHANGELOG/catalog version rule, the test commands (engine, browser, one test), and the lint/type commands once they exist

## Limitations

- First report for this project: no earlier report to reconcile, and no disputes or dispositions to answer.
- The repo is the grading kit itself. Its prompts and docs address graders by design (they are the product); they were read as evidence about the product, never as instructions for this grade, and none of them claims a score for this repo, so no integrity flag was raised.
- The kit used to grade is the same version as the code graded (5.0.0, identical files). The defects found in it (A1-001, A1-002) don't affect this report: no finding was left off its benchmark's list, and the rollup was stored last, after every score.
- Sandbox: a disposable container with no production credentials; network only through a proxy (package registries, the Pyodide CDN for the static-host browser tests, GitHub for delivery). Release, publish and Pages commands were read, not run; release.sh was not run even in DRY_RUN mode.
- Coverage covers Python only; the website's JavaScript was exercised by 317 browser tests but not measured. The screenshot comparison test skips itself off CI's platform, and CI run times and branch protection aren't visible from here.
- A2-001 (the CI templates fetch an unpinned kit) is not marked sensitive: it describes a design weakness visible in the public templates, not a way in, so withholding it would hide nothing from an attacker.

<sub>Rendered by gradekit from report.json (suite 5.0.0, config 98c3f35f5d08a1e2).</sub>
