<!-- Part of the Code Grading Suite v5.0.1. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar F rubric: Operations & Delivery

*Can it be shipped, run, observed and kept healthy over time?*

## F1. Ease of Deployability
- **Measures:** The path from merged code to running in an environment:
  - Automated or one-command deploy.
  - A packaged, immutable artifact (container image or package).
  - Infrastructure as code.
  - Configuration externalized and validated at startup.
  - Proper secrets management.
  - Parity between environments.
  - Health and readiness checks.
  - Migrations integrated into the deploy.
  - Zero-downtime deploys and rollback where relevant.
  - A documented runbook.
  - For libraries and CLIs, "deploy" means release and publish, and installing the published artifact.
- **Not this:** CI checks and gates (F2). Whether operations are safe to repeat (A4).
- **Assess:** Follow the deploy or release process on paper, or for real if possible. Count manual steps. Find hard-coded environment values. Check for a rollback path.
- **Anchors:**
  - **1–3:** Deploying needs the author and code edits.
  - **4–6:** Scripted but fragile; manual steps.
  - **7–8:** Automated and repeatable; documented.
  - **9–10:** Push-button or continuous; a new environment needs no code changes; rollback is fast and tested.
- **Caps:** Manual, undocumented deploy steps → max 4 (`F1-cap-1`). No rollback path for a production service → max 6 (`F1-cap-2`).

## F2. Build, CI/CD & Automation
- **Measures:** Reproducible builds; automated format, lint, type and test checks; CI that blocks merges on failure; caching and speed; automated releases and versioning; pre-commit hooks.
- **Not this:** Which tools are used (E4). Deploy mechanics (F1).
- **Assess:** Inspect the CI config. Which checks run, and do they block merges? Measure CI duration if visible.
- **Anchors:**
  - **1–3:** No CI.
  - **4–6:** CI runs but doesn't block merges.
  - **7–8:** Full gating.
  - **9–10:** Fast, cached, comprehensive pipeline; releases fully automated.

## F3. Observability & Debuggability
- **Measures:** You can tell what the system is doing and diagnose problems without attaching a debugger. Structured, leveled logs; correlation or request IDs; metrics; tracing where relevant; health endpoints; actionable error output; and no secrets or PII in telemetry. For a CLI: clear errors, verbose and debug modes, meaningful exit codes.
- **Assess:** Pick a realistic failure in a core flow. Would the logs and metrics be enough to diagnose it? For a library, which has no telemetry of its own, F3 is `limited`: grade its error messages and exceptions, and whether it logs through the host's logging, with levels.
- **Anchors:**
  - **1–3:** Failures are opaque.
  - **4–6:** Some logging; inconsistent.
  - **7–8:** Structured logs with context, plus key metrics.
  - **9–10:** Any production issue can be diagnosed from telemetry alone; signals are documented, and alerting exists where relevant.

## F4. Performance, Efficiency & Scalability
- **Measures:** Appropriate algorithms and data structures; efficient I/O (no N+1 queries; batching and streaming); sensible memory and CPU use; caching where justified; no blocking calls in async code; no unbounded growth; graceful behavior at 10× expected load; optimization based on measurement.
- **Assess:** Review the busiest code paths. Look for queries inside loops, whole datasets loaded into memory, missing indexes and quadratic loops over large inputs. Run benchmarks or profilers if they exist.
- **Anchors:**
  - **1–3:** Will fail at expected scale.
  - **4–6:** OK now; clear inefficiencies.
  - **7–8:** Efficient busy paths; no known scaling cliffs.
  - **9–10:** Performance budgets defined and guarded by benchmarks or load tests in CI, without hurting clarity.

## F5. Portability
- **Measures:** Runs correctly across every operating system, CPU architecture, runtime version, browser or cloud the project claims to support. No hard-coded absolute paths, path-separator or shell assumptions, locale, timezone or encoding assumptions, or machine-specific config. The supported matrix is declared *and* tested.
- **Assess:** Search for absolute paths, `/` vs `\` handling, shelling out to platform-specific tools, and dependence on the system timezone or locale. Check whether CI covers the claimed matrix.
- **Anchors:**
  - **1–3:** Works only on the author's machine.
  - **4–6:** Works on one platform; others break.
  - **7–8:** Works on the claimed platforms, partly tested.
  - **9–10:** The full declared matrix is tested in CI.
- **Caps:** Machine-specific assumptions in core paths → max 4 (`F5-cap-1`).

## F6. Dependency Health & Longevity
- **Measures:** Dependencies are pinned and locked, maintained, minimal and license-compatible, and the project resists bit rot: runtime and framework versions are within their support windows, no deprecated APIs, the toolchain is pinned, and updates are automated.
- **Not this:** *Reachable* vulnerabilities (A2). *Unused* dependencies (B6).
- **Assess:** Inspect manifests and lockfiles. Run outdated and audit checks. Check end-of-life dates for the runtime and major frameworks. Grep for deprecation warnings in build and test output.
- **Anchors:**
  - **1–3:** Unpinned, abandoned or end-of-life.
  - **4–6:** Locked but stale.
  - **7–8:** Current and pinned.
  - **9–10:** Automated updates (Renovate, Dependabot) with audit gates; no deprecations; would still build cleanly a year from now.
