<!-- Part of the Code Grading Suite v4.2.1. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar D rubric: Value & Fitness for Purpose

*Does it do the right things, completely, in a way that makes sense in the real world?*

## D1. Feature Completeness
- **Measures:** Every feature the project claims or exposes (README, docs, CLI help, routes, UI, config options) is fully implemented and works end to end, with parity across surfaces (e.g. the CLI and the API both support it). No stubs, placeholder UI, dead buttons, `NotImplementedError` or half-wired flags.
- **Not this:** Features that are *missing* but expected (D2).
- **Assess:** Build a **feature inventory** from your recon list and give each feature a status: `complete`, `partial`, `stub`, `broken` or `undocumented`. Exercise each one, or as many as practical.
- **Anchors:**
  - **1–3:** Most claimed features broken or stubbed.
  - **4–6:** Core features work; several partial.
  - **7–8:** Nearly everything complete; minor rough edges.
  - **9–10:** Everything claimed works end to end, matches the docs, and is covered by tests.
- **Caps:** Any advertised core feature that is missing or broken → max 5.

## D2. Gap Coverage
- **Measures:** Absence of gaps. A gap is something the project's purpose clearly needs, or that users of this kind of software would reasonably expect, but that is missing. Examples: an auth system without password reset, a CLI without `--help` or meaningful exit codes, an API without pagination or rate-limit handling, a data tool without export, a destructive action without confirm or undo, a service without health checks, a missing platform the project says it supports.
- **Not this:** Unfinished *existing* features (D1). A wishlist; feature creep is not rewarded.
- **Assess:** Compare against the stated requirements, the domain's norms and 1–3 peer tools. Build a **gap register**. Mark each gap with a severity (`critical`, `major`, `minor`) and a necessity (`must-have` or `nice-to-have`) relative to the project's purpose.
- **Anchors:**
  - **1–3:** Missing essentials that make it unfit for purpose.
  - **4–6:** Several major gaps.
  - **7–8:** Only minor or nice-to-have gaps.
  - **9–10:** Nothing a reasonable user would miss; scope boundaries are documented.
- **Caps:** Any critical gap → max 4.

## D3. Practicality
- **Measures:** Pragmatic fitness for purpose:
  - Technology choices suit the team, scale and budget (no Kubernetes cluster for a nightly cron job, no hand-written ORM where a standard one works).
  - It works with realistic data volumes, real network conditions and real user workflows, not just demo data.
  - Trade-offs are made consciously.
  - Operating cost and effort are proportional to the value delivered.
  - No gold-plating, and no purity that gets in the way of delivering value.
- **Not this:** Code-level leanness (B6). Architecture quality as such (B1).
- **Assess:** Ask: "Would an experienced team adopt and run this as-is? What would they rip out or bolt on in the first week?" Test with realistic inputs where possible.
- **Anchors:**
  - **1–3:** Impractical: wrong tools, or only works in a demo.
  - **4–6:** Usable but awkward or over-built in places.
  - **7–8:** Sensible, grounded choices.
  - **9–10:** Every choice clearly serves the real use case, and the trade-offs are documented.

## D4. Intuitiveness
- **Measures:** Least surprise, for end users *and* developers. Sensible defaults; names that match the domain's vocabulary; consistent behavior across similar operations; discoverability (help text, completions, clear flags, resources and menus); error messages that say what to do next; no hidden modes, ordering traps or surprising side effects; it behaves the way users of similar tools expect.
- **Not this:** Onboarding and time-to-first-success (E1). Docs content (E2).
- **Assess:** Do 3–5 common tasks as a first-time user without reading the source. Log every surprise, guess and dead end.
- **Anchors:**
  - **1–3:** Confusing; users must read the source.
  - **4–6:** Learnable, with friction and several gotchas.
  - **7–8:** Mostly obvious.
  - **9–10:** Users succeed on the first try and the behavior feels inevitable.
