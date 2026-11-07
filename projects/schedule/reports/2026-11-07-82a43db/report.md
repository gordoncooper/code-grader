# Grading report: schedule @ 82a43db (2026-11-07)

Code: https://github.com/dbader/schedule · Suite 4.2.1 · config `39a297f11c42a5c8` (oss_library) · grader: Claude Opus 5.5 (claude-opus-5-5)

## 1. Summary

schedule is a small, well-tested and pragmatic library: 81 tests with 97% branch coverage, zero runtime dependencies, clear scope documentation and deliberate DST handling. It scores **6.9 overall** and sits at maturity **L1**. Two hot-zone findings block L2. A job that raises is never rescheduled, so callers who catch exceptions get a hot retry loop (A3-001). The fluent builder API is untyped even though the package ships `py.typed` (B4-001). The adoption path is the weakest pillar (E, 5.1): the README quickstart crashes after the documented install because its timezone line needs pytz, and the documented contributor setup cannot run pytest at all. A setuptools deprecation means builds will stop working after 2027-02-18 unless the license metadata is updated.

## 2. Scorecard

**A. Correctness & Trust**: pillar score 6.9

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| A1 (gate) | Correctness & Functional Behavior | 8 | 10 | full | 3 | high | at() reports an unformatted placeholder when the hour is out of range |
| A2 (gate) | Security & Privacy | 8 | 9 | full | 2 | high | No security or dependency scanning in CI |
| A3 | Robustness & Error Handling | 5 | 9 | full | 2 | high | A job that raises is never rescheduled, and the rest of that tick's jobs are skipped |
| A4 | Idempotence & Determinism | 6 | 9 | full | 2 | medium | Calling do() again on the same job registers it twice, so it runs twice per tick |
| A5 | Durability & Recoverability | – | – | not_applicable | 0 | high | No persistent state by design: jobs are declared in code and rebuilt at startup; docs list job persistence under 'When not to use Schedule'. |

**B. Design & Structure**: pillar score 6.8

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| B1 | Architecture & Design Fitness | 7 | 10 | full | 3 | medium | Timezone handling is tied to pytz's normalize() throughout Job |
| B2 | Modularity & Decoupling | 7 | 10 | full | 3 | medium | Module-level default scheduler exposes its live jobs list as a global alias |
| B3 | Structure & Organization | 8 | 8 | full | 1 | high | Tidy single-package layout with tests, docs and CI cleanly separated |
| B4 | Interface Design & Contracts | 5 | 10 | full | 3 | high | Fluent builder properties and helpers are untyped, so typed callers get Any from every()-chains |
| B5 | Flexibility & Extensibility | 6 | 8 | full | 1 | medium | Supported units are hard-coded in several places; adding one means shotgun edits |
| B6 | Leanness | 9 | 9 | full | 2 | high | No runtime dependencies and about 510 source lines for the whole feature set; vulture finds only public API |

**C. Code Health**: pillar score 7.4

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| C1 | Readability & Clarity | 7 | 9 | full | 2 | medium | at() reuses hour/minute/second as both str and int across branches |
| C2 | Maintainability & Complexity | 7 | 10 | full | 3 | high | Seven weekday properties are copy-pasted with only the day name changed |
| C3 | Consistency & Idiomatic Code | 8 | 9 | full | 2 | high | Two string-formatting styles (%-style and str.format) are mixed in one module |
| C4 | Test Suite Quality | 8 | 9 | full | 2 | high | No test covers a job that raises |

**D. Value & Fitness**: pillar score 8.5

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| D1 | Feature Completeness | 9 | 9 | full | 2 | medium | Every feature in README and docs exercised by tests and works end to end (timezones with the documented pytz extra) |
| D2 | Gap Coverage | 8 | 9 | full | 2 | medium | Timezones must be pytz objects; standard-library zoneinfo is rejected |
| D3 | Practicality | 9 | 9 | full | 2 | medium | Pragmatic in-process design with trade-offs documented (missed runs, persistence, threads) |
| D4 | Intuitiveness | 8 | 9 | full | 2 | medium | until('HH:MM') earlier than now raises instead of meaning tomorrow |

**E. Adoption & Experience**: pillar score 5.1

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| E1 | Adopter Friendliness | 4 | 10 | full | 3 | high | The README quickstart crashes after the documented install |
| E2 | Documentation | 5 | 10 | full | 3 | high | Development docs give a test command that fails |
| E3 | Developer Experience & Inner Loop | 5 | 9 | full | 2 | high | The documented dev environment cannot run pytest at all |
| E4 | Native Tooling & Ecosystem Fit | 7 | 9 | full | 2 | high | Packaging is half-migrated: metadata split between setup.py and pyproject.toml, checked with deprecated setup.py check |

**F. Operations & Delivery**: pillar score 6.6

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| F1 | Ease of Deployability | 6 | 8 | full | 1 | medium | Releases are manual: version bumped in two files, tag, build and twine by hand |
| F2 | Build, CI/CD & Automation | 7 | 10 | full | 3 | medium | CI has no release automation and no lint step |
| F3 | Observability & Debuggability | 7 | 8 | limited | 1 | medium | An in-process library of about 500 lines with no service surface; logging is the only relevant signal. Would be fully relevant if it ran as a daemon. |
| F4 | Performance, Efficiency & Scalability | 8 | 8 | full | 1 | medium | Hot path is one pass over the job list per tick; fine at the documented scale |
| F5 | Portability | 7 | 9 | full | 2 | medium | The package claims OS independence, but tests are Unix-only and CI runs Linux only |
| F6 | Dependency Health & Longevity | 5 | 9 | full | 2 | high | Builds will stop working with setuptools after 2027-02-18 (deprecated license metadata) |

