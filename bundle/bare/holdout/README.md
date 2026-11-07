# Hidden checks (the holdout set)

When agents optimize against a visible rubric, scores can rise without the code actually improving. Hidden checks are a small set of tests and probes that **improving agents never see**. If visible scores rise while the hidden-check pass rate stays flat or falls, the code is being tuned to the rubric. `gradekit diff` flags this as **divergence**.

## Where they live
- In a directory **outside the graded repo** and outside anything improvers can read. Don't put it inside `SUITE_DIR` if improvers can read that; use a separate private location the orchestrator mounts only for grading runs.
- Results go only into `holdout.private_details` in the private report. `gradekit redact` strips them from the shared copy, and `gradekit validate` fails a report if a check's name appears anywhere else in it.

## What makes a good hidden check
Aim for 10–30 checks that test **real quality** in ways the rubric describes but doesn't spell out:

| Kind | Example |
|---|---|
| Edge-case tests | Order with one item and a discount; Unicode names; DST boundary; empty file; 0 and negative amounts |
| Failure injection | Dependency times out; disk full; DB connection dropped mid-transaction |
| Repeat probes | Run setup, seed and migration scripts twice; replay the same webhook; retry the same POST |
| Crash probes | Kill the process during a write; restart; check the data is consistent |
| Adopter journeys | A clean container following only the README; time to first success |
| Gap probes | Things a real user would try that aren't in the docs: `--help`, cancelling an order, pagination beyond page 1 |
| Contract probes | Malformed input on every public endpoint or function; check the error shape is consistent |

Guidelines:
- Each check has a stable name of at least 6 characters (e.g. `holdout-refund-edge-case`, so the leak check works), a pass/fail result and a short note.
- Prefer checks that run automatically (scripts, test files run against the checkout). A few manual "try this as a user" probes for the grader are fine too.
- Rotate about a quarter of the checks every few cycles, so that if any leak through the code itself, they don't stay useful to optimize against.
- Never turn a hidden check into a visible finding verbatim. If one reveals a real defect, the grader describes the defect from its own reading of the code.

## In the report

```json
"holdout": {
  "run": true,
  "checks_run": 12,
  "pass_rate": 0.83,
  "private_details": [
    {"check": "holdout-refund-edge-case", "passed": false, "note": "..."}
  ]
}
```

Maturity levels L3 and L4 require hidden-check pass rates of at least 80% and 95%, when hidden checks are run.
