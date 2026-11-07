<!-- Part of the Code Grading Suite v3.1.0. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Conditional benchmarks rubric

## X1. Accessibility, UX & Internationalization (*UI code*)
- **Measures:** Semantic markup; keyboard navigation; focus management; correct ARIA; color contrast; screen-reader labels; responsive layout; loading, empty and error states; text externalized for translation; locale-aware formatting; right-to-left readiness where relevant.
- **Assess:** Run axe or Lighthouse, then do a keyboard-only pass through core flows.
- **Caps:** Core flows not keyboard-operable → max 4.

## X2. Public API Stability & Upgradeability (*libraries, SDKs, public APIs*)
- **Measures:** Semantic versioning, a changelog, a deprecation policy with warnings, backward-compatibility tests, a minimal public surface, a clear split between public and internal code, and migration guides for breaking changes.
- **Caps:** Breaking changes shipped in minor or patch releases → max 4.

## X3. Concurrency Safety (*concurrent, parallel or async code*)
- **Measures:** Shared state is protected; no races, deadlocks or unawaited promises; no blocking the event loop; cancellation is propagated; parallelism is bounded. Race detectors or stress tests are used (`go test -race`, TSan, loom...).
- **Caps:** A demonstrable data race on shared mutable state → max 3.

## X4. Cost Efficiency (*code that runs on paid infrastructure or APIs*)
- **Measures:** Resources are right-sized; autoscaling and scale-to-zero where sensible; no runaway loops calling paid APIs; caching of expensive calls; storage lifecycle policies; resources tagged and costs visible; budget alerts.

## X5. Compliance & Licensing (*regulated data, or distributed software*)
- **Measures:** Dependency licenses are compatible; an SBOM can be generated; audit logs exist for sensitive actions; data residency and retention controls; controls required by any applicable regimes (GDPR, HIPAA, SOC 2, PCI...) are present and documented.

## X6. Agent-Readiness (*graded by default in this workflow, because agents will maintain the code*)
- **Measures:** An AI coding agent can work on this codebase safely and productively:
  - An `AGENTS.md`, `CLAUDE.md` or equivalent with exact build, test, lint and run commands.
  - Fast, scoped, deterministic verification commands.
  - Conventions and module boundaries written down.
  - No tribal knowledge needed to make a correct change.
  - Generated and protected files clearly marked.
  - Clear signals of success and failure (exit codes, machine-readable output).
- **Assess:** Could an agent with no prior context make a correct, verified change from the repo alone?
