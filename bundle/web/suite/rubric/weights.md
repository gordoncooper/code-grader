<!-- Part of the Code Grading Suite v4.3.0. The tables show the shipped defaults (config/defaults.toml). For your own configuration, run `gradekit presets` and `gradekit resolve`. -->

# How scoring works: weights, gates, zones, targets and maturity

Graders only assign the 1–10 scores and findings. Everything else in this file is computed by `gradekit` from the **effective config**: the suite defaults layered with an optional org-level config and the project's own config. That keeps the arithmetic consistent and the rules tunable. To change any of it, see `TUNING.md`.

```
config/defaults.toml  →  org.toml (optional)  →  project.toml
                     gradekit resolve
                            ↓
weights · gates · zones · targets · maturity rules · priority rules
                            ↓
grader scores + findings  →  gradekit rollup  →  overall, gates, maturity, ranked priorities
```

## 1. Weights: how much each benchmark counts

Weights run from 1 (minor) to 3 (critical). Each benchmark's weight is:

1. its **base weight**;
2. **plus the effects of the project's answers** to eight questions about the project, e.g. "handles money" raises Security, Idempotence and Durability;
3. **clamped** to 1–3;
4. replaced by an **explicit override**, if the project sets one (an override always needs a written reason).

Then **applicability** adjusts it per grading run: `limited` drops the weight to 1, and `not_applicable` removes the benchmark from every average.

Run `gradekit resolve --config project.toml --explain A4` to see exactly how any weight was reached.

### The questions

| Question | Answer | Weight effects | Makes a gate |
|---|---|---|---|
| **data_sensitivity**<br>What is the most sensitive data this code handles? | `none` | A2 -1, A5 -1 | — |
|  | `internal` *(default)* | — | — |
|  | `personal` | A2 +1, A5 +1, X5 +1 | A5 |
|  | `financial` | A2 +1, A4 +1, A5 +1 | A4, A5 |
|  | `regulated` | A2 +1, A5 +1, X5 +2 | A5, X5 |
| **audience**<br>Who uses it? | `just_me` | D4 -1, E1 -1, E2 -1, X2 -1 | — |
|  | `team` | E1 -1 | — |
|  | `internal_org` *(default)* | — | — |
|  | `public` | A2 +1, D4 +1, X1 +1 | — |
|  | `developers` | B4 +1, E1 +1, E2 +1, X2 +1 | — |
| **lifespan**<br>How long will this code live? | `throwaway` | B1 -1, B2 -1, B5 -1, C2 -1, C4 -1, E3 -1, F6 -1, D3 +1 | — |
|  | `months` | B5 -1, F6 -1 | — |
|  | `years` *(default)* | — | — |
|  | `indefinite` | B1 +1, C2 +1, F6 +1 | — |
| **failure_impact**<br>What happens when it fails? | `inconvenience` | A3 -1, F1 -1, F3 -1 | — |
|  | `degraded_work` *(default)* | — | — |
|  | `revenue_loss` | A3 +1, A4 +1, F1 +1, F3 +1 | A3 |
|  | `safety_or_legal` | A3 +1, A5 +1, C4 +1, F3 +1 | A3, A5 |
| **team**<br>Who works on it? | `solo` | C3 -1, E3 -1 | — |
|  | `small` *(default)* | — | — |
|  | `large` | B2 +1, C3 +1, E3 +1, F2 +1 | — |
|  | `open_source` | C3 +1, E1 +1, E2 +1, E3 +1, F2 +1 | — |
| **change_rate**<br>How often does it change? | `rare` | B5 -1 | — |
|  | `regular` *(default)* | — | — |
|  | `constant` | B5 +1, C2 +1, C4 +1, F2 +1 | — |
| **delivery**<br>How is it delivered? | `mixed` *(default)* | — | — |
|  | `service` | A4 +1, F1 +1, F3 +2 | — |
|  | `website` | D4 +1, F3 +1, F4 +1 | — |
|  | `package` | B2 +1, B4 +1, E4 +1, F1 -1, F2 +1, F5 +1, X2 +1 | — |
|  | `installed_app` | A5 -1, D4 +1, F1 -1, F5 +1 | — |
|  | `internal_script` | E1 -1, F1 -1, F5 -1 | — |
| **scale**<br>What load or data volume does it face? | `small` | F4 -1 | — |
|  | `moderate` *(default)* | — | — |
|  | `large` | F4 +1, X4 +1 | — |
|  | `massive` | F4 +2, X3 +1, X4 +1 | — |

