# Calibration

The rubric anchors are written in words, so different graders, or the same grader on different days, can drift. Calibration checks that the grader scores known code the way you would.

## Set up (once)

1. **Pick 2–3 reference repos** that resemble what you'll grade. Ideally include one you'd call weak (around 4), one decent (around 6–7) and one strong (around 8–9). Internal repos are best; open-source projects work too.
2. **Freeze each one at a specific commit SHA.** Calibration only means something if the code never changes.
3. **Score them by hand.** One or two experienced engineers set the expected score and applicability for each benchmark, using the rubric. Where reviewers disagree, discuss until you agree; if you can't, the rubric wording is ambiguous and should be fixed. You don't need all 35: the 10–15 that matter most to you is enough.
4. Save one file per repo, following `expected-scores.example.json`:

```json
{
  "suite_version": "4.3.0",
  "reference": "payments-service @ 4f2a9c1",
  "criteria": {"within_tolerance_pct": 90, "mae_max": 0.75},
  "expected": {
    "A1": {"score": 7},
    "A2": {"score": 5, "tolerance": 1},
    "X1": {"score": null, "applicability": "not_applicable"}
  }
}
```

Keep these files with the suite, out of reach of improving agents.

Also keep a `project.toml` for each reference repo, and grade it with that same config every time. Calibration checks the *scores*; weights don't affect them, but zones affect what the grader reads closely.

## Run it

Whenever the rubric changes, the grader model changes, or every few months anyway:

```bash
# grade each reference repo with prompts/grader.md as usual, then:
python3 tools/gradekit.py calibrate payments-report.json calibration/payments-expected.json
```

The grader **passes** when, for every reference repo:
- at least 90% of benchmarks are within tolerance (±1 by default);
- the mean absolute error is at most 0.75;
- every applicability matches where one is specified.

The output also reports **bias**: whether the grader runs generous or harsh on average.

## When calibration fails
- **One benchmark keeps missing:** its anchors are ambiguous. Tighten the wording, or add a concrete example to that benchmark's anchors, then bump the suite's minor version.
- **Consistent bias in one direction:** add a line to `prompts/grader.md` naming the bias, e.g. "Graders tend to over-score E2; a 7 requires architecture docs, not just a README." Or try a different grader model.
- **Large random scatter:** use `gradekit stability` with 3 runs and take the consensus. Recurring unstable benchmarks point to the same rubric problems.

Don't adjust your expected scores to match the grader unless, on reflection, you agree it was right.