**X. Conditional**: pillar score 7.3

| ID | Benchmark | Score | Target | Applicability | Weight | Confidence | Why |
|---|---|:-:|:-:|---|:-:|---|---|
| X1 | Accessibility, UX & Internationalization | – | – | not_applicable | 0 | high | Library with no user interface. |
| X2 | Public API Stability & Upgradeability | 7 | 10 | full | 3 | medium | No explicit public surface or deprecation mechanism |
| X3 | Concurrency Safety | 7 | 8 | limited | 1 | medium | The scheduler is single-threaded by design; concurrency only arises when users run job bodies on threads, as the docs show. |
| X4 | Cost Efficiency | – | – | not_applicable | 0 | high | Runs in the user's process; no paid infrastructure or API calls. |
| X5 | Compliance & Licensing | 9 | 9 | full | 2 | medium | MIT license shipped in the sdist, zero runtime dependencies, and the optional pytz is MIT too |
| X6 | Agent-Readiness | 5 | 8 | full | 1 | medium | No agent or contributor instructions with working commands |

**Overall: 6.9**

## 3. Applicability and weight callouts

- **A5 Durability & Recoverability**: not_applicable. No persistent state by design: jobs are declared in code and rebuilt at startup; docs list job persistence under 'When not to use Schedule'.
- **F3 Observability & Debuggability**: limited. An in-process library of about 500 lines with no service surface; logging is the only relevant signal. Would be fully relevant if it ran as a daemon.
- **X1 Accessibility, UX & Internationalization**: not_applicable. Library with no user interface.
- **X3 Concurrency Safety**: limited. The scheduler is single-threaded by design; concurrency only arises when users run job bodies on threads, as the docs show.
- **X4 Cost Efficiency**: not_applicable. Runs in the user's process; no paid infrastructure or API calls.
- No weight notes: the config weights fit this project.

## 4. Gates and maturity

| Gate | Score | Status |
|---|:-:|---|
| A1 Correctness & Functional Behavior | 8 | passed (always) |
| A2 Security & Privacy | 8 | passed (always) |

Current level **L1**, next **L2**. Unmet:
- at most 0 open critical findings in hot zones: now 2 (A3-001, B4-001)

## 5. Top 10 priorities

| # | Action | Tier | Zone | Gain | Effort | Decision |
|:-:|---|:-:|---|:-:|:-:|---|
| 1 | **B4-act-1**: Annotate every Job property and builder method to return 'Job' (and the remaining helpers), then switch setup.cfg [mypy] to strict = True and keep CI green | 0 | hot | +3 | M |  |
| 2 | **A3-act-1**: In Job.run(), compute last_run and _schedule_next_run() in a try/finally around job_func() so a failing job still moves to its next interval; let Scheduler.run_pending() continue with the remaining due jobs and re-raise afterwards; add tests for both | 0 | hot | +3 | M | needed |
| 3 | **B4-act-2**: Introduce Literal types for unit and start_day | 2 | hot | +3 | S |  |
| 4 | **A3-act-2**: Replace the assert in Job.should_run with an explicit ScheduleError when next_run is None | 2 | hot | +3 | S |  |
| 5 | **E1-act-1**: In README.rst and docs/index.rst, either move the timezone line into a separate example preceded by `pip install schedule[timezone]`, or add that install line to the quickstart; run the README snippet in CI (e.g. a doctest or script step) | 2 | normal | +4 | S |  |
| 6 | **E2-act-2**: Correct README feature bullets: say timezone support needs `schedule[timezone]`; fix 'Tested on Python and 3.7' to the versions CI actually runs | 2 | normal | +3 | S |  |
| 7 | **F6-act-3**: Drop Python 3.7 and 3.8 from python_requires, classifiers, tox and CI; add 3.13 | 2 | normal | +4 | S | needed |
| 8 | **A1-act-1**: In schedule/__init__.py, format the hour into the at() error (line 548) and reword the to() check at line 711 to '`latest` must be greater than or equal to `interval`'; add assertRaisesRegex tests for both messages | 2 | hot | +1 | S |  |
| 9 | **B2-act-1**: Deprecate the module-level `jobs` alias in favour of get_jobs(), emitting a DeprecationWarning on access via module __getattr__ | 2 | hot | +1 | S | needed |
| 10 | **C2-act-1**: Generate the seven weekday properties from one helper (e.g. a _weekday(name) factory) with a single error message | 2 | hot | +1 | S |  |

### Decisions needed (answer them together)

- [ ] **A3-act-1**: Approve rescheduling a job's next run even when it raises, so a failing job retries at its next interval instead of on every tick?
- [ ] **B2-act-1**: Approve deprecating the public module-level `schedule.jobs` list in favour of `schedule.get_jobs()`?
- [ ] **D2-act-1**: Support standard-library zoneinfo alongside pytz in 1.x, or migrate fully to zoneinfo and drop pytz in a 2.0?
- [ ] **D4-act-1**: Should until('HH:MM') earlier than now mean tomorrow, or keep raising with a clearer message?
- [ ] **F1-act-1**: Set up PyPI trusted publishing from GitHub Actions for releases?
- [ ] **F6-act-3**: Approve dropping Python 3.7 and 3.8 support in the next minor release?
- [ ] **X2-act-1**: Approve declaring __all__ (it changes what `from schedule import *` exports)?

Record answers in `decisions.json`; the suite website's **Review a report** page writes it for you.

## 6. Metrics

