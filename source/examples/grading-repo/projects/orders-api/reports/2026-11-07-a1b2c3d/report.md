# Grading report: orders-api @ a1b2c3d (2026-11-07)

*Graded by example (example)*

## Summary

Overall **4.9**, maturity **L0** (next: L1).

The committed API key is gone and the first tests exist. The biggest risks now are a silently swallowed stock-reservation error in a hot zone, no CI, and an order insert that isn't transactional.

## Gates and maturity

| Gate | Score | Status |
|---|:-:|---|
| A1 Correctness & Functional Behavior | 5 | passed (always) |
| A2 Security & Privacy | 5 | passed (always) |
| A3 Robustness & Error Handling | 4 | passed (failure_impact=revenue_loss) |
| A4 Idempotence & Determinism | 5 | passed (data_sensitivity=financial) |
| A5 Durability & Recoverability | 4 | passed (data_sensitivity=financial) |

Blocking L1: overall ≥ 5.0 (now 4.9)

## Scorecard

Gates are marked ★. Weight is the weight used, after applicability.

| ID | Benchmark | Score | Target | Weight | Confidence | Applicability | Notes |
|---|---|:-:|:-:|:-:|---|---|---|
| A1 ★ | Correctness & Functional Behavior | 5 | 10 | 3 | medium | full |  |
| A2 ★ | Security & Privacy | 5 | 10 | 3 | medium | full | Hard-coded payment API key removed from src/payments/api.py (A2-002 fixed) |
| A3 ★ | Robustness & Error Handling | 4 | 10 | 3 | medium | full |  |
| A4 ★ | Idempotence & Determinism | 5 | 10 | 3 | high | full |  |
| A5 ★ | Durability & Recoverability | 4 | 10 | 3 | medium | full |  |
| | **A Correctness & Trust** | **4.6** | | | | | |
| B1 | Architecture & Design Fitness | 6 | 9 | 2 | medium | full |  |
| B2 | Modularity & Decoupling | 6 | 9 | 2 | medium | full |  |
| B3 | Structure & Organization | 7 | 8 | 1 | medium | full |  |
| B4 | Interface Design & Contracts | 5 | 9 | 2 | medium | full |  |
| B5 | Flexibility & Extensibility | 6 | 8 | 1 | medium | full |  |
| B6 | Leanness | 7 | 9 | 2 | medium | full | Unused helper module deleted |
| | **B Design & Structure** | **6.1** | | | | | |
| C1 | Readability & Clarity | 7 | 9 | 2 | medium | full |  |
| C2 | Maintainability & Complexity | 6 | 9 | 2 | medium | full |  |
| C3 | Consistency & Idiomatic Code | 7 | 8 | 1 | medium | full |  |
| C4 | Test Suite Quality | 3 | 9 | 2 | high | full | A unit test for order totals was added |
| | **C Code Health** | **5.6** | | | | | |
| D1 | Feature Completeness | 5 | 9 | 2 | medium | full |  |
| D2 | Gap Coverage | 5 | 9 | 2 | medium | full |  |
| D3 | Practicality | 6 | 9 | 2 | medium | full |  |
| D4 | Intuitiveness | 6 | 9 | 2 | medium | full |  |
| | **D Value & Fitness for Purpose** | **5.5** | | | | | |
| E1 | Adopter Friendliness | 3 | 9 | 2 | high | full |  |
| E2 | Documentation | 4 | 9 | 2 | medium | full | README now describes the service |
| E3 | Developer Experience & Inner Loop | 4 | 8 | 1 | medium | full |  |
| E4 | Native Tooling & Ecosystem Fit | 6 | 8 | 1 | medium | full |  |
| | **E Adoption & Experience** | **4.0** | | | | | |
| F1 | Ease of Deployability | 3 | 10 | 3 | medium | full |  |
| F2 | Build, CI/CD & Automation | 2 | 8 | 1 | high | full |  |
| F3 | Observability & Debuggability | 3 | 10 | 3 | medium | full |  |
| F4 | Performance, Efficiency & Scalability | 6 | 8 | 1 | medium | full |  |
| F5 | Portability | 7 | 8 | 1 | medium | limited | Ships only as one pinned Linux container; would become fully relevant if it ran on other platforms. |
| F6 | Dependency Health & Longevity | 5 | 8 | 1 | medium | full |  |
| | **F Operations & Delivery** | **3.8** | | | | | |
| X1 | Accessibility, UX & Internationalization | – | – | 0 | – | not_applicable | Backend API with no user interface. |
| X2 | Public API Stability & Upgradeability | 5 | 8 | 1 | medium | limited | Internal API with one known consumer; becomes fully relevant if exposed to other teams. |
| X3 | Concurrency Safety | 5 | 9 | 2 | medium | full |  |
| X4 | Cost Efficiency | – | – | 0 | – | not_applicable | Runs on fixed, already-paid hardware; no metered resources or paid APIs. |
| X5 | Compliance & Licensing | – | – | 0 | – | not_applicable | No regulated data and the software is not distributed. |
| X6 | Agent-Readiness | 2 | 8 | 1 | medium | full |  |
| | **X Conditional** | **4.3** | | | | | |
| | **Overall** | **4.9** | | | | | |