### Presets

A preset is a set of typical answers. A project picks one, then overrides any answers that don't fit.

| Preset | Answers (everything else at its default) |
|---|---|
| `default` | none — No assumptions: every question at its default answer |
| `service` | delivery = `service`, failure_impact = `revenue_loss` — A backend service or API you deploy and operate |
| `web_app` | delivery = `website`, audience = `public`, data_sensitivity = `personal` — A public-facing web application |
| `library` | delivery = `package`, audience = `developers`, lifespan = `indefinite` — A library or SDK other developers depend on |
| `oss_library` | delivery = `package`, audience = `developers`, lifespan = `indefinite`, team = `open_source` — An open-source library with outside contributors |
| `cli` | delivery = `installed_app`, audience = `developers` — A command-line tool people install |
| `internal_tool` | delivery = `internal_script`, audience = `team`, failure_impact = `inconvenience` — An internal tool or script collection used by one team |
| `prototype` | lifespan = `throwaway`, audience = `team`, failure_impact = `inconvenience`, team = `solo` — A spike, demo or experiment |

### Resulting weights by preset

| ID | Benchmark | Base | Default | Service | Web app | Library | OSS lib | CLI | Internal | Prototype |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| A1 | Correctness & Functional Behavior | 3 | **3** | **3** | **3** | **3** | **3** | **3** | **3** | **3** |
| A2 | Security & Privacy | 3 | **3** | **3** | **3** | **3** | **3** | **3** | **3** | **3** |
| A3 | Robustness & Error Handling | 2 | 2 | **3** | 2 | 2 | 2 | 2 | 1 | 1 |
| A4 | Idempotence & Determinism | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 | 2 |
| A5 | Durability & Recoverability | 2 | 2 | 2 | **3** | 2 | 2 | 1 | 2 | 2 |
| B1 | Architecture & Design Fitness | 2 | 2 | 2 | 2 | 3 | 3 | 2 | 2 | 1 |
| B2 | Modularity & Decoupling | 2 | 2 | 2 | 2 | 3 | 3 | 2 | 2 | 1 |
| B3 | Structure & Organization | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| B4 | Interface Design & Contracts | 2 | 2 | 2 | 2 | 3 | 3 | 3 | 2 | 2 |
| B5 | Flexibility & Extensibility | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| B6 | Leanness | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| C1 | Readability & Clarity | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| C2 | Maintainability & Complexity | 2 | 2 | 2 | 2 | 3 | 3 | 2 | 2 | 1 |
| C3 | Consistency & Idiomatic Code | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 | 1 |
| C4 | Test Suite Quality | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 1 |
| D1 | Feature Completeness | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| D2 | Gap Coverage | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| D3 | Practicality | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 3 |
| D4 | Intuitiveness | 2 | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 |
| E1 | Adopter Friendliness | 2 | 2 | 2 | 2 | 3 | 3 | 3 | 1 | 1 |
| E2 | Documentation | 2 | 2 | 2 | 2 | 3 | 3 | 3 | 2 | 2 |
| E3 | Developer Experience & Inner Loop | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 | 1 |
| E4 | Native Tooling & Ecosystem Fit | 1 | 1 | 1 | 1 | 2 | 2 | 1 | 1 | 1 |
| F1 | Ease of Deployability | 2 | 2 | 3 | 2 | 1 | 1 | 1 | 1 | 1 |
| F2 | Build, CI/CD & Automation | 1 | 1 | 1 | 1 | 2 | 3 | 1 | 1 | 1 |
| F3 | Observability & Debuggability | 1 | 1 | 3 | 2 | 1 | 1 | 1 | 1 | 1 |
| F4 | Performance, Efficiency & Scalability | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 1 |
| F5 | Portability | 1 | 1 | 1 | 1 | 2 | 2 | 2 | 1 | 1 |
| F6 | Dependency Health & Longevity | 1 | 1 | 1 | 1 | 2 | 2 | 1 | 1 | 1 |
| X1 | Accessibility, UX & Internationalization | 2 | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 |
| X2 | Public API Stability & Upgradeability | 2 | 2 | 2 | 2 | 3 | 3 | 3 | 2 | 2 |
| X3 | Concurrency Safety | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| X4 | Cost Efficiency | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| X5 | Compliance & Licensing | 2 | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 |
| X6 | Agent-Readiness | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