| Metric | Value | Note |
|---|---|---|
| `build_passes` | True |  |
| `tests_total` | 81 |  |
| `tests_failed` | 0 |  |
| `tests_skipped` | 0 |  |
| `flaky_tests_detected` | 0 |  |
| `line_coverage_pct` | 99.2 |  |
| `branch_coverage_pct` | 97.2 |  |
| `core_branch_coverage_pct` | 97.2 | core = schedule/__init__.py, the only module |
| `mutation_score_pct` | – | no mutation tool run |
| `lint_errors` | 3 | flake8 at black's 88-column width; the project has no lint config |
| `lint_warnings` | 0 |  |
| `lint_suppressions` | 0 |  |
| `type_errors_strict` | 45 |  |
| `type_escape_hatches` | 3 |  |
| `vulns_critical` | 0 | runtime dependencies: none. Dev-only black 20.8b1 has 4 advisories (F6-002), not counted here |
| `vulns_high` | 0 |  |
| `vulns_medium` | 0 |  |
| `vulns_low` | 0 |  |
| `secrets_found` | 0 |  |
| `deps_direct` | 0 |  |
| `deps_transitive` | 0 |  |
| `deps_outdated_major` | 0 |  |
| `deps_unused` | 0 |  |
| `loc_source` | 512 | radon SLOC |
| `loc_tests` | 1137 |  |
| `complexity_p95` | 10 |  |
| `complexity_max` | 25 |  |
| `duplication_pct` | – | no duplication tool available; duplication judged by reading (C2-001) |
| `functions_over_50_lines` | 2 |  |
| `dependency_cycles` | 0 |  |
| `todo_fixme_count` | 1 |  |
| `dead_code_items` | 0 |  |
| `artifact_size_bytes` | 12286 | wheel size |
| `ci_duration_seconds` | – | CI runs of dbader/schedule not visible from this session |
| `setup_second_run_passes` | – | no setup, seed or migration scripts |
| `time_to_first_success_minutes` | – | the literal quickstart fails (E1-001); not timed |
| `time_to_first_test_minutes` | – | the documented dev setup never reaches a passing test (E3-001); an undocumented venv + pytest route took about a minute |
| `quickstart_steps` | 2 |  |

## 7. Findings

| ID | Benchmark | Severity → effective | Zone | Status | Title |
|---|---|---|---|---|---|
| A1-001 | A1 | minor → major | hot | new | at() reports an unformatted placeholder when the hour is out of range |
| A1-002 | A1 | minor → major | hot | new | every(a).to(b) with b < a raises an error that states the opposite of the problem |
| A2-001 | A2 | minor → minor | normal | new | No security or dependency scanning in CI |
| A3-001 | A3 | major → critical | hot | new | A job that raises is never rescheduled, and the rest of that tick's jobs are skipped |
| A3-002 | A3 | minor → major | hot | new | should_run guards an invariant with assert, which python -O removes |
| A4-001 | A4 | minor → major | hot | new | Calling do() again on the same job registers it twice, so it runs twice per tick |
| A4-002 | A4 | minor → major | hot | new | Time and randomness are not injectable; tests patch datetime.datetime globally |
| B1-001 | B1 | minor → major | hot | new | Timezone handling is tied to pytz's normalize() throughout Job |
| B2-001 | B2 | minor → major | hot | new | Module-level default scheduler exposes its live jobs list as a global alias |
| B4-001 | B4 | major → critical | hot | new | Fluent builder properties and helpers are untyped, so typed callers get Any from every()-chains |
| B4-002 | B4 | minor → major | hot | new | Units and weekdays are plain strings, so invalid states are only caught at do() time |
| B5-001 | B5 | minor → major | hot | new | Supported units are hard-coded in several places; adding one means shotgun edits |
| C1-001 | C1 | minor → major | hot | new | at() reuses hour/minute/second as both str and int across branches |
| C2-001 | C2 | minor → major | hot | new | Seven weekday properties are copy-pasted with only the day name changed |
| C2-002 | C2 | minor → minor | normal | new | Job.at() is the complexity hotspot (cyclomatic 25, 89 lines) |
| C3-001 | C3 | minor → major | hot | new | Two string-formatting styles (%-style and str.format) are mixed in one module |
| C4-001 | C4 | minor → minor | normal | new | No test covers a job that raises |
| D2-001 | D2 | minor → major | hot | new | Timezones must be pytz objects; standard-library zoneinfo is rejected |
| D4-001 | D4 | minor → major | hot | new | until('HH:MM') earlier than now raises instead of meaning tomorrow |
| E1-001 | E1 | major → major | normal | new | The README quickstart crashes after the documented install |
| E2-001 | E2 | major → minor | cold | new | Development docs give a test command that fails |
| E2-002 | E2 | minor → minor | normal | new | README feature claims are inaccurate |
| E3-001 | E3 | major → major | normal | new | The documented dev environment cannot run pytest at all |
| E4-001 | E4 | minor → minor | normal | new | Packaging is half-migrated: metadata split between setup.py and pyproject.toml, checked with deprecated setup.py check |
| F1-001 | F1 | minor → minor | cold | new | Releases are manual: version bumped in two files, tag, build and twine by hand |
| F2-001 | F2 | minor → minor | normal | new | CI has no release automation and no lint step |
| F5-001 | F5 | minor → minor | normal | new | The package claims OS independence, but tests are Unix-only and CI runs Linux only |
| F6-001 | F6 | major → major | normal | new | Builds will stop working with setuptools after 2027-02-18 (deprecated license metadata) |
| F6-002 | F6 | minor → minor | normal | new | Dev toolchain pinned to black 20.8b1 (2020), which has published advisories; no automated updates |
| F6-003 | F6 | minor → minor | normal | new | Still declares support for end-of-life Python 3.7 and 3.8 |
| X2-001 | X2 | minor → minor | normal | new | No explicit public surface or deprecation mechanism |
| X6-001 | X6 | minor → minor | normal | new | No agent or contributor instructions with working commands |

