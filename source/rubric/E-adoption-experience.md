<!-- Part of the Code Grading Suite v6.0.0. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

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
- **Not this:** The contributor experience (E3). Docs accuracy beyond the quickstart (E2).
- **Assess:** From a clean environment, follow the quickstart literally. Count the steps, minutes and stumbles to the first meaningful result. A quickstart that needs something the documented install doesn't provide (an extra package, a system library) fails as written.
- **Anchors:**
  - **1–3:** Can't get started without help from the author.
  - **4–6:** Gets working after real effort.
  - **7–8:** Smooth start within minutes.
  - **9–10:** Delightful; examples cover the main use cases, and the quickstart is tested in CI.
- **Caps:** Quickstart fails → max 4 (`E1-cap-1`). No license in a distributed or open project → max 5 (`E1-cap-2`).

## E2. Documentation
- **Measures:** Quality and accuracy of the documentation at every layer: README (purpose, setup, usage, configuration), API reference, architecture overview, decision records, runbooks, changelog, and inline comments explaining *why*. Above all, docs must match the code.
- **Not this:** The onboarding experience, including a quickstart that fails (E1). Contributor setup, test commands and agent instructions, even where they're documented (E3).
- **Assess:** Do the same checks every time, so graders find the same things:
  - **Run every example** in the README and the main usage guide, as written, in a clean environment. Reading them isn't enough.
  - **Compare the API reference with the public names in the code:** what's missing, and what's documented but gone.
  - **Check five documented behaviors** that users rely on (defaults, error handling, timing, limits) against the code.
  - **Severity of a docs error:** `major` when following the docs gives a wrong program, or a failure with no obvious fix. A wrong program includes one that runs without an error but does something other than the docs say: a wrong stated result, time, value or default in a behavior users rely on. Otherwise `minor` (a typo, a stale date whose error makes the fix plain, a missing name). A clear error with no way to do what the docs promise is still `major`.
  - `E2-cap-1` is for instructions and documented behavior users rely on to install, configure or use the project, beyond the quickstart (a failing quickstart is `E1-cap-1`). A contributor setup that fails is E3.
- **Anchors:**
  - **1–3:** Missing or misleading.
  - **4–6:** Basic, with gaps and stale parts: an example fails in a way that misleads, a behavior users rely on is stated wrongly, or much of the public API is undocumented.
  - **7–8:** Accurate and covers the essentials: the examples run as written (or fail only with a clear, self-explaining error, such as a stale date), and nothing users rely on is stated wrongly. Minor slips are allowed: 8 has at most one or two, 7 a few.
  - **9–10:** Complete and layered; versioned with the code and verified (doc tests, examples run in CI, generated references).
- **Caps:** Docs misstate how to install, configure or use the project, beyond the quickstart → max 5 (`E2-cap-1`).

## E3. Contributor & Agent Experience
- **Measures:** How productive a *contributor*, a person or an AI coding agent, is day to day:
  - One-command dev setup through the ecosystem's standard package manager and manifest (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, Gradle/Maven...).
  - The standard test runner, formatter and linter, and the conventional project layout, rather than bespoke scripts that reinvent the toolchain.
  - A fast edit-build-test cycle, easy single-test runs, and a local environment that matches production (compose file, devcontainer, Nix...), plus seed data.
  - A working debugger, and IDE and language-server integration.
  - Discoverable task scripts (`make`, `just`, npm scripts) and a contribution guide.
  - Instructions an agent can follow: an `AGENTS.md`, `CLAUDE.md` or equivalent with exact build, test, lint and run commands, the conventions and module boundaries written down, and generated or protected files marked.
  - Clear signals of success and failure (exit codes, machine-readable output), and fast CI feedback.
- **Not this:** The outsider-adopter experience (E1). Code-level idiom (C1). Whether CI blocks merges (F2). Publishing artifacts (F1).
- **Assess:** Measure time from clone to passing tests, time to run one test, incremental build time, and how many undocumented steps you hit. Inventory the build, test, lint, format and task tools, and flag each custom tool where a standard exists without a documented reason. Ask whether an agent with no prior context could make a correct, verified change from the repo alone. A documented dev setup or test command that fails is an E3 finding, not an E2 one.
- **Anchors:**
  - **1–3:** Painful setup; slow loops; a homegrown toolchain that fights the ecosystem.
  - **4–6:** Workable with tribal knowledge; several bespoke pieces.
  - **7–8:** Quick setup with standard tools; fast loops; the main tasks are written down.
  - **9–10:** Productive within an hour of cloning, for people and agents alike: the inner loop takes seconds, and the instructions give the exact commands.
- **Caps:** A custom build or test harness where a standard exists, with no documented reason → max 6 (`E3-cap-1`).
- **Scope:** repo