## Applicability and weight notes

- **F5** limited: Ships only as one pinned Linux container; would become fully relevant if it ran on other platforms.
- **X2** limited: Internal API with one known consumer; becomes fully relevant if exposed to other teams.
- **X1** not applicable: Backend API with no user interface.
- **X4** not applicable: Runs on fixed, already-paid hardware; no metered resources or paid APIs.
- **X5** not applicable: No regulated data and the software is not distributed.
- **F1** weight note: Deploys are owned by a platform team; weight 2 would better reflect this repo's share.

## Top priorities

1. **A1-act-1** (tier 0, hot zone, +3, effort S): In order_total, apply the discount to single-item orders too (drop the len(items) > 1 condition) and test a one-item discounted order
2. **A2-act-1** (tier 0, hot zone, +3, effort S): Fix A2-001 as the private report describes, and add a test that fails without the fix
3. **A3-act-1** (tier 0, hot zone, +3, effort S): In src/orders/service.py create_order, remove the bare except; let reserve_stock failures propagate as an OutOfStock error and return 409 from the API layer
4. **A5-act-1** (tier 0, hot zone, +4, effort M): In create_order, insert the order and reserve stock in one database transaction, so a failed reservation leaves no order behind
5. **B4-act-1** (tier 0, hot zone, +3, effort M): Replace the item dicts with a dataclass (sku, price, qty), checked where requests come in
6. **X3-act-1** (tier 0, hot zone, +3, effort M): Claim the idempotency key atomically (insert-if-absent) before charging, so two concurrent requests can't both charge
7. **D2-act-1** (tier 0, hot zone, +2, effort L): Add order cancellation with a refund through the gateway (D2-001)
8. **F3-act-1** (tier 2, normal zone, +4, effort S): Log each order and charge with its ID and outcome, using the logging module
9. **C2-act-1** (tier 2, hot zone, +2, effort S): Split order_total into subtotal, discount and rounding steps, each with its own test
10. **D4-act-1** (tier 2, hot zone, +2, effort S): Make the discount parameter apply in every case, or reject it where it can't, instead of ignoring it

## Decisions needed

- [ ] **D1-act-1:** Implement CSV and XLSX export, or drop the export claim from the README?

Answers go in `decisions.json`: tick the boxes in this report's pull request (the grading CI records them), run `gradekit decide --approve ID --by NAME`, or use the suite website's *Review a report* page.

## Metrics