This is the first report for this project, so there are no fixed or regressed findings.

## 8. Feature inventory and gap register

| Feature | Source | Status |
|---|---|---|
| every(n).<unit>.do(job, *args, **kwargs) | README | complete |
| Daily/hourly/minutely .at() times | README | complete |
| Weekday scheduling (.monday ... .sunday) | README | complete |
| Timezones in .at() | README, docs/timezones.rst | partial |
| Randomized intervals .to() | README | complete |
| Run until a deadline .until() | docs/examples.rst | complete |
| Tags: get_jobs(tag), clear(tag) | docs/examples.rst | complete |
| Cancel from inside a job (CancelJob) | docs/examples.rst | complete |
| @repeat decorator | docs/examples.rst | complete |
| run_all(delay_seconds) | docs/reference.rst | complete |
| next_run / idle_seconds | docs/examples.rst | complete |
| Multiple schedulers | docs/multiple-schedulers.rst | complete |
| Logging via the 'schedule' logger | docs/logging.rst | complete |

| ID | Gap | Severity | Necessity | Benchmarks |
|---|---|---|---|---|
| GAP-001 | Standard-library zoneinfo timezones are not accepted | minor | nice-to-have | D2 |
| GAP-002 | No built-in hook for job failures (users must wrap each job or subclass the scheduler) | minor | nice-to-have | D2, A3 |

## 9. Per-benchmark detail

### A1 Correctness & Functional Behavior: 8 / target 10
- Strength: 81 tests pass, with deliberate DST and timezone handling covered by tests. `python -m pytest test_schedule.py schedule -q --cov schedule --cov-branch --cov-` → `81 passed in 0.58s`; `schedule/__init__.py:811-813` `# We ended up in a DST Gap. The requested 'at' time does not exist` (DST gap handled explicitly)
- **A1-001** (minor): at() reports an unformatted placeholder when the hour is out of range. `schedule/__init__.py:547-549` `raise ScheduleValueError(` (the message is never .format()-ed, so users see a literal '{}'); `python /tmp/probe.py  (every().day.at('25:00'))` → `2. message: Invalid number of hours ({} is not between 0 and 23)`
- **A1-002** (minor): every(a).to(b) with b < a raises an error that states the opposite of the problem. `schedule/__init__.py:710-711` `if not (self.latest >= self.interval):` (condition is latest < interval, but the message says latest is greater); `python /tmp/probe.py  (every(5).to(2).seconds)` → `3. message: `latest` is greater than `interval``
- Action **A1-act-1** (S, → 9): In schedule/__init__.py, format the hour into the at() error (line 548) and reword the to() check at line 711 to '`latest` must be greater than or equal to `interval`'; add assertRaisesRegex tests for both messages

### A2 Security & Privacy: 8 / target 9
- Strength: No runtime dependencies, no I/O, no eval or shell; inputs validated at the API edge. `schedule/__init__.py:466-467` `if not all(isinstance(tag, Hashable) for tag in tags):` (tags validated); `schedule/__init__.py:513-514` `if not re.match(r"^[0-2]\d:[0-5]\d(:[0-5]\d)?$", time_str):` (time strings validated with anchored regexes)
- **A2-001** (minor): No security or dependency scanning in CI. absence: secret, SAST or dependency-audit step in CI (read .github/workflows/ci.yml and tox.ini in full)
- Action **A2-act-1** (S, → 9): Add a CI job that runs pip-audit against requirements-dev.txt and a secret scan (e.g. gitleaks) on pull requests

### A3 Robustness & Error Handling: 5 / target 9
- Strength: Configuration errors raise specific exception types with clear messages. `schedule/__init__.py:65-66` `class IntervalError(ScheduleValueError):` (IntervalError subclass); `schedule/__init__.py:494-496` `raise ScheduleValueError(` (explicit message for invalid units)
- **A3-001** (major): A job that raises is never rescheduled, and the rest of that tick's jobs are skipped. `schedule/__init__.py:691-693` `ret = self.job_func()` (an exception from job_func() skips _schedule_next_run(), so next_run stays in the past); `python /tmp/probe.py  (hourly job that raises, run_pending() wrapped in try/exce` → `1. failing hourly job ran 5 times in 5 consecutive ticks; next_run in past: True`
- **A3-002** (minor): should_run guards an invariant with assert, which python -O removes. `schedule/__init__.py:671` `assert self.next_run is not None, "must run _schedule_next_run before"` (under -O this becomes a TypeError comparing datetime with None)
- Action **A3-act-1** (M, → 8): In Job.run(), compute last_run and _schedule_next_run() in a try/finally around job_func() so a failing job still moves to its next interval; let Scheduler.run_pending() continue with the remaining due jobs and re-raise afterwards; add tests for both *Decision: Approve rescheduling a job's next run even when it raises, so a failing job retries at its next interval instead of on every tick?*
- Action **A3-act-2** (S, → 8): Replace the assert in Job.should_run with an explicit ScheduleError when next_run is None

