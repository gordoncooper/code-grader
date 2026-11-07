<!-- Part of the Code Grading Suite v4.2.1. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar C rubric: Code Health

*Is the code itself pleasant and safe to work in day to day?*

## C1. Readability & Clarity
- **Measures:** How quickly a competent newcomer understands the code: intent-revealing names, small functions, shallow nesting, clear control flow, no magic numbers, comments that explain *why*, no cleverness for its own sake.
- **Not this:** Codebase-level navigability (B3). Style uniformity (C3).
- **Assess:** Read core modules cold. Note functions over about 50 lines, nesting of 4+ levels, cryptic names and misleading comments.
- **Anchors:**
  - **1–3:** Cryptic.
  - **4–6:** Readable with effort.
  - **7–8:** Generally clear.
  - **9–10:** Reads like well-written prose.

## C2. Maintainability & Complexity
- **Measures:** How cheap and safe changes are at the code level: duplication, cyclomatic and cognitive complexity, change amplification, TODO/FIXME debt, stale feature flags, and hotspots (high churn × high complexity).
- **Not this:** Dead code and bloat (B6). Architectural coupling (B1, B2).
- **Assess:** Run complexity and duplication tools (`radon`, `lizard`, `jscpd`, `gocyclo`...). Use `git log` to find churn hotspots and cross-reference them with complexity. Count and sample TODOs.
- **Anchors:**
  - **1–3:** Widespread copy-paste; extreme complexity.
  - **4–6:** Several complexity hotspots; noticeable duplication.
  - **7–8:** Complexity confined to a few justified places.
  - **9–10:** Small, focused units; complexity thresholds enforced in tooling.

## C3. Consistency & Idiomatic Code
- **Measures:** Uniform conventions across the codebase (naming, error patterns, formatting, file shape) and idiomatic use of the language and framework, rather than patterns carried over from somewhere else.
- **Not this:** Use of the ecosystem's *tooling* (E4).
- **Assess:** Compare modules from different eras or authors. Run the formatter in check mode. Note non-idiomatic constructs and hand-rolled standard features.
- **Anchors:**
  - **1–3:** Every file looks different.
  - **4–6:** Pockets of divergence.
  - **7–8:** Consistent and idiomatic.
  - **9–10:** Looks written by one expert; conventions enforced by tooling.

## C4. Test Suite Quality
- **Measures:** Whether the tests would actually catch regressions: meaningful assertions; the right mix of unit, integration, contract and end-to-end tests; property or fuzz tests where valuable; determinism and speed; coverage of critical and failure paths.
- **Not this:** Whether the code is correct (A1). Tests are evidence for A1, not a substitute for it.
- **Assess:** Run the suite with coverage. Read a sample of tests for assertion quality. Find flakiness sources (sleeps, real network calls, shared state, order dependence). Mentally mutate core logic, or run a mutation-testing tool: do tests fail?
- **Anchors:**
  - **1–3:** No tests, or useless ones.
  - **4–6:** Some value; big gaps; heavy mocking.
  - **7–8:** Critical paths well tested; roughly 70%+ branch coverage on core logic; deterministic.
  - **9–10:** Tests read as a specification; failure paths covered; mutations caught; gated in CI.
- **Caps:** Tests not run in CI → max 7. Coverage inflated by assertion-free tests → max 4.