| Metric | Value | Note |
|---|---|---|
| build_passes | yes |  |
| tests_total | 1 |  |
| tests_failed | 0 |  |
| tests_skipped | 0 |  |
| line_coverage_pct | 41 |  |
| branch_coverage_pct | 25 |  |
| lint_errors | 0 |  |
| lint_suppressions | 0 |  |
| vulns_critical | 0 |  |
| secrets_found | 0 |  |
| setup_second_run_passes | no |  |
| time_to_first_success_minutes | – | quickstart fails at step 1 |
| mutation_score_pct | – | no mutation tool available |
| loc_source | 25 |  |
| loc_tests | 5 |  |

## Findings

| ID | Severity | Zone | Status | Title |
|---|---|---|---|---|
| A1-001 | critical | hot | open | Discount ignored for single-item orders |
| A2-001 | critical | hot | open | Security & Privacy issue (details withheld) |
| A3-001 | critical | hot | open | Stock reservation errors swallowed |
| A4-001 | minor | cold | open | Seed script not re-runnable |
| A4-002 | major | hot | open | Wall-clock time read inside domain logic |
| A5-001 | critical | hot | open | Order insert and stock reservation not in one transaction |
| B1-001 | major | hot | open | Domain logic depends directly on the DB handle |
| B2-001 | major | hot | open | Orders and payments share no interface; payments reads the raw request |
| B4-001 | critical | hot | open | Items are untyped dicts |
| B5-001 | major | hot | accepted | Single payment gateway assumed |
| C2-001 | major | hot | open | Rounding and discount logic mixed in one function |
| C4-001 | major | cold | open | One test covers one happy path |
| D1-001 | major | normal | open | XLSX export advertised but not implemented |
| D2-001 | critical | hot | new | No way to cancel or refund an order |
| D3-001 | major | hot | open | Money handled as floats |
| D4-001 | major | hot | open | discount parameter silently ignored in a common case |
| E1-001 | critical | normal | open | Quickstart command does not exist |
| E2-001 | major | normal | open | README is one line and partly wrong |
| E3-001 | major | normal | open | No dependency manifest or dev setup |
| E4-001 | minor | normal | open | No standard Python project metadata |
| F1-001 | critical | normal | open | No deploy artifact or instructions |
| F2-001 | critical | normal | open | No CI |
| F3-001 | major | normal | open | No logging anywhere |
| F4-001 | major | hot | open | Total recomputed per insert with no batching |
| F6-001 | major | normal | open | Dependencies not declared or pinned |
| X2-001 | minor | normal | open | No versioning of the HTTP API |
| X3-001 | critical | hot | open | Check-then-act race on idempotency key |
| X6-001 | major | normal | open | No agent instructions or runnable verification commands |
| A2-002 | critical | hot | fixed | Payment API key committed in config |

Fixed since the last report: A2-002.

## Feature inventory

| Feature | Claimed in | Status |
|---|---|---|
| Create order | route | partial |
| Idempotent charge | route | complete |
| CSV/XLSX export | README | stub |

## Gap register

| ID | Gap | Severity | Necessity | Status | Benchmarks |
|---|---|---|---|---|---|
| GAP-001 | No cancel or refund flow | major | must-have | new | D2 |
| GAP-002 | No health check endpoint | minor | must-have | new | D2, F1 |

## Benchmark detail

### A1 Correctness & Functional Behavior: 5 (target 10)

- Finding A1-001 (critical, open): Discount ignored for single-item orders (`src/orders/service.py:7-8`: discount only applied when more than one item)
- Limit: at most 5 while open critical finding A1-001
- Next: **A1-act-1** → 8 (effort S): In order_total, apply the discount to single-item orders too (drop the len(items) > 1 condition) and test a one-item discounted order

### A2 Security & Privacy: 5 (target 10)

Change: Hard-coded payment API key removed from src/payments/api.py (A2-002 fixed)