### A4 Idempotence & Determinism: 6 / target 9
- Strength: Tests are deterministic: three consecutive runs gave identical results. `python -m pytest test_schedule.py -q  (x3)` → `81 passed in 0.09s`
- **A4-001** (minor): Calling do() again on the same job registers it twice, so it runs twice per tick. `schedule/__init__.py:663` `self.scheduler.jobs.append(self)` (do() appends unconditionally); `PYTHONPATH=. python - (job.do(f); job.do(f); run_pending())` → `jobs registered after calling do() twice on one job: 2`
- **A4-002** (minor): Time and randomness are not injectable; tests patch datetime.datetime globally. `schedule/__init__.py:717` `now = datetime.datetime.now(self.at_time_zone)` (wall clock read deep inside scheduling logic); `schedule/__init__.py:712` `interval = random.randint(self.interval, self.latest)` (unseeded module-level random); `test_schedule.py:39` `class mock_datetime:` (tests swap out datetime.datetime with a context manager instead of passing a clock)
- Action **A4-act-1** (S, → 7): Make Job.do() idempotent: if self is already in scheduler.jobs, update job_func instead of appending again; add a test
- Action **A4-act-2** (M, → 8): Add an optional clock (callable returning now) and random.Random instance to Scheduler, passed to its jobs; switch tests from patching datetime.datetime to an injected fake clock

### A5 Durability & Recoverability: –
*not_applicable*: No persistent state by design: jobs are declared in code and rebuilt at startup; docs list job persistence under 'When not to use Schedule'.

### B1 Architecture & Design Fitness: 7 / target 10
- Strength: A small, fitting design: a Scheduler that owns jobs, a fluent Job builder, and a thin module-level facade. `schedule/__init__.py:843-845` `def every(interval: int = 1) -> Job:` (facade delegates to the default scheduler)
- **B1-001** (minor): Timezone handling is tied to pytz's normalize() throughout Job. `schedule/__init__.py:499` `import pytz` (pytz imported lazily inside at()); `schedule/__init__.py:789` `moment = self.at_time_zone.normalize(moment)` (pytz-specific API used in the core next-run computation)
- Action **B1-act-1** (M, → 8): Isolate timezone conversion behind a small internal helper (normalize/localize) so Job no longer calls pytz APIs directly