**Bold** = gate for that preset.

## 2. Gates: what an average can't make up for

A weighted average lets strengths make up for weaknesses: great docs could "pay for" a security hole. Gates stop that.

- **Which benchmarks are gates:**
  - Correctness (A1) and Security (A2) always are.
  - Some answers add more: handling money makes Idempotence (A4) and Durability (A5) gates; failure that costs revenue makes Robustness (A3) one.
  - Projects can add gates of their own (`[gates] extra`).
- **A gate at or below the hard floor (default 3) caps the overall score at 4.0**, and maturity stays at L0 until it's fixed.
- **Each maturity level has a gate minimum.** Every gate must reach it.
- **Fixing a failed gate always ranks first** among improvement actions.

## 3. Zones: not all code matters equally

The project config maps paths to zones: **hot** (money, auth, data writes), **normal**, or **cold** (scripts, examples, internal tooling). A file takes the first zone whose pattern matches; a finding takes the hottest zone among the files it cites.

- **Effective severity.** Graders record each finding's *intrinsic* severity. `gradekit` shifts it by zone: one level up in hot zones, one level down in cold zones. Security findings are never downgraded.
- **Maturity.** Levels limit open findings by effective severity and zone. For example, L2 allows no critical findings in hot zones.
- **Priorities.** Work in hot zones is ranked higher (×2 by default; cold ×0.5).
- **Grading.** Graders read hot zones in full and weigh them most when scoring.

## 4. Targets: where improvement stops

| Mode | Target for each applicable benchmark |
|---|---|
| `proportional` (default) | By weight used: 3 → 10, 2 → 9, 1 → 8 |
| `maximal` | 10 everywhere |
| `level:L3` (any level) | The minimum each benchmark needs for that maturity level: gates at the level's gate minimum, others at its "no benchmark below" minimum |

A `limited` benchmark never targets above 8. Per-benchmark overrides beat the mode.

## 5. The rollup

- **Pillar score:** the weighted average of that pillar's applicable benchmarks.
- **Overall score:** the weighted average of all applicable benchmarks, capped if a gate failed.
- **Monorepos:** each component is scored with its own config. The repo-wide overall score is weighted by component, and repo-wide maturity is the lowest component's level.

## 6. Maturity ladder

| Level | Name | Requirements (all must hold; findings counted at effective severity) |
|---|---|---|
| L0 | Not viable | Any gate at or below the hard floor, or L1 not met |
| L1 | Prototype | overall ≥ 5.0; every gate ≥ 4 |
| L2 | Usable / Beta | overall ≥ 6.5; every gate ≥ 6; no benchmark < 4; no critical gaps; no open critical findings in hot zones |
| L3 | Production-ready | overall ≥ 8.0; every gate ≥ 8; no benchmark < 6; no critical gaps; no major must-have gaps; no open critical findings; hidden-check pass rate ≥ 80% (if run) |
| L4 | Exemplary | overall ≥ 9.3; every gate ≥ 9; no benchmark < 8; no critical gaps; no major must-have gaps; no open critical findings; no open major findings; every 10 backed by enforcement; hidden-check pass rate ≥ 95% (if run) |

Any **integrity flag** (an attempt to influence the grader) caps maturity at L1 for that run.

## 7. Priorities: what to fix first

`gradekit rollup` ranks every action in four tiers:

| Tier | Contains |
|---|---|
| 0 | Fixes a failed gate, or an effective-critical finding in a hot zone |
| 1 | Unblocks the next maturity level |
| 2 | Everything else below target |
| 3 | Optional (benchmark already at target) |

Within a tier, actions are ordered by **weight × points gained (up to target) × zone multiplier ÷ effort cost**, where effort costs S = 1, M = 2, L = 4. Improving agents work through this list in order.