- Finding A2-001 (critical, open): Security & Privacy issue (details withheld)
- Finding A2-002 (critical, fixed): Payment API key committed in config (`src/payments/api.py:2`: key now read from the request; the hard-coded secret was removed)
- Limit: at most 5 while open critical finding A2-001
- Next: **A2-act-1** → 8 (effort S): Fix A2-001 as the private report describes, and add a test that fails without the fix

### A3 Robustness & Error Handling: 4 (target 10)

- Finding A3-001 (critical, open): Stock reservation errors swallowed (`src/orders/service.py:16-17`: order is created even when stock reservation fails)
- Limit: at most 4 while open critical finding A3-001; A3-cap-1: Catch-all blocks that swallow errors in core paths
- Next: **A3-act-1** → 7 (effort S): In src/orders/service.py create_order, remove the bare except; let reserve_stock failures propagate as an OutOfStock error and return 409 from the API layer

### A4 Idempotence & Determinism: 5 (target 10)

- Strength: Payment endpoint honours idempotency keys (`src/payments/api.py:2`)
- Finding A4-001 (minor, open): Seed script not re-runnable (`scripts/seed.sql:2`: second run fails with duplicate key)
- Finding A4-002 (major, open): Wall-clock time read inside domain logic (`src/orders/service.py:13`: time not injectable; tests cannot control it)
- Limit: at most 5 while A4-cap-2: Setup or migration fails or corrupts on a second run
- Next: **A4-act-1** → 7 (effort S): Rewrite scripts/seed.sql inserts as INSERT ... ON CONFLICT (id) DO NOTHING and add a CI step that runs the seed twice

### A5 Durability & Recoverability: 4 (target 10)

- Finding A5-001 (critical, open): Order insert and stock reservation not in one transaction (`src/orders/service.py:13-15`: a crash between insert and reserve leaves an order with no stock held)
- Limit: at most 4 while open critical finding A5-001; A5-cap-1: Important state written non-atomically or held only in memory
- Next: **A5-act-1** → 8 (effort M): In create_order, insert the order and reserve stock in one database transaction, so a failed reservation leaves no order behind

### B1 Architecture & Design Fitness: 6 (target 9)

- Finding B1-001 (major, open): Domain logic depends directly on the DB handle (`src/orders/service.py:12`: no repository boundary; persistence details leak into the domain)
- Next: **B1-act-1** → 8 (effort M): Give the order service a small repository interface (insert_order, reserve_stock) instead of the raw db handle

### B2 Modularity & Decoupling: 6 (target 9)

- Finding B2-001 (major, open): Orders and payments share no interface; payments reads the raw request (`src/payments/api.py:1`: HTTP request object passed into payment logic)
- Next: **B2-act-1** → 8 (effort M): Have charge() take an amount and an idempotency key from its caller instead of reading the raw HTTP request

### B3 Structure & Organization: 7 (target 8)

- Strength: src/, tests/ and scripts/ cleanly separated (ran `find . -maxdepth 2 -type d`)
- Next: **B3-act-1** → 8 (effort S): Add a package layout (src/orders/__init__.py, src/payments/__init__.py) and move the API handlers apart from the domain logic

### B4 Interface Design & Contracts: 5 (target 9)

- Finding B4-001 (critical, open): Items are untyped dicts (`src/orders/service.py:6`: no type or schema for items)
- Limit: at most 5 while open critical finding B4-001
- Next: **B4-act-1** → 8 (effort M): Replace the item dicts with a dataclass (sku, price, qty), checked where requests come in

### B5 Flexibility & Extensibility: 6 (target 8)

- Finding B5-001 (major, accepted): Single payment gateway assumed (`src/payments/api.py:5`: no currency or provider abstraction)
- Next: **B5-act-1** → 7 (effort S): Note the single-gateway decision (B5-001, accepted through 2027) beside charge(), so the next provider has an obvious seam

### B6 Leanness: 7 (target 9)

Change: Unused helper module deleted