### B2 Modularity & Decoupling: 7 / target 10
- Strength: Scheduler instances are independent; multiple schedulers are supported and documented. `schedule/__init__.py:86-87` `def __init__(self) -> None:` (state is per instance)
- **B2-001** (minor): Module-level default scheduler exposes its live jobs list as a global alias. `schedule/__init__.py:840` `jobs = default_scheduler.jobs  # todo: should this be a copy, e.g. jobs()?` (mutable alias to internal state; the authors' own TODO questions it)
- Action **B2-act-1** (S, → 8): Deprecate the module-level `jobs` alias in favour of get_jobs(), emitting a DeprecationWarning on access via module __getattr__ *Decision: Approve deprecating the public module-level `schedule.jobs` list in favour of `schedule.get_jobs()`?*

### B3 Structure & Organization: 8 / target 8
- Strength: Tidy single-package layout with tests, docs and CI cleanly separated. absence: misplaced or junk files (git ls-files; read MANIFEST.in)

### B4 Interface Design & Contracts: 5 / target 10
- Strength: Default mypy passes and runtime validation is thorough. `python -m mypy -p schedule` → `Success: no issues found in 1 source file`
- **B4-001** (major): Fluent builder properties and helpers are untyped, so typed callers get Any from every()-chains. `schedule/__init__.py:331-333` `@property` (no return annotation on unit properties; py.typed is shipped, so this leaks Any to users); `python -m mypy --strict -p schedule` → `Found 45 errors in 1 file (checked 1 source file)`
- **B4-002** (minor): Units and weekdays are plain strings, so invalid states are only caught at do() time. `schedule/__init__.py:233` `self.unit: Optional[str] = None` (stringly-typed unit); `schedule/__init__.py:704` `if self.unit not in ("seconds", "minutes", "hours", "days", "weeks"):` (validated late, when the job is finally scheduled)
- Action **B4-act-1** (M, → 8): Annotate every Job property and builder method to return 'Job' (and the remaining helpers), then switch setup.cfg [mypy] to strict = True and keep CI green
- Action **B4-act-2** (S, → 8): Introduce Literal types for unit and start_day

### B5 Flexibility & Extensibility: 6 / target 8
- Strength: Multiple schedulers and the repeat decorator let users extend behavior without forking. `schedule/__init__.py:909-911` `def _schedule_decorator(decorated_function):` (decorator built on the same Job API)
- **B5-001** (minor): Supported units are hard-coded in several places; adding one means shotgun edits. `schedule/__init__.py:493` `if self.unit not in ("days", "hours", "minutes") and not self.start_day:` (at() keeps its own unit list); `schedule/__init__.py:704` `if self.unit not in ("seconds", "minutes", "hours", "days", "weeks"):` (_schedule_next_run keeps another)
- Action **B5-act-1** (S, → 7): Define the supported units once (a module constant) and derive at()'s and _schedule_next_run's checks from it

### B6 Leanness: 9 / target 9
- Strength: No runtime dependencies and about 510 source lines for the whole feature set; vulture finds only public API. `python -c 'import tomllib; ...["project"]["dependencies"]'` → `[]`; `vulture schedule --min-confidence 60` → `schedule/__init__.py:471: unused method 'at' (60% confidence)`

### C1 Readability & Clarity: 7 / target 9
- Strength: Docstrings on every public method explain behavior and edge cases. `schedule/__init__.py:93-95` `Please note that it is *intended behavior that run_pending()` (documents the missed-run policy)
- **C1-001** (minor): at() reuses hour/minute/second as both str and int across branches. `schedule/__init__.py:529-531` `hour: Union[str, int]` (the same names change type mid-function, which makes the parsing hard to follow)
- Action **C1-act-1** (S, → 8): Split Job.at() into _validate_at_format(unit, time_str) and _parse_at_time(...) -> datetime.time, using int-only locals

### C2 Maintainability & Complexity: 7 / target 10
- Strength: Average complexity is low (A, 2.75) and there is only one TODO. `radon cc schedule -s -a` → `Average complexity: A (2.75)`
- **C2-001** (minor): Seven weekday properties are copy-pasted with only the day name changed. `schedule/__init__.py:388-389` `self.start_day = "monday"` (repeated for monday...sunday with identical error text (lines 380-455))
- **C2-002** (minor): Job.at() is the complexity hotspot (cyclomatic 25, 89 lines). `radon cc schedule -s` → `M 471:4 Job.at - D (25)`
- Action **C2-act-1** (S, → 8): Generate the seven weekday properties from one helper (e.g. a _weekday(name) factory) with a single error message
- Action **C2-act-2** (M, → 9): Reduce Job.at() below complexity 10 by splitting it as in C1-act-1, and add a radon/xenon complexity gate to CI

### C3 Consistency & Idiomatic Code: 8 / target 9
- Strength: black --check enforced in CI at the pinned version. `.github/workflows/ci.yml:77-78` `- name: Check formatting` (formatting job); `black==20.8b1 --check .` → `4 files would be left unchanged.`
- **C3-001** (minor): Two string-formatting styles (%-style and str.format) are mixed in one module. `schedule/__init__.py:303` `return "Every %s %s at %s do %s %s" % (` (%-formatting); `schedule/__init__.py:943` `"Invalid start day (valid start days are {})".format(weekdays)` (str.format)
- Action **C3-act-1** (S, → 9): Use f-strings consistently for messages and keep %-style only for logger arguments

### C4 Test Suite Quality: 8 / target 9
- Strength: 99% line / 97% branch coverage, deterministic, run on six Python versions with and without pytz. `python -m pytest test_schedule.py schedule -q --cov schedule --cov-branch --cov-` → `schedule/__init__.py     385      3    144      4    99%   552->555, 659, 755, 800`; `tox.ini:2` `envlist = py3{7,8,9,10,11,12}{,-pytz}` (matrix with and without pytz)
- **C4-001** (minor): No test covers a job that raises. absence: a test where a scheduled job raises an exception (grep -n 'raise\|Exception' test_schedule.py; read SchedulerTests)
- Action **C4-act-1** (S, → 9): Add tests for a job that raises: the exception propagates, the job's next_run moves forward and other due jobs still run (pairs with A3-act-1)

### D1 Feature Completeness: 9 / target 9
- Strength: Every feature in README and docs exercised by tests and works end to end (timezones with the documented pytz extra). `python -m pytest test_schedule.py schedule -q --cov schedule --cov-branch --cov-` → `81 passed in 0.58s`; `pyproject.toml:19-20` `[project.optional-dependencies]` (timezone extra declared)

### D2 Gap Coverage: 8 / target 9
- Strength: Scope boundaries are documented explicitly. `docs/index.rst:59-61` `* Job persistence (remember schedule between restarts)` (the 'When not to use Schedule' list)
- **D2-001** (minor): Timezones must be pytz objects; standard-library zoneinfo is rejected. `schedule/__init__.py:503-505` `elif isinstance(tz, pytz.BaseTzInfo):` (only str or pytz.BaseTzInfo accepted); `python /tmp/probe.py  (at('10:00', ZoneInfo('Europe/Amsterdam')))` → `4. zoneinfo: ScheduleValueError Timezone must be string or pytz.timezone object`
- Action **D2-act-1** (M, → 9): Accept zoneinfo.ZoneInfo (and any tzinfo) in at() alongside pytz, keeping pytz optional; add tests on 3.9+ *Decision: Support standard-library zoneinfo alongside pytz in 1.x, or migrate fully to zoneinfo and drop pytz in a 2.0?*

### D3 Practicality: 9 / target 9
- Strength: Pragmatic in-process design with trade-offs documented (missed runs, persistence, threads). `schedule/__init__.py:93-95` `Please note that it is *intended behavior that run_pending()` (missed-run behavior documented); `docs/index.rst:59-61` `* Job persistence (remember schedule between restarts)` (honest scope)

### D4 Intuitiveness: 8 / target 9
- Strength: The fluent API reads like English and rejects nonsense early. `schedule/__init__.py:383-385` `raise IntervalError(` (explains why every(2).monday is rejected)
- **D4-001** (minor): until('HH:MM') earlier than now raises instead of meaning tomorrow. `schedule/__init__.py:626-628` `if "-" not in until_time:` (time-only strings are always pinned to today); `python /tmp/probe.py  (every().hour.until(<a minute ago>))` → `5. Cannot schedule a job to run until a time in the past`
- Action **D4-act-1** (S, → 9): When until() gets a time-only string that has already passed today, either roll it to tomorrow or raise a message that says so; document the choice *Decision: Should until('HH:MM') earlier than now mean tomorrow, or keep raising with a clearer message?*

### E1 Adopter Friendliness: 4 / target 10
Caps: Quickstart fails → max 4
- Strength: Standard pip install, MIT license, runnable examples in docs. `README.rst:27` `$ pip install schedule` (one-line install); `setup.py:24` `license="MIT",` (license declared)
- **E1-001** (major): The README quickstart crashes after the documented install. `README.rst:27` `$ pip install schedule` (the only install step); `README.rst:44` `schedule.every().day.at("12:42", "Europe/Amsterdam").do(job)` (this line needs pytz, which 'pip install schedule' does not install); `python qs_readme.py  (README example, fresh venv with only the built wheel)` → `ModuleNotFoundError: No module named 'pytz'`
- Action **E1-act-1** (S, → 8): In README.rst and docs/index.rst, either move the timezone line into a separate example preceded by `pip install schedule[timezone]`, or add that install line to the quickstart; run the README snippet in CI (e.g. a doctest or script step)

### E2 Documentation: 5 / target 10
Caps: Wrong setup instructions → max 5
- Strength: Layered docs on Read the Docs: examples, timezones, exception handling, FAQ, autodoc reference, changelog; built with -W in CI. `.github/workflows/ci.yml:64-65` `- name: Check docs` (docs built in CI); `sphinx-build -W -b html . _build` → `exit 0`
- **E2-001** (major): Development docs give a test command that fails. `docs/development.rst:22` `py.test test_schedule.py --flake8 schedule -v --cov schedule --cov-report term-missing` (--flake8 relies on pytest-flake8, which can't load with current pytest); `pip install -r requirements-dev.txt && py.test test_schedule.py --flake8 schedul` → `Argument(s) {'path'} are declared in the hookimpl but can not be found in the hookspec`
- **E2-002** (minor): README feature claims are inaccurate. `README.rst:18` `- Very lightweight and no external dependencies.` (timezone support needs the optional pytz package); `README.rst:20` `- Tested on Python and 3.7, 3.8, 3.9, 3.10, 3.11, 3.12` (typo, and the 3.7 claim is unverifiable on current CI runners)
- Action **E2-act-1** (S, → 8): Fix docs/development.rst: replace the --flake8 command with `tox` (or `pytest test_schedule.py`) and `flake8 schedule`, and drop the black 20.8b1 instruction once F6-act-2 lands
- Action **E2-act-2** (S, → 8): Correct README feature bullets: say timezone support needs `schedule[timezone]`; fix 'Tested on Python and 3.7' to the versions CI actually runs

### E3 Developer Experience & Inner Loop: 5 / target 9
- Strength: Tests are tiny and fast; tox covers every environment. `python -m pytest test_schedule.py -q` → `81 passed in 0.09s`
- **E3-001** (major): The documented dev environment cannot run pytest at all. `requirements-dev.txt:5` `pytest-flake8` (unpinned pytest-flake8 is incompatible with pytest 9; it breaks every pytest invocation in that env); `pip install -r requirements-dev.txt && python -m pytest test_schedule.py -q` → `Argument(s) {'path'} are declared in the hookimpl but can not be found in the hookspec`
- Action **E3-act-1** (S, → 8): Remove pytest-flake8 from requirements-dev.txt, add flake8 (or ruff) as its own tox env, and pin dev tools with a constraints file

### E4 Native Tooling & Ecosystem Fit: 7 / target 9
- Strength: Standard ecosystem tools throughout: pytest, tox, mypy, black, Sphinx, wheel builds. `tox.ini:22-24` `commands =` (standard test env)
- **E4-001** (minor): Packaging is half-migrated: metadata split between setup.py and pyproject.toml, checked with deprecated setup.py check. `setup.py:5` `SCHEDULE_VERSION = "1.2.2"` (version lives in setup.py (and is repeated in docs/conf.py)); `tox.ini:38` `python setup.py check --strict --metadata --restructuredtext` (deprecated direct setup.py invocation in CI)
- Action **E4-act-1** (M, → 9): Move all metadata (version, classifiers, keywords, authors) into pyproject.toml, read the version in docs/conf.py from package metadata, delete setup.py, and replace `setup.py check` with `python -m build && twine check dist/*`

### F1 Ease of Deployability: 6 / target 8
- Strength: The release procedure is written down. `docs/development.rst:53` `Bump the version in ``setup.py`` and ``docs/conf.py``.` (documented steps)
- **F1-001** (minor): Releases are manual: version bumped in two files, tag, build and twine by hand. `docs/development.rst:53` `Bump the version in ``setup.py`` and ``docs/conf.py``.` (two places to bump by hand); `docs/development.rst:66` `twine upload --repository schedule dist/*` (manual upload)
- Action **F1-act-1** (M, → 8): Add a tag-triggered GitHub Actions workflow that builds and publishes to PyPI via trusted publishing; single-source the version *Decision: Set up PyPI trusted publishing from GitHub Actions for releases?*

### F2 Build, CI/CD & Automation: 7 / target 10
- Strength: CI gates tests on six Python versions plus mypy, docs, formatting and packaging checks. `.github/workflows/ci.yml:17` `python-version: ['3.7', '3.8', '3.9', '3.10', '3.11', '3.12']` (version matrix); `tox.ini:23-24` `py.test test_schedule.py schedule -v --cov schedule --cov-report term-missing` (pytest with coverage, then mypy)
- **F2-001** (minor): CI has no release automation and no lint step. absence: a publish/release workflow or a flake8/ruff step (read .github/workflows/ci.yml and tox.ini in full)
- Action **F2-act-1** (S, → 8): Add a lint job (flake8 or ruff) and pip caching to CI; release automation via F1-act-1

### F3 Observability & Debuggability: 7 / target 8
*limited*: An in-process library of about 500 lines with no service surface; logging is the only relevant signal. Would be fully relevant if it ran as a daemon.
- Strength: Uses a named 'schedule' logger with debug messages for runs and cancellations, documented in docs/logging.rst. `schedule/__init__.py:50` `logger = logging.getLogger("schedule")` (named logger); `schedule/__init__.py:690` `logger.debug("Running job %s", self)` (each run logged)
- Action **F3-act-1** (S, → 8, optional): Log at warning level, with the job repr, when a job raises before the exception propagates

### F4 Performance, Efficiency & Scalability: 8 / target 8
- Strength: Hot path is one pass over the job list per tick; fine at the documented scale. `schedule/__init__.py:99-101` `runnable_jobs = (job for job in self.jobs if job.should_run)` (filter then sort due jobs)

### F5 Portability: 7 / target 9
- Strength: Pure Python with no platform calls in the library. absence: os/platform/subprocess use in schedule/ (grep -n 'import os\|subprocess\|platform' schedule/__init__.py)
- **F5-001** (minor): The package claims OS independence, but tests are Unix-only and CI runs Linux only. `test_schedule.py:30` `time.tzset()` (time.tzset() exists only on Unix, so the suite can't run on Windows); `.github/workflows/ci.yml:13` `runs-on: ubuntu-latest` (every CI job uses ubuntu)
- Action **F5-act-1** (M, → 9): Make the timezone tests skip time.tzset() on Windows (or use zoneinfo-based fixtures) and add windows-latest and macos-latest to the CI matrix

### F6 Dependency Health & Longevity: 5 / target 9
- Strength: Zero runtime dependencies; pytz is an optional extra. `pyproject.toml:13` `dependencies = []` (no install-time dependencies)
- **F6-001** (major): Builds will stop working with setuptools after 2027-02-18 (deprecated license metadata). `pyproject.toml:10` `license = {text = "MIT License"}` (TOML-table license is deprecated, as is the License classifier in setup.py); `python -m build` → `By 2027-Feb-18, you need to update your project and remove deprecated calls`
- **F6-002** (minor): Dev toolchain pinned to black 20.8b1 (2020), which has published advisories; no automated updates. `requirements-dev.txt:7` `black==20.8b1` (pinned formatter from 2020); `pip-audit -r requirements-dev.txt` → `black 20.8b1  PYSEC-2024-48   24.3.0`
- **F6-003** (minor): Still declares support for end-of-life Python 3.7 and 3.8. `setup.py:54` `python_requires=">=3.7",` (3.7 reached end of life in June 2023, 3.8 in October 2024)
- Action **F6-act-1** (S, → 7): Switch to `license = "MIT"` (SPDX) with `license-files`, drop the License classifier, and require setuptools>=77 in build-system
- Action **F6-act-2** (S, → 8): Upgrade black (and click pin) to a current release, reformat once, and add Dependabot for pip and GitHub Actions
- Action **F6-act-3** (S, → 9): Drop Python 3.7 and 3.8 from python_requires, classifiers, tox and CI; add 3.13 *Decision: Approve dropping Python 3.7 and 3.8 support in the next minor release?*

### X1 Accessibility, UX & Internationalization: –
*not_applicable*: Library with no user interface.

### X2 Public API Stability & Upgradeability: 7 / target 10
- Strength: Semantic versioning with a detailed changelog that calls out behavior-changing fixes. `HISTORY.rst:6` `1.2.2 (2024-05-25)` (dated releases)
- **X2-001** (minor): No explicit public surface or deprecation mechanism. absence: __all__ or warnings.warn deprecations in schedule/__init__.py (grep -n '__all__\|warnings' schedule/__init__.py)
- Action **X2-act-1** (S, → 9): Declare __all__ with the public API and add a short deprecation policy (DeprecationWarning for one minor release before removal) to the docs *Decision: Approve declaring __all__ (it changes what `from schedule import *` exports)?*

### X3 Concurrency Safety: 7 / target 8
*limited*: The scheduler is single-threaded by design; concurrency only arises when users run job bodies on threads, as the docs show.
- Strength: Thread usage is explicitly out of scope for the scheduler itself and the docs show safe patterns for running jobs on threads. `docs/index.rst:61` `* Concurrent execution (multiple threads)` (concurrency listed under 'When not to use')

### X4 Cost Efficiency: –
*not_applicable*: Runs in the user's process; no paid infrastructure or API calls.

### X5 Compliance & Licensing: 9 / target 9
- Strength: MIT license shipped in the sdist, zero runtime dependencies, and the optional pytz is MIT too. `MANIFEST.in:3` `include LICENSE.txt` (license included in the distribution)

### X6 Agent-Readiness: 5 / target 8
- Strength: tox gives one command per check, so an agent can verify a change. `tox.ini:2` `envlist = py3{7,8,9,10,11,12}{,-pytz}` (env list)
- **X6-001** (minor): No agent or contributor instructions with working commands. absence: AGENTS.md, CLAUDE.md, CONTRIBUTING.md (git ls-files)
- Action **X6-act-1** (S, → 8): Add AGENTS.md listing `tox -e py312`, `tox -e format`, `tox -e docs`, the one-file layout and the rule to update HISTORY.rst

## 10. Integrity flags, gaming flags and regressions

None found.

## 11. Limitations

- CI history of dbader/schedule wasn't visible from this session, so CI pass/fail, duration and whether the Python 3.7 job still finds a runner are unverified (F2, F5 confidence medium).
- No mutation testing or duplication tool was run; C2 and C4 rely on reading plus coverage.
- Single grader run (1 of 1); this report is the end-to-end test of the suite website, graded by the same agent that tested the site, not by an independent session.
- The project's project.toml was not yet merged to the grading repo's default branch, so the report branch is based on the setup branch.
- Hidden checks: none were run for this project.
