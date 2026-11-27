<!-- Part of the Code Grading Suite v6.0.0. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar X rubric: Conditional

*Graded only where they apply: each one names the kind of code it covers.*

*A benchmark here without anchors of its own is scored on this scale:*
- **1–3:** Absent, or harmful where it matters.
- **4–6:** Present but partial, with real gaps.
- **7–8:** Solid for this project's needs; minor gaps.
- **9–10:** Thorough, automated where it can be, and verified.

## X1. Accessibility, UX & Internationalization (*UI code*)
- **Measures:** Semantic markup; keyboard navigation; focus management; correct ARIA; color contrast; screen-reader labels; responsive layout; loading, empty and error states; text externalized for translation; locale-aware formatting; right-to-left readiness where relevant.
- **Assess:** Run axe or Lighthouse, then do a keyboard-only pass through core flows.
- **Caps:** Core flows not keyboard-operable → max 4 (`X1-cap-1`).

## X2. Public API Stability & Upgradeability (*libraries, SDKs, public APIs*)
- **Measures:** Semantic versioning, a changelog that is honest about breaking changes, a deprecation policy with warnings, backward-compatibility tests, a minimal public surface, a clear split between public and internal code, and migration guides for breaking changes.
- **Not this:** The changelog's quality as documentation (E2).
- **Assess:** Do the same checks every time, so graders find the same things:
  - **Find the public API:** what the docs and the API reference present, plus what the language's conventions make public (names without a leading underscore in Python, exported names in Go and JavaScript or TypeScript, `pub` items in Rust), unless the project marks it internal.
  - **Compare it with the previous release's:** diff the public names and signatures between the last two release tags, and between the last tag and this commit. A public name that's removed, or whose signature or behavior changes incompatibly, is a breaking change; check that the version number and the changelog say so.
  - Look for deprecation warnings that name a replacement and a removal version, and for tests that pin old behavior.
- **Anchors:**
  - **1–3:** No versioning discipline: breaking changes arrive unannounced, and nothing separates public from internal.
  - **4–6:** Versioned, but breaking changes reach minor or patch releases or go unmentioned in the changelog; deprecations are rare or silent.
  - **7–8:** Semantic versioning followed: breaking changes come with a major version, a changelog entry and a deprecation period first.
  - **9–10:** All of that, with a small, explicitly marked public surface, API compatibility checks in CI, and migration guides.
- **Caps:** Breaking changes shipped in minor or patch releases → max 4 (`X2-cap-1`).

## X3. Concurrency Safety (*concurrent, parallel or async code*)
- **Measures:** Shared state is protected; no races, deadlocks or unawaited promises; no blocking the event loop; cancellation is propagated; parallelism is bounded. Race detectors or stress tests are used (`go test -race`, TSan, loom...).
- **Assess:** `limited` for code that isn't concurrent itself but is commonly called from threads or async code, or whose docs show it used that way: grade what it promises about thread safety, and whether it says where it isn't safe. `not_applicable` only when neither the code nor its documented use is concurrent.
- **Caps:** A demonstrable data race on shared mutable state → max 3 (`X3-cap-1`).

## X4. Cost Efficiency (*code that runs on paid infrastructure or APIs*)
- **Measures:** Operating cost and effort are proportional to the value delivered. Resources are right-sized; autoscaling and scale-to-zero where sensible; no runaway loops calling paid APIs; caching of expensive calls; storage lifecycle policies; resources tagged and costs visible; budget alerts.

## X5. Compliance & Licensing (*regulated data, or distributed software*)
- **Measures:** Dependency licenses are compatible; an SBOM can be generated; audit logs exist for sensitive actions; data residency and retention controls; controls required by any applicable regimes (GDPR, HIPAA, SOC 2, PCI...) are present and documented.
- **Assess:** For distributed software that doesn't handle regulated data, grade the licensing part only: a license file, the license declared in the package metadata, dependency licenses compatible with it and with how the software is distributed, and whether an SBOM can be generated. The data controls apply only to code that handles regulated data. Score what applies; the parts that don't apply don't make it `limited`.
- **Anchors:**
  - **1–3:** No license, or dependencies whose licenses forbid how the software is distributed; required controls missing.
  - **4–6:** Licensed, but the metadata, notices or required controls are missing or inconsistent.
  - **7–8:** The license is clear and declared, dependency licenses are checked, and the required controls are present.
  - **9–10:** License checks and SBOM generation run in CI; the required controls are documented and audited.