- Strength: Small, dependency-free code (ran `wc -l src/**/*.py`)
- Next: **B6-act-1** → 8 (effort S): Let the database stamp each order's creation time, and drop the time import from create_order

### C1 Readability & Clarity: 7 (target 9)

- Strength: Short functions with clear names (`src/orders/service.py:5`)
- Next: **C1-act-1** → 8 (effort S): Name the money values (subtotal, discount_rate) and add docstrings to order_total and charge

### C2 Maintainability & Complexity: 6 (target 9)

- Finding C2-001 (major, open): Rounding and discount logic mixed in one function (`src/orders/service.py:9`: float rounding for money; no money type)
- Next: **C2-act-1** → 8 (effort S): Split order_total into subtotal, discount and rounding steps, each with its own test

### C3 Consistency & Idiomatic Code: 7 (target 8)

- Strength: Consistent PEP 8 style (ran `ruff check .`)
- Next: **C3-act-1** → 8 (effort S): Add a formatter and linter config (ruff) and apply it once

### C4 Test Suite Quality: 3 (target 9)

Change: A unit test for order totals was added

- Finding C4-001 (major, open): One test covers one happy path (ran `pytest -q`: single test; create_order and charge untested)
- Limit: at most 7 while C4-cap-1: Tests not run in CI
- Next: **C4-act-1** → 7 (effort M): Add tests for single-item orders, the discount, a failed stock reservation and a repeated idempotency key

### D1 Feature Completeness: 5 (target 9)

- Finding D1-001 (major, open): XLSX export advertised but not implemented (`README.md:3`; searched for export implementation (grep -rni 'xlsx\|csv' src/): no export code at all)
- Limit: at most 5 while D1-cap-1: Any advertised core feature that is missing or broken
- Next: **D1-act-1** → 8 (effort M): Either implement CSV/XLSX export in a new src/export module with tests, or remove the claim from README.md *(needs a decision)*

### D2 Gap Coverage: 5 (target 9)

- Finding D2-001 (critical, new): No way to cancel or refund an order (searched for cancel or refund operations (read all of src/; grep -rni 'refund\|cancel'))
- Limit: at most 5 while open critical finding D2-001
- Next: **D2-act-1** → 7 (effort L): Add order cancellation with a refund through the gateway (D2-001)

### D3 Practicality: 6 (target 9)

- Finding D3-001 (major, open): Money handled as floats (`src/orders/service.py:9`: float arithmetic for currency)
- Next: **D3-act-1** → 8 (effort M): Hold money as integer cents (or Decimal) from the request to the gateway call

### D4 Intuitiveness: 6 (target 9)

- Finding D4-001 (major, open): discount parameter silently ignored in a common case (`src/orders/service.py:5`: callers passing a discount for one item get no error and no discount)
- Next: **D4-act-1** → 8 (effort S): Make the discount parameter apply in every case, or reject it where it can't, instead of ignoring it

### E1 Adopter Friendliness: 3 (target 9)

- Finding E1-001 (critical, open): Quickstart command does not exist (`README.md:3`; searched for Makefile (ls -a at repo root): no Makefile; quickstart fails at step 1)
- Limit: at most 4 while open critical finding E1-001; E1-cap-1: Quickstart fails
- Next: **E1-act-1** → 7 (effort S): Replace `make dev` in the README with the command that starts the service, and check it from a fresh clone

### E2 Documentation: 4 (target 9)

Change: README now describes the service

- Finding E2-001 (major, open): README is one line and partly wrong (`README.md:3`: claims features that do not exist)
- Limit: at most 5 while E2-cap-1: Wrong setup instructions
- Next: **E2-act-1** → 7 (effort S): Rewrite the README: what the service does, how to run it and its tests, and the endpoints it serves

### E3 Developer Experience & Inner Loop: 4 (target 8)

