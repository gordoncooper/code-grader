# Grading report: orders-api @ 9f8e7d6 (2026-10-24)

*Example report for the suite's bundled sample repo. Scores are illustrative.*

## Summary

Overall **4.0**, maturity **L0** (next: L1). An early baseline: a committed API key, almost no tests and a thin README.

## Gates and maturity

| Gate | Score | Status |
|---|:-:|---|
| A1 Correctness & Functional Behavior | 5 | passed (always) |
| A2 Security & Privacy | 3 | failed (always) |
| A3 Robustness & Error Handling | 4 | passed (failure_impact=revenue_loss) |
| A4 Idempotence & Determinism | 5 | passed (data_sensitivity=financial) |
| A5 Durability & Recoverability | 4 | passed (data_sensitivity=financial) |

Blocking the next level: gate above 3 (now 3); overall ≥ 5.0 (now 4.0); gate ≥ 4 (now 3)

## Scorecard

| ID | Benchmark | Score | Target | Weight | Applicability |
|---|---|:-:|:-:|:-:|---|
| A1 | Correctness & Functional Behavior | 5 | 10 | 3 | full |
| A2 | Security & Privacy | 3 | 10 | 3 | full |
| A3 | Robustness & Error Handling | 4 | 10 | 3 | full |
| A4 | Idempotence & Determinism | 5 | 10 | 3 | full |
| A5 | Durability & Recoverability | 4 | 10 | 3 | full |
| B1 | Architecture & Design Fitness | 6 | 9 | 2 | full |
| B2 | Modularity & Decoupling | 6 | 9 | 2 | full |
| B3 | Structure & Organization | 7 | 8 | 1 | full |
| B4 | Interface Design & Contracts | 5 | 9 | 2 | full |
| B5 | Flexibility & Extensibility | 6 | 8 | 1 | full |
| B6 | Leanness | 6 | 9 | 2 | full |
| C1 | Readability & Clarity | 7 | 9 | 2 | full |
| C2 | Maintainability & Complexity | 6 | 9 | 2 | full |
| C3 | Consistency & Idiomatic Code | 7 | 8 | 1 | full |
| C4 | Test Suite Quality | 2 | 9 | 2 | full |
| D1 | Feature Completeness | 5 | 9 | 2 | full |
| D2 | Gap Coverage | 5 | 9 | 2 | full |
| D3 | Practicality | 6 | 9 | 2 | full |
| D4 | Intuitiveness | 6 | 9 | 2 | full |
| E1 | Adopter Friendliness | 3 | 9 | 2 | full |
| E2 | Documentation | 3 | 9 | 2 | full |
| E3 | Developer Experience & Inner Loop | 4 | 8 | 1 | full |
| E4 | Native Tooling & Ecosystem Fit | 6 | 8 | 1 | full |
| F1 | Ease of Deployability | 3 | 10 | 3 | full |
| F2 | Build, CI/CD & Automation | 2 | 8 | 1 | full |
| F3 | Observability & Debuggability | 3 | 10 | 3 | full |
| F4 | Performance, Efficiency & Scalability | 6 | 8 | 1 | full |
| F5 | Portability | 7 | 8 | 1 | limited |
| F6 | Dependency Health & Longevity | 5 | 8 | 1 | full |
| X1 | Accessibility, UX & Internationalization | – | – | 0 | not_applicable |
| X2 | Public API Stability & Upgradeability | 5 | 8 | 1 | limited |
| X3 | Concurrency Safety | 5 | 9 | 2 | full |
| X4 | Cost Efficiency | – | – | 0 | not_applicable |
| X5 | Compliance & Licensing | – | – | 0 | not_applicable |
| X6 | Agent-Readiness | 2 | 8 | 1 | full |

## Top priorities

1. **A3-act-1** (tier 0, hot zone, +3, effort S): In src/orders/service.py create_order, remove the bare except; let reserve_stock failures propagate as an OutOfStock error and return 409 from the API layer
2. **F2-act-1** (tier 2, normal zone, +5, effort S): Add .github/workflows/ci.yml running ruff, mypy --strict and pytest --cov with a branch-coverage floor, required on main
3. **A4-act-1** (tier 2, cold zone, +2, effort S): Rewrite scripts/seed.sql inserts as INSERT ... ON CONFLICT (id) DO NOTHING and add a CI step that runs the seed twice
4. **D1-act-1** (tier 2, normal zone, +3, effort M): Either implement CSV/XLSX export in a new src/export module with tests, or remove the claim from README.md — **decision needed:** Implement CSV and XLSX export, or drop the export claim from the README?

## Decisions needed

- [ ] **D1-act-1:** Implement CSV and XLSX export, or drop the export claim from the README?

Answer in `decisions.json` (the suite website's *Review a report* page writes it for you).

## Findings

| ID | Severity → effective | Zone | Status | Title |
|---|---|---|---|---|
| A1-001 | major → critical | hot | new | Discount ignored for single-item orders |
| A2-001 | major → critical | hot | new | No input validation on charge amount |
| A3-001 | critical → critical | hot | new | Stock reservation errors swallowed |
| A4-001 | major → minor | cold | new | Seed script not re-runnable |
| A4-002 | minor → major | hot | new | Wall-clock time read inside domain logic |
| A5-001 | major → critical | hot | new | Order insert and stock reservation not in one transaction |
| B1-001 | minor → major | hot | new | Domain logic depends directly on the DB handle |
| B2-001 | minor → major | hot | new | Orders and payments share no interface; payments reads the raw request |
| B4-001 | major → critical | hot | new | Items are untyped dicts |
| B5-001 | minor → major | hot | new | Single payment gateway assumed |
| C2-001 | minor → major | hot | new | Rounding and discount logic mixed in one function |
| C4-001 | critical → major | cold | new | One test covers one happy path |
| D1-001 | major → major | normal | new | XLSX export advertised but not implemented |
| D3-001 | minor → major | hot | new | Money handled as floats |
| D4-001 | minor → major | hot | new | discount parameter silently ignored in a common case |
| E1-001 | critical → critical | normal | new | Quickstart command does not exist |
| E2-001 | major → major | normal | new | README is one line and partly wrong |
| E3-001 | major → major | normal | new | No dependency manifest or dev setup |
| E4-001 | minor → minor | normal | new | No standard Python project metadata |
| F1-001 | critical → critical | normal | new | No deploy artifact or instructions |
| F2-001 | critical → critical | normal | new | No CI |
| F3-001 | major → major | normal | new | No logging anywhere |
| F4-001 | minor → major | hot | new | Total recomputed per insert with no batching |
| F6-001 | major → major | normal | new | Dependencies not declared or pinned |
| X2-001 | minor → minor | normal | new | No versioning of the HTTP API |
| X3-001 | major → critical | hot | new | Check-then-act race on idempotency key |
| X6-001 | major → major | normal | new | No agent instructions or runnable verification commands |
| A2-002 | critical → critical | normal | new | Payment API key committed in config |

## Limitations

- Example report for the bundled sample repo; scores are illustrative.
- Hidden checks: 4 run, 50% passed.
