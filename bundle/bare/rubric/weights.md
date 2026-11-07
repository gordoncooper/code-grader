<!-- Part of the Code Grading Suite v3.1.0. `weights.json` is the source of truth; this table is generated from it. If they ever disagree, weights.json wins. -->

# Weights, targets and maturity levels

## Weights by project profile

Pick the column that matches the project profile in the project context. Weights run from 1 (minor) to 3 (critical). These are *starting* weights:

- `full` applicability → use the profile weight.
- `limited` applicability → weight drops to 1 (or stays at its profile weight if that is already 1).
- `not_applicable` → excluded from every average.

If a weight looks wrong for this codebase, keep it, but add a `weight_note` with the weight you'd recommend. The person running the suite decides whether to change it. `gradekit.py rollup` checks that every weight used matches these rules and flags any that don't.

| ID | Benchmark | Default | Library | Service/API | Web app | CLI | Prototype |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|
| A1 | Correctness & Functional Behavior | 3 | 3 | 3 | 3 | 3 | 2 |
| A2 | Security & Privacy | 3 | 2 | 3 | 3 | 2 | 1 |
| A3 | Robustness & Error Handling | 2 | 2 | 3 | 2 | 2 | 1 |
| A4 | Idempotence & Determinism | 2 | 1 | 3 | 2 | 2 | 1 |
| A5 | Durability & Recoverability | 2 | 1 | 3 | 2 | 1 | 1 |
| B1 | Architecture & Design Fitness | 2 | 2 | 2 | 2 | 1 | 1 |
| B2 | Modularity & Decoupling | 2 | 3 | 2 | 2 | 1 | 1 |
| B3 | Structure & Organization | 1 | 1 | 1 | 1 | 1 | 1 |
| B4 | Interface Design & Contracts | 2 | 3 | 2 | 2 | 2 | 1 |
| B5 | Flexibility & Extensibility | 1 | 2 | 1 | 1 | 1 | 1 |
| B6 | Leanness | 2 | 2 | 1 | 2 | 2 | 2 |
| C1 | Readability & Clarity | 2 | 2 | 2 | 2 | 2 | 2 |
| C2 | Maintainability & Complexity | 2 | 2 | 2 | 2 | 2 | 1 |
| C3 | Consistency & Idiomatic Code | 1 | 1 | 1 | 1 | 1 | 1 |
| C4 | Test Suite Quality | 2 | 3 | 2 | 2 | 2 | 1 |
| D1 | Feature Completeness | 2 | 2 | 2 | 2 | 2 | 2 |
| D2 | Gap Coverage | 2 | 2 | 2 | 2 | 2 | 2 |
| D3 | Practicality | 2 | 2 | 2 | 2 | 2 | 3 |
| D4 | Intuitiveness | 2 | 2 | 1 | 3 | 3 | 2 |
| E1 | Adopter Friendliness | 2 | 3 | 1 | 1 | 2 | 1 |
| E2 | Documentation | 2 | 3 | 2 | 1 | 2 | 1 |
| E3 | Developer Experience & Inner Loop | 1 | 1 | 1 | 1 | 1 | 1 |
| E4 | Native Tooling & Ecosystem Fit | 1 | 2 | 1 | 1 | 1 | 1 |
| F1 | Ease of Deployability | 2 | 1 | 3 | 2 | 1 | 1 |
| F2 | Build, CI/CD & Automation | 1 | 2 | 2 | 1 | 1 | 1 |
| F3 | Observability & Debuggability | 1 | 1 | 3 | 2 | 1 | 1 |
| F4 | Performance, Efficiency & Scalability | 1 | 2 | 2 | 2 | 1 | 1 |
| F5 | Portability | 1 | 2 | 1 | 1 | 2 | 1 |
| F6 | Dependency Health & Longevity | 1 | 2 | 1 | 1 | 1 | 1 |
| | *Conditional (only when applicable)* | | | | | | |
| X1 | Accessibility, UX & Internationalization | 2 | 2 | 2 | 2 | 2 | 1 |
| X2 | Public API Stability & Upgradeability | 2 | 3 | 2 | 2 | 2 | 1 |
| X3 | Concurrency Safety | 2 | 2 | 2 | 2 | 2 | 1 |
| X4 | Cost Efficiency | 2 | 1 | 2 | 2 | 1 | 1 |
| X5 | Compliance & Licensing | 2 | 2 | 2 | 2 | 2 | 1 |
| X6 | Agent-Readiness | 1 | 1 | 1 | 1 | 1 | 1 |

## Targets

Targets tell improving agents where to stop. They are set by `target_mode` in the project context:

| Mode | Target for each applicable benchmark |
|---|---|
| `proportional` (default) | By weight used: 3 → 10, 2 → 9, 1 → 8 |
| `maximal` | 10 everywhere |
| `level:L3` (or any level) | The minimum score each benchmark needs for that maturity level: Pillar A at the level's Pillar A minimum, everything else at its "no benchmark below" minimum. The overall-score requirement still has to be met. |

- A `limited` benchmark's target is never above 8.
- Per-benchmark overrides in the project context (e.g. `{"F4": 10}`) take priority over the mode.
- `gradekit.py rollup` computes each benchmark's target and the distance to it.

## Roll-ups

- **Pillar score** = weighted average of the pillar's non-N/A benchmarks.
- **Overall score** = `sum(score × weight) / sum(weight)` across all non-N/A benchmarks, conditionals included.
- **Overall cap:** if A1 or A2 is 3 or lower, the overall score cannot exceed 4.0.

Always compute these with `gradekit.py rollup` rather than by hand.

## Maturity ladder

| Level | Name | Requirements (all must hold) |
|---|---|---|
| L0 | Not viable | A1 or A2 ≤ 3, or L1 not met |
| L1 | Prototype | Overall ≥ 5.0; every Pillar A benchmark ≥ 4 |
| L2 | Usable / Beta | Overall ≥ 6.5; no benchmark < 4; every Pillar A benchmark ≥ 6; no critical gaps |
| L3 | Production-ready | Overall ≥ 8.0; no benchmark < 6; every Pillar A benchmark ≥ 8; no critical or major must-have gaps; hidden-check pass rate ≥ 80% (if hidden checks were run) |
| L4 | Exemplary | Overall ≥ 9.3; no benchmark < 8; every Pillar A benchmark ≥ 9; no critical or major must-have gaps; every 10 backed by enforcement evidence; hidden-check pass rate ≥ 95% (if run) |

**Integrity rule:** any integrity flag (Part 1 of the grader prompt) caps maturity at L1 for that run, whatever the scores.
