<!-- Part of the Code Grading Suite v4.2.2. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar E rubric: Adoption & Experience

*How easy is it for new users, integrators and contributors to pick up and work with?*

## E1. Adopter Friendliness
- **Measures:** Time-to-first-success for someone *adopting* the project (end user, integrator, library consumer, new operator). Covers:
  - Installing through standard channels.
  - A quickstart that actually works.
  - Runnable examples.
  - Zero-config or sensible defaults.
  - A clear license.
  - A supported-versions or compatibility matrix.
  - Upgrade and migration guides.
  - Issue and support paths.
  - Low integration friction with common stacks.
  - No lock-in surprises.
- **Not this:** The contributor experience (E3). Docs accuracy in general (E2).
- **Assess:** From a clean environment, follow the quickstart literally. Count the steps, minutes and stumbles to the first meaningful result.
- **Anchors:**
  - **1–3:** Can't get started without help from the author.
  - **4–6:** Gets working after real effort.
  - **7–8:** Smooth start within minutes.
  - **9–10:** Delightful; examples cover the main use cases, and the quickstart is tested in CI.
- **Caps:** Quickstart fails → max 4. No license in a distributed or open project → max 5.

## E2. Documentation
- **Measures:** Quality and accuracy of the documentation at every layer: README (purpose, setup, usage, configuration), API reference, architecture overview, decision records, runbooks, changelog, and inline comments explaining *why*. Above all, docs must match the code.
- **Not this:** The onboarding experience (E1). Agent-specific instructions (X6).
- **Assess:** Spot-check documented behavior against the code. Check coverage of public APIs and config options. Look for stale sections.
- **Anchors:**
  - **1–3:** Missing or misleading.
  - **4–6:** Basic, with gaps and stale parts.
  - **7–8:** Accurate and covers the essentials.
  - **9–10:** Complete and layered; versioned with the code and verified (doc tests, examples run in CI, generated references).
- **Caps:** Wrong setup instructions → max 5.

## E3. Developer Experience & Inner Loop
- **Measures:** How productive a *contributor* is day to day:
  - One-command dev setup.
  - Fast edit-build-test cycle, with hot reload where relevant.
  - Easy single-test runs.
  - Local environment that matches production (compose file, devcontainer, Nix...), plus seed data.
  - A working debugger.
  - Discoverable task scripts (`make`, `just`, npm scripts).
  - A contribution guide.
  - Fast CI feedback.
- **Not this:** The outsider-adopter experience (E1). Choice of standard toolchain (E4).
- **Assess:** Measure time from clone to passing tests, time to run one test, incremental build time, and how many undocumented steps you hit.
- **Anchors:**
  - **1–3:** Painful setup; slow loops.
  - **4–6:** Workable with tribal knowledge.
  - **7–8:** Quick setup; fast loops.
  - **9–10:** Productive within an hour of cloning; inner loop measured in seconds.

## E4. Native Tooling & Ecosystem Fit
- **Measures:** The project uses its ecosystem's standard tools and conventions rather than bespoke ones:
  - The native package manager and manifest (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, Gradle/Maven...).
  - The standard test runner, formatter and linter.
  - The conventional project layout.
  - Built-in language features and the standard library over custom scripts.
  - Publishing in native formats (wheel, crate, npm package, OCI image).
  - Working IDE and language-server integration.
  - No sprawl of shell scripts that reinvent what the toolchain already does.
- **Not this:** Code-level idiom (C3).
- **Assess:** Inventory the build, test, lint, format, release and task-running tools. Flag each custom tool where a standard exists, and check whether a documented reason is given.
- **Anchors:**
  - **1–3:** A homegrown toolchain that fights the ecosystem.
  - **4–6:** Mixed; several bespoke pieces.
  - **7–8:** Standard tools used throughout.
  - **9–10:** Feels native; any ecosystem developer is productive immediately with tools they already know.
- **Caps:** A custom build or test harness where a standard exists, with no documented reason → max 6.