- Finding E3-001 (major, open): No dependency manifest or dev setup (searched for pyproject.toml, requirements.txt, setup.cfg (ls -a at repo root))
- Next: **E3-act-1** → 7 (effort S): Add a pyproject.toml with the dependencies and a one-command test run

### E4 Native Tooling & Ecosystem Fit: 6 (target 8)

- Finding E4-001 (minor, open): No standard Python project metadata (searched for pyproject.toml (ls -a at repo root))
- Next: **E4-act-1** → 8 (effort S): Declare the project in pyproject.toml (name, version, Python requirement)

### F1 Ease of Deployability: 3 (target 10)

- Finding F1-001 (critical, open): No deploy artifact or instructions (searched for Dockerfile, deploy scripts, IaC (find . -iname '*docker*' -o -iname '*.tf'))
- Limit: at most 4 while open critical finding F1-001; F1-cap-1: Manual, undocumented deploy steps
- Next: **F1-act-1** → 7 (effort M): Add a Dockerfile and a deploy section to the README

### F2 Build, CI/CD & Automation: 2 (target 8)

- Finding F2-001 (critical, open): No CI (searched for CI configuration (ls .github/workflows .gitlab-ci.yml .circleci): none present)
- Limit: at most 5 while open critical finding F2-001
- Next: **F2-act-1** → 7 (effort S): Add .github/workflows/ci.yml running ruff, mypy --strict and pytest --cov with a branch-coverage floor, required on main

### F3 Observability & Debuggability: 3 (target 10)

- Finding F3-001 (major, open): No logging anywhere (searched for logging calls (grep -rn 'logging\|logger' src/))
- Next: **F3-act-1** → 7 (effort S): Log each order and charge with its ID and outcome, using the logging module

### F4 Performance, Efficiency & Scalability: 6 (target 8)

- Finding F4-001 (major, open): Total recomputed per insert with no batching (`src/orders/service.py:13`: fine at current scale; noted for bulk imports)
- Next: **F4-act-1** → 8 (effort M): Reserve stock for all items in one call per order, and measure create_order with a 100-item order

### F5 Portability: 7 (target 8)

- Strength: No platform-specific paths or shell calls (searched for absolute paths and subprocess calls (grep -rn "subprocess\|/home/\|C:\\" src/))
- Next: **F5-act-1** → 8 (effort S): Read settings from the environment instead of assuming a local setup

### F6 Dependency Health & Longevity: 5 (target 8)

- Finding F6-001 (major, open): Dependencies not declared or pinned (searched for lockfile or manifest (ls -a at repo root))
- Next: **F6-act-1** → 8 (effort S): Pin the dependencies in a lock file and let Dependabot propose updates

### X2 Public API Stability & Upgradeability: 5 (target 8)

- Finding X2-001 (minor, open): No versioning of the HTTP API (searched for API version prefix or changelog (grep -rn 'v1' src/; ls CHANGELOG*))
- Next: **X2-act-1** → 8 (effort S): Version the HTTP API (/v1/...) and keep a changelog of breaking changes

### X3 Concurrency Safety: 5 (target 9)

- Finding X3-001 (critical, open): Check-then-act race on idempotency key (`src/payments/api.py:3-6`: two concurrent requests with the same key can both charge)
- Limit: at most 5 while open critical finding X3-001
- Next: **X3-act-1** → 8 (effort M): Claim the idempotency key atomically (insert-if-absent) before charging, so two concurrent requests can't both charge

### X6 Agent-Readiness: 2 (target 8)

- Finding X6-001 (major, open): No agent instructions or runnable verification commands (searched for AGENTS.md / CLAUDE.md / test command docs (ls -a at repo root))
- Next: **X6-act-1** → 7 (effort S): Add AGENTS.md with the exact commands to install, test and lint

## Limitations

- Example report for the bundled sample repo; scores are illustrative.
- Hidden checks: 4 run, 50% passed.

<sub>Rendered by gradekit from report.json (suite 6.0.0, config 99965e49bb3352f4).</sub>
