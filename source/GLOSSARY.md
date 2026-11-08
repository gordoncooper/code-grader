# Glossary

The words the suite uses, and what they mean. Prompts, the website and these docs use them exactly as defined here. When a term has alternatives to avoid, they're listed: please don't use them either.

Generated from `rubric/glossary.json` by `gradekit glossary --markdown`. Edit that file, not this one.

## Scoring

**benchmark**: One of the 35 things the suite grades, such as A2 Security & Privacy. Each has a rubric with what to assess and what each score means. *Not:* criterion.

**pillar**: A group of benchmarks (A to F, plus X for the conditional ones). A pillar's score is the weighted average of its benchmarks. *Not:* dimension.

**score**: A whole number from 1 to 10 for a benchmark, set by the grader from evidence. The overall score and pillar scores are weighted averages computed by gradekit.

**applicability**: Whether a benchmark applies to a project: full, limited (counts at most weight 1 and its target is capped) or not applicable (weight 0, no score). Decided by the project's purpose, never its quality.

**weight**: How much a benchmark counts, from 1 to 3 (0 when not applicable). It starts from the base weight and is moved by the project's answers and overrides.

**preset**: A starting set of answers for a kind of project, such as service, library or prototype.

**answers**: A project's replies to the eight questions in `project.toml` (sensitive data, users, lifespan…). Each answer moves specific weights and may make a benchmark a gate.

**config fingerprint**: A short hash of everything in the effective config that affects scores. Reports with different fingerprints were weighted differently. *Not:* config id.

**gate**: A non-negotiable benchmark. A gate at or below the hard floor (3 by default) caps the overall score (at 4.0 by default), and every gate must reach a minimum for each maturity level. *Not:* hard gate, blocker benchmark.

**maturity level**: Where the code stands, from L0 (not viable) to L4 (exemplary), set by fixed requirements on gates, pillars and the overall score.

**target**: The score a benchmark should reach, from its weight (proportional targets: 10, 9 or 8). The improver stops at each benchmark's target.

**rollup**: Everything gradekit computes from a report's scores: pillar and overall scores, gates, maturity, targets, zones and ranked priorities. Never computed by hand. *Not:* roll-up.

## Findings and evidence

**finding**: A specific problem in the code, with an ID (A3-002), a severity, a status and evidence. Findings keep their ID from one report to the next. *Not:* issue ID.

**noticed finding**: A problem first recorded in this report that was already there before: the previous report missed it. It counts as open, but a PR check never fails because of it.

**dispute**: A person's statement, in disputes.json, that a finding is wrong. The next grader answers it: the finding is upheld, or withdrawn.

**withdrawn finding**: A finding a grader agreed was wrong after a dispute. It stays in the report for the record, but counts nowhere.

**severity**: How bad a finding is, by what happens when it bites, where the code runs: critical (serious harm with no reasonable workaround: data lost, money or access wrong, secrets exposed, the core feature down), major (a real defect with a workaround or a limited reach) or minor (little happens).

**effective severity**: Under the scoring rules before 5.0, a finding's severity after its zone: one level higher in a hot zone, one lower in a cold one. Since 5.0 the grader judges severity where the code runs, so it's the same as the severity.

**zone**: A part of the code marked hot (problems there cost more: money, access, important data), normal, or cold (cost less: scripts, examples). Hot zones are read in full, ranked first, and held to a higher bar for maturity. The first matching zone wins. *Not:* critical code, criticality zone, hot path.

**evidence**: What a claim rests on: a code citation (file, lines and exact quote), a command and its output, or an absence (what was searched for and how).

**citation**: Code evidence: a file, line range and the exact quote. gradekit checks every citation against the code.

**strength**: Positive evidence for a benchmark. A score of 9 needs at least one.

**enforcement**: Evidence that a benchmark's quality is kept up automatically (a CI job, a lint rule, a test). A score of 10 needs it.

**accepted finding**: A finding people decided to leave as it is (for example, won't fix by design). It's listed in `dispositions.json` and stops lowering scores. *Not:* waived finding, disposition.

**sensitive finding**: A finding whose details would help an attacker. Its details are withheld from the public report and kept in `report.private.json`.

**hidden checks**: Tests kept out of the graded repo and run against it, to catch a grade that doesn't match behaviour. Off unless you turn them on. *Not:* hidden tests, holdout.

**integrity flag**: Text in the graded repo that tries to influence the grader. It caps maturity at L1 for that report.

**gaming flag**: A sign that code was written to look good to the grader rather than to work better, such as tests that assert nothing.

## Acting on a report

**action**: One step on a benchmark's path to its target, with the findings it resolves, the expected new score and the effort.

**priority**: An action's place in the ranked list gradekit makes from tiers, zones and expected gain.

**tier**: A priority group: fix first (tier 0: a failed gate, or a critical finding in a hot zone), unblocks the next maturity level (1), below target (2), optional (3).

**decision question**: A yes-or-no question a person must answer before an action is done, because it changes behaviour, scope or a public interface.

**decision**: The answer to a decision question, kept in `decisions.json`. Append-only: the newest answer wins. *Not:* approval record.

## Where things live

**grading repo**: The repo that holds every project's grading files: `projects/NAME/` with `project.toml`, `decisions.json`, `dispositions.json` and `reports/`. Separate from the code it grades. *Not:* central repo, grading repository.

**project**: One graded codebase (or part of a monorepo), with its own folder in the grading repo.

**report**: One grading of one commit: `report.json` (the data) and `report.md` (made from it), in `reports/<date>-<commit>/`. Never edited after it's committed.

**public copy**: The report that is committed when sensitive findings are withheld. The full report is `report.private.json`, which is never committed.

**index**: `projects/index.json`: every project's latest score, maturity, history and decisions waiting, made by `gradekit index`.

## Runs

**grader**: The agent that grades the code (`prompts/grader.md`). It never changes the code.

**reviewer**: The agent that checks a grader's report and prepares the decision questions (`prompts/reviewer.md`). People can use the Review page instead.

**improver**: The agent that works down a report's priorities and stops at each benchmark's target (`prompts/improver.md`). *Not:* fixer agent.

**PR checker**: The agent that runs a PR check (`prompts/pr-review.md`). *Not:* pull-request reviewer.

**PR check**: A quick re-grade of only what a pull request touches, against the last report. It passes or fails: any score that drops fails it. On GitLab, the same for a merge request. *Not:* quality check, pull-request check.

**carried forward**: A benchmark copied unchanged from the last report in a PR check, because the change doesn't touch it.

**regression**: Something that got worse: a score that dropped, a finding that came back, or a new critical finding.

**guard**: The improver's before-and-after record of the code's own checks (tests, linters, type checker, build) and of its suppressions and skipped tests. `guard compare` fails if any got worse.

**consensus**: The report made from three independent graders: the median score of each benchmark, with the ones they disagree on flagged.

**delivery**: How an agent hands back its work: a pull request, files saved in a folder, or the chat.
