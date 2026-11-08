# Hidden checks

When agents optimize against a visible rubric, scores can rise without the code actually improving. Hidden checks are a small set of tests and probes that **improving agents never see**. If visible scores rise while the hidden-check pass rate stays flat or falls, the code is being tuned to the rubric. `gradekit diff` flags this as **divergence**.

## Where they live
- In the grading repo, in `projects/<name>/hidden-checks/`. They're hidden by **instruction, not by access**: graders are told to run them, and improvers are only pointed at the report and decisions, never at this folder. If you want stronger separation, keep them in a separate private repo and give that only to graders.
- If the grading repo is public, anyone can read them. That's fine for keeping agents honest, but don't put anything sensitive in them.
- Graders write per-check results to `hidden-checks.json` in the report's folder. The report itself carries only `checks_run` and `pass_rate`.

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
  "private_details": "[see hidden-checks.json]"
}
```

Maturity levels L3 and L4 require hidden-check pass rates of at least 80% and 95%, when hidden checks are run.
