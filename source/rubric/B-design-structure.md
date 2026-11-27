<!-- Part of the Code Grading Suite v6.0.0. Read together with prompts/grader.md, which holds the scoring rules, anti-gaming rules and output format. -->

# Pillar B rubric: Design & Structure

*Is the system shaped well, and does that shape stay easy to change?*

## B1. Architecture & Design Fitness
- **Measures:** The overall shape suits the problem: clear layering, correct dependency direction (domain logic doesn't depend on frameworks or I/O), consistent patterns, important decisions recorded, and a design that meets the requirements the project actually has. The technology suits the problem, the team and the budget (no Kubernetes cluster for a nightly cron job, no hand-written ORM where a standard one works), and trade-offs are made consciously.
- **Not this:** Boundaries of individual units (B2). Physical file layout (B3). Building more than the purpose needs (B6). Behavior at realistic data volumes and load (F4).
- **Assess:** Sketch the system's components and data flow. Look for business logic in controllers, views or SQL, framework types leaking into the domain, and mismatched architecture (e.g. microservices for a tiny app, or a monolith that's tangling under real load). Ask what an experienced team would rip out or bolt on in its first week.
- **Anchors:**
  - **1–3:** No discernible design, or technology that fights the problem.
  - **4–6:** Some structure; frequent layer violations; some choices that don't fit.
  - **7–8:** Clear, fitting design with a few leaks.
  - **9–10:** The design is obvious, fits the problem precisely, has recorded rationale, and its boundaries are enforced by import rules or package visibility.

## B2. Modularity & Decoupling
- **Measures:** Units are cohesive, loosely coupled, encapsulated, replaceable and testable in isolation. No dependency cycles, no hidden global state, and explicit seams (dependency injection) at I/O boundaries.
- **Not this:** System-level fit (B1). Where files live (B3).
- **Assess:** Build the module dependency graph. Count cycles, god modules, and fan-in and fan-out hotspots. Pick 3 modules and ask whether each could be replaced or tested alone.
- **Anchors:**
  - **1–3:** Big ball of mud.
  - **4–6:** Some modules; heavy coupling; god files.
  - **7–8:** Clean boundaries; coupling controlled.
  - **9–10:** Every unit has one clear job and a narrow interface; replacing one touches only its seam.
- **Caps:** Circular dependencies between major modules → max 5 (`B2-cap-1`).

## B3. Structure & Organization
- **Measures:** The codebase is easy to navigate. Directory layout reflects the domain or architecture; things live where you'd expect; file and folder names are consistent; source, tests, scripts, config and docs are separated; no junk-drawer `utils/` or `misc/`; generated code is isolated. Repo hygiene: `.gitignore` is correct, and no build artifacts or large binaries are committed.
- **Not this:** Logical coupling (B2). Committed secrets (A2).
- **Assess:** Pick 5 concepts (e.g. "where is pricing calculated?", "where are the DB models?") and note how quickly and confidently each can be found. Inspect the top two levels of the tree and the tracked files.
- **Anchors:**
  - **1–3:** Chaotic; things scattered.
  - **4–6:** Partly organized; several misplaced or junk-drawer areas.
  - **7–8:** Predictable and tidy.
  - **9–10:** A newcomer can guess where anything lives; the layout is documented and stays consistent.
- **Scope:** repo

## B4. Interface Design & Contracts
- **Measures:** Public and internal APIs (functions, classes, HTTP/gRPC/GraphQL endpoints, CLI arguments, events, schemas) have clear contracts, are hard to misuse, follow consistent conventions, are strongly typed or validated at runtime, and make invalid states unrepresentable.
- **Not this:** Long-term version stability for outside consumers (X2). How intuitive the interface feels to end users (D4).
- **Assess:** Run the type checker at strict settings and count escape hatches. Review signatures for boolean-flag parameters, stringly-typed values, nullable confusion, and inconsistent naming, pagination or error shapes across endpoints. Check that schemas are validated at boundaries.
- **Anchors:**
  - **1–3:** Untyped or loosely typed; surprising contracts.
  - **4–6:** Partial typing; frequent escape hatches.
  - **7–8:** Strong contracts; few justified escape hatches.
  - **9–10:** Strict mode passes; domain types model the problem; schemas are the source of truth and are checked automatically.

## B5. Flexibility & Extensibility
- **Measures:** Likely changes can be made without invasive edits. Things that vary are config rather than code; extension points (plugins, hooks, strategies, adapters) exist *where there is real demand*; no hard-coded assumptions that limit growth (single tenant, one currency or locale, one region, one storage backend); feature flags where they help.
- **Not this:** Speculative over-engineering is penalized under Leanness (B6). Flexibility should be earned by likely change, not imagined change. Coupling between modules in general (B2): a hard-wired choice that a likely change has to replace (one backend, one unit system, one locale) is B5's; coupling that makes unrelated changes ripple is B2's.
- **Assess:** Take 3 likely change requests from the project itself: its open issues and feature requests, its roadmap or changelog, or what its docs say users ask for. Invent one only when the project gives none, and say so in the rationale. For each, trace the blast radius: the files and functions it touches, and the risk involved. Name the 3 changes in the rationale, so the score can be checked.
- **Anchors:**
  - **1–3:** Every change ripples through the codebase.
  - **4–6:** Some changes are localized; others need shotgun surgery.
  - **7–8:** Most likely changes touch 1–3 places.
  - **9–10:** Likely changes are additive and localized, with no unused extension points.

## B6. Leanness
- **Measures:** No more code, dependencies, configuration, features or runtime weight than the job needs. Covers dead code, unused exports and files, unused or redundant dependencies, speculative abstractions and layers, gold-plating (features, options and polish beyond what the purpose needs), reinventing what the standard library already provides, oversized bundles, binaries or images, slow startup, and a bloated configuration surface.
- **Not this:** Duplication and complexity (C2). Operating cost (X4). Removing needed features is **not** leanness (anti-gaming).
- **Assess:** Run unused-code and unused-dependency tools (`knip`, `ts-prune`, `depcheck`, `vulture`, `cargo-udeps`, `deadcode`...). Measure bundle, image or binary size and startup time. Count abstraction layers per request path. Compare code size per feature to comparable tools.
- **Anchors:**
  - **1–3:** Heavy bloat; large dead areas; dependency sprawl.
  - **4–6:** Noticeable dead code, unused dependencies or needless layers.
  - **7–8:** Tight, with a few leftovers.
  - **9–10:** Every file, dependency and abstraction earns its place; size and dead code are checked in CI.
