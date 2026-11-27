<!-- Part of the Code Grading Suite v6.0.0. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar C rubric: Code Health

*Is the code itself pleasant and safe to work in day to day?*

## C1. Readability & Consistency
- **Measures:** How quickly a competent newcomer understands the code, and how uniform it is. Intent-revealing names; clear control flow; no magic numbers; comments that explain *why*; no cleverness for its own sake. Uniform conventions across the codebase (naming, error patterns, formatting, file shape), and idiomatic use of the language and framework rather than patterns carried over from somewhere else.
- **Not this:** Codebase-level navigability (B3). Function length, nesting and complexity (C2). Which tools a contributor uses (E3), and whether CI enforces them (F2).
- **Assess:** Read core modules cold, and compare modules from different eras or authors. Note cryptic names, misleading comments, non-idiomatic constructs and hand-rolled standard features. Run the formatter and linter in check mode.
- **Anchors:**
  - **1–3:** Cryptic; every file looks different.
  - **4–6:** Readable with effort; pockets of divergence.
  - **7–8:** Generally clear, consistent and idiomatic.
  - **9–10:** Reads like well-written prose by one expert; conventions are enforced by tooling.
- **Re-grade:** any source change

## C2. Maintainability & Complexity
- **Measures:** How cheap and safe changes are at the code level: duplication, function length and nesting depth, cyclomatic and cognitive complexity, change amplification, TODO/FIXME debt, stale feature flags, and hotspots (high churn × high complexity).
- **Not this:** Dead code and bloat (B6). Architectural coupling (B1, B2).
- **Assess:** Run complexity and duplication tools (`radon`, `lizard`, `jscpd`, `gocyclo`...). Note functions over about 50 lines and nesting of 4+ levels. Use `git log` to find churn hotspots and cross-reference them with complexity. Count and sample TODOs.
- **Anchors:**
  - **1–3:** Widespread copy-paste; extreme complexity.
  - **4–6:** Several complexity hotspots; noticeable duplication.
  - **7–8:** Complexity confined to a few justified places.
  - **9–10:** Small, focused units; complexity thresholds enforced in tooling.
- **Re-grade:** any source change

## C4. Test Suite Quality
- **Measures:** Whether the tests would actually catch regressions: meaningful assertions; the right mix of unit, integration, contract and end-to-end tests; property or fuzz tests where valuable; coverage of critical and failure paths; speed; and determinism, with time, randomness, ordering and environment injected or controlled rather than hidden, so tests can pin them.
- **Not this:** Whether the code is correct (A1). Tests are evidence for A1, not a substitute for it.
- **Assess:** Run the suite with coverage, twice. Read a sample of tests for assertion quality. Find flakiness sources (sleeps, real network calls, shared state, order dependence, unseeded randomness, `now()` called deep inside logic). Mentally mutate core logic, or run a mutation-testing tool: do tests fail?
- **Anchors:**
  - **1–3:** No tests, or useless ones.
  - **4–6:** Some value; big gaps; heavy mocking.
  - **7–8:** Critical paths well tested; roughly 70%+ branch coverage on core logic; deterministic.
  - **9–10:** Tests read as a specification; failure paths covered; mutations caught; no flaky tests; gated in CI.
- **Caps:** Tests not run in CI → max 7 (`C4-cap-1`). Coverage inflated by assertion-free tests → max 4 (`C4-cap-2`).
- **Re-grade:** any source change
