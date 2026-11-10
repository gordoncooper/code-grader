# Calibration

The rubric anchors are written in words, so different graders, or the same grader on different days, can drift. Calibration checks that the grader scores known code the way you would.

## Set up (once)

1. **Pick 2–3 reference repos** that resemble what you'll grade. Ideally include one you'd call weak (around 4), one decent (around 6–7) and one strong (around 8–9). Internal repos are best; open-source projects work too.
2. **Freeze each one at a specific commit SHA.** Calibration only means something if the code never changes.
3. **Score them by hand.** One or two experienced engineers set the expected score and applicability for each benchmark, using the rubric. Where reviewers disagree, discuss until you agree; if you can't, the rubric wording is ambiguous and should be fixed. You don't need all 35: the 10–15 that matter most to you is enough.
4. Save one file per repo, following `expected-scores.example.json`:

```json
{
  "suite_version": "5.0.1",
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

## The calibration program (5.0)

The suite's own calibration lives in `golden/`: one folder per golden repo, each with `expected.json` (the frozen commit and the expected scores), the `project.toml` to grade it with, and `runs/`, one file per independent grader run.

```bash
# a grader grades the golden commit as usual (prompts/cards/grader.md, with the golden's project.toml), then:
python3 tools/gradekit.py calibration add-run calibration/golden/schedule REPORT.json --note "model, session"
python3 tools/gradekit.py calibration run          # writes calibration/results.json and RESULTS.md
```

`calibration run` scores every run against its golden's expected scores (the same test as `calibrate`), and measures the **spread** across runs. A golden repo passes with at least 3 runs (`--min-runs`), every run passing, and no benchmark spreading more than its `criteria.max_spread` (default 1). The program passes when every golden repo does. [`RESULTS.md`](RESULTS.md) publishes the result.

**No scoring change ships unmeasured.** The results record a fingerprint of the scoring rules: the scoring version, every benchmark's rubric and anchors, its caps, and the limits. The kit's tests fail when the rules change and the results haven't been regenerated (`calibration run --check`), so whoever changes the rules must re-run calibration and show its result in the same pull request. Each run records the fingerprint it was graded under (`add-run` writes it), and only runs under the current rules count: after a rule change, the old runs are listed as earlier runs, and the golden repo needs fresh ones.

Runs must be independent: a fresh session for each, which hasn't seen the expected scores or the other runs. Give each grader a copy of the kit without `calibration/` (and without `CHANGELOG.md`, which discusses results), so it can't read them. The first golden repo, `schedule`, has expected scores from the 4.3 release gate's grade, with A1 and E2 changed after the 5.0 gate's runs. Its first three runs were graded before A5's applicability wording was clarified, so they're kept as earlier runs. Runs 4–6 were graded on the clarified rubric: each is within tolerance, but run 5 marks X3 not applicable where the key says limited, and E2 spreads by 2 because one grader filed the broken contributor setup under E2 (with its cap) where the others used E3. Both were clarified. Scoring 5.0 then redefined severity: runs 7–9, the first on the new rules, all gave A1 7 (the key, set before they ran) and reached L2. Two of the three passed. E2 still spread, because two graders let a minor finding hold E2's cap; a cap now needs a major finding. Runs 10–12, on those rules, are each 100% within tolerance (6.9–7.2, all L2). Only E2 still spreads by 2 (8, 8, 6), against a limit of 1. One grader ran the examples and the others only read them, so E2 now has a fixed procedure and sharper anchors. That made runs 10–12 earlier runs. Runs 13–15, three independent graders on the released 5.0.0 kit, each came out 100% within tolerance (MAE 0.28–0.41), with every benchmark's spread at most 1: calibration passes under scoring 5.0.

## When calibration fails
- **One benchmark keeps missing:** its anchors are ambiguous. Tighten the wording, or add a concrete example to that benchmark's anchors, then bump the suite's minor version.
- **Consistent bias in one direction:** add a line to `prompts/grader.md` naming the bias, e.g. "Graders tend to over-score E2; a 7 requires architecture docs, not just a README." Or try a different grader model.
- **Large random scatter:** use `gradekit stability` with 3 runs and take the consensus. Recurring unstable benchmarks point to the same rubric problems.

Don't adjust your expected scores to match the grader unless, on reflection, you agree it was right.
