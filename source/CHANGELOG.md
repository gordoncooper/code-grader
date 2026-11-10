# Changelog

Versioning rules for the suite itself:
- **Major:** a change that can break existing setups: the report format, the prompts' workflow, or the scoring rules. Each project pins the major it uses (`suite = "5"` in `project.toml`).
- **Scoring version:** separate from the kit version, it changes only with rules that can move scores, i.e. new or removed benchmarks, changed anchors, caps, weights, targets or maturity rules. It's `suite_version` in `config/defaults.toml`, part of every config fingerprint. Scores from different scoring majors are **not comparable**, and `gradekit diff` won't treat their deltas as regressions.
- **Minor:** clarified wording that shouldn't move scores, new optional fields, new tool commands. Re-run calibration to confirm.
- **Patch:** typos, formatting, documentation.

After any major or minor change, re-run calibration (`calibration/README.md`) before trusting new scores.

## 5.0.1
Fixes from the 5.0 calibration runs and from the suite's first grade of itself. Calibration now passes under scoring 5.0. No scoring rule changes, so the calibration fingerprint is the same and runs 13–15 count. One thing to know before upgrading:

- **5.0 reports can show a pillar 0.1 higher when re-rendered.** Rounding is now exact (half-up), so a pillar or overall score at exactly .x5 moves up. For example, the self-grade's F pillar goes from 7.2 to 7.3.
- **Graded overall scores and maturity levels stay the same.** The self-grade and all three calibration runs recompute to the same overall score and level.
- **For CI:** `gradekit ci` compares the stored overall score and level, so it passes. A `report.md` rendered by 5.0.0 can get a warning that it differs; `gradekit render report` brings it up to date.

Also new: the grading CI runs a pinned kit, never what the website serves. Upgrade an installed check with `gradekit ci-pin --version 5.0.1`, or with this kit's `gradekit init --ci HOST --force` to also get the new template.

**Calibration passes under scoring 5.0.** Runs 13, 14 and 15 on the `schedule` golden were three independent graders on the released kit. Each is 100% within tolerance (MAE 0.28, 0.41 and 0.31), and no benchmark spreads more than 1 across them. All three gave overall 7.0 and L2, and E2 7 as keyed.

**What the graders ran into**
- **A long citation keeps its first three lines** with a note, instead of being refused. A refusal saved nothing for the whole command, which left half-saved `&&` chains to untangle. `rules.json`'s quote-length check follows the new message.
- **Excerpts are checked as they're added.** For a command recorded with `report ran --output`, an excerpt line that isn't a whole line of the output is refused on entry, not only warned about by `report check`. `grader.md` now says excerpts are whole lines: spacing can differ, `...` stands for lines left out, and a line can't be cut short.
- **One item of a list can be changed or removed:** `report set REPORT limitations.2 "…"`, or `report set REPORT limitations.2 --remove`. Before, the whole list had to be rewritten as JSON.
- **`lint_errors` when nothing runs** uses the language's long-standing default linter (for Python, `flake8`, whose defaults don't drift between versions the way `ruff`'s do), and records its version.
- **`doctor`'s hot-zone warning is addressed to the project's owner**, and tells a grader just to note it under limitations.

**From the self-grade**
- **The open-critical limit (max 5) can't be escaped by leaving a finding off its benchmark's list.** It used to count only the benchmark's `finding_ids`, so a report edited by hand to drop a critical finding's ID could keep C4 at 8. Now a finding counts for a benchmark if the benchmark lists it, or if the finding names that benchmark. Finding caps work the same way. A format-5 report where a benchmark doesn't list its own open finding is now an error, not a "not referenced" warning.
- **`deliver` never ships a stored rollup older than the scores.** It used to keep a stored rollup when the config hadn't changed, even if a score had changed since `report check --write`; `report.json` could say 4.9 L0 while `report.md` said 5.0 L1. Now:
  - `deliver` always recomputes the rollup.
  - Any `report` edit drops a stored rollup, and says so.
  - `report check` warns about a stored rollup that doesn't match the scores.
  - `gradekit ci` already refused one.
- **An open gap explains a low score too:** "score N but no findings explain what is wrong" no longer fires when an open gap names the benchmark.
- **Overall and pillar scores round half-up on the exact values.** `round()` rounded halves to even and worked on floats, so 6.25 showed 6.2 and a mean of 7.95 could show 7.9. Maturity levels are judged on the score as shown. Benchmark scores and calibration are unaffected. A 5.0 report recomputed by 5.0.1 can show a pillar or overall 0.1 higher at an exact .x5. Reports graded under 4.x rules recompute as they were graded.
- **`gradekit init` writes only the answers you give.** The preset's answers are written as comments, so the project keeps following its preset, including improvements in later suite versions. Its "next" line is a command you can run as typed.
- **The website-with-Pyodide download includes the licenses of what it redistributes.** `vendor_pyodide.py` writes `pyodide/THIRD-PARTY-NOTICES.md` and `pyodide/licenses/`: Pyodide's MPL-2.0 with where its source is, CPython's PSF license for the standard library, and each package's license, taken from its own wheel. `--licenses-from DIR` works offline.
- **A report records that its code quotes were checked against the code.** `report check --repo CODE --write` and `deliver --repo CODE` set `run.citations_checked`, with the number of quotes, the date and the kit version. Any later edit drops it. `gradekit ci` can't see the code, so it warns when a format-5 report's quotes weren't checked, or changed after they were. Review's run line says which. This is the lighter alternative to the grading CI reading each project's code, which was declined on the self-grade.
- **Answering decisions keeps `report.md` in step.** `report.md` shows each decision's status, so after any answer the grading check warned that it "differs from what `gradekit render report` makes". `gradekit decide` now re-renders the newest report's `report.md`, and the CI decide jobs commit it with `decisions.json`.
- **The grading CI templates install `jsonschema`.** Without it, every grading repo's check skipped the reports' structural schema check and said so in each comment.
- **The grading CI's kit is pinned.** The templates used to download `fetch-kit.py`, then whatever kit the website served, at run time, and checked it against a checksum from that same website. That ran in jobs that hold write tokens, so a changed site would have gone unnoticed.
  - Now each template names one exact kit zip, with `GRADEKIT_VERSION`, `GRADEKIT_URL` and `GRADEKIT_SHA256`. Every job downloads it and refuses it unless the hash matches.
  - `gradekit init --ci` pins the kit it's run with, by default the suite's release asset, using that release's `SHA256SUMS`.
  - The new `gradekit ci-pin --version X.Y.Z` changes the pin and nothing else. A new kit's `init --ci HOST --force` also brings its template.
  - `--kit-url` and `--kit-sha256` take any copy, for another host or offline.
  - `fetch-kit.py` stays for older workflows. `SUITE_SITE` now only builds the Review links.
- `grader.md` said 4.x and 5.x reports share scoring version 4.2.0. They don't: 5.x is scoring 5.0.0, so a 5.x report isn't compared for regressions with a 4.x one.

## 5.0.0
Major release. The 35 benchmarks and their anchors don't change. **Severity does:** graders judge it by consequence where the code runs, zones no longer shift it, and a rubric cap needs a major or critical finding. That's a new scoring version (5.0.0): config fingerprints change, and a score change against a 4.x report isn't a regression. 5.x still reads 4.x reports and recomputes them under the rules they were graded with, and `gradekit migrate` moves a project over.

- **For agents:**
  - Report format 5 adds *noticed* findings, fingerprints, and who graded and what it took.
  - Short operating cards replace reading whole prompts.
  - `gradekit mcp` serves agents without a shell.
  - Also new: work orders, enforced score limits, finding disputes, monorepo components in every tool, and answering decisions with `gradekit decide`.
- **For people:**
  - A **Projects** page for every project at once, and a Review page that explains every score.
  - Deciding by ticking a box on the report's pull request, and saving files without pasting JSON.
  - A quick setup, a guided first run, and a command palette (Ctrl/Cmd+K).
  - Grading on a schedule, with time and cost on the pages.
- **Every major at its own address** (`/v4/`, `/v5/`), so a project's rules can't change under it.
- **Calibration** is now a program, with golden repos, spread across runs, and a rules fingerprint tests enforce. The `schedule` golden's run under the final 5.0 rules is 100% within tolerance (MAE 0.28). Calibration passes once two more independent runs agree within the allowed spread. A1's expected score is provisional until a person reviews it.

**Versions and pins**
- **Three versions, each with its own job:**
  - the **kit version** (5.0.0): prompts, tools and report format;
  - the **scoring version** (5.0.0, up from 4.2.0): the rules that move scores;
  - each report's `suite_version`: the kit that wrote it.

  New reports also record their scoring version (`config.scoring_version`). `gradekit diff` compares reports for regressions whenever their scoring majors match. Across majors it lists the changes as notes, so a project's first 5.0 grade should be a full one.
- **5.x reads 4.x reports unchanged.** `validate`, `rollup`, `diff`, the index and the Review page accept reports from 4.x and 5.x. Reports from older majors are refused, with a note to re-grade.
- **Projects pin their major:** `suite = "5"` under `[project]` in `project.toml`.
  - `init` and the Set up page write the pin for new projects. A project loaded into the Set up page keeps its own pin, or none.
  - `report new` and `carry` refuse to write a report for a project pinned to another major, and say which kit to use.
  - `doctor` warns when a project isn't pinned, and fails when the pin doesn't match the kit.
  - `gradekit ci` needs changes on a report PR whose report was made by another major than the pin.
  - A project without a pin works as before.

**Report format 5**
- New reports carry `"schema_version": 5`. Reports without it are format 4 (suite 4.x), which 5.x still reads with `schema/report-4.schema.json`. `report new` and `carry` write format 5, so carrying a 4.x report forward upgrades it.
- **`noticed`, a new finding status:** a problem first recorded now that was already there before, because the previous report missed it. It counts as open everywhere (maturity, priorities, the index, Review). A PR check reports it as pre-existing and never fails because of it, so the old workaround (`new` with `first_seen_commit` set to the base commit) isn't needed. 4.x reports still use that rule. `report finding add --status noticed` sets the first-seen commit to the PR's base commit.
- **The quote is the anchor:** `lines` is optional in code evidence. Without it, the check finds the quote anywhere in the file. `report cite` still writes both, for links to the exact lines.
- **UTC timestamps:** `run.started` (stamped by `report new` and `carry`) and `run.date` (stamped by `report check --write` at the finish) are required, as `YYYY-MM-DDTHH:MM:SSZ`.
- **Fingerprints:** every finding gets a `fingerprint` from its benchmark, files and quoted code. Rewording or moving the code doesn't change it, so the same problem is recognized across reports. gradekit writes it (report commands, `report check --write`, `rollup --write`), and `validate` refuses one that doesn't match.
- **Who graded, and what it cost:**
  - `run.model`: required before a report is finished.
  - `run.session` and `run.work_order`: optional.
  - `report new` and `carry` take `--model`, `--session` and `--work-order`. `report check` lists the model as a to-do until it's set.
  - `run.usage` holds minutes, tokens and cost where known. `report check --write` fills the minutes from the two timestamps.
  - `report.md` opens with a line saying who graded, with which model, how long it took, and the work order.
- The grader and PR-check prompts, the glossary (*noticed finding*) and the Review page (status filter; evidence without line numbers) follow suit.
- A public copy keeps each withheld finding's fingerprint, computed from the full report before `redact` withheld its evidence. Editing the public copy never overwrites it.

**Monorepo components in every tool**
- **One report per component:** `report new --component NAME` writes `components/NAME.json` in the report folder, with its component's config. `--component repo` writes the repo report (`report.json`). Each marks the benchmarks graded elsewhere as `not_applicable` for you: the components skip what the repo shares (B3, E3, E4, F2, F6, X6), and the repo report skips the rest.
- **The repo-wide result:** `rollup-repo FOLDER --write` stores it in `report.json` as `repo_rollup`. The overall score is weighted by component weight, and maturity is the lowest component's.
- **The tools that handle reports know components:**
  - `deliver` redacts and renders every component report;
  - `gradekit ci` validates each with its component's config and checks that `repo_rollup` matches;
  - the index shows the repo-wide score and each component's.

**Finding disputes**
- **People dispute a finding:** `gradekit dispute add A3-002 --project NAME --reason "…" --by NAME` appends to `projects/NAME/disputes.json`, which is append-only like `decisions.json` (`gradekit ci` checks it). `dispute list` shows open disputes.
- **The next grader must answer:** `report check` lists each open dispute on a finding in the report as a to-do. `report finding answer REPORT ID --uphold --note "…"` keeps the finding. `--withdraw` gives it the new status `withdrawn`, which counts nowhere: not open, not fixed. The answer records which dispute it answers, which closes that dispute.
- `diff` notes withdrawn findings, the index lists open disputes, and the glossary adds *dispute* and *withdrawn finding*.

**The calibration program**
- **Golden repos:** `calibration/golden/NAME/` holds a frozen commit's expected scores, its `project.toml` and one file per independent grader run (`gradekit calibration add-run`).
- **`gradekit calibration run`** scores every run against its golden's expected scores and measures the spread across runs. It writes `calibration/results.json` and publishes `calibration/RESULTS.md`. A golden repo passes with at least 3 runs, all passing, and no benchmark spreading more than allowed.
- **No scoring change ships unmeasured:** the results carry a fingerprint of the scoring rules (the scoring version, the rubric, the caps and the limits). The kit's tests fail when the rules change without the results being regenerated.
- **Only runs under the current rules count:** `add-run` records the rules' fingerprint with each run. After a rule change, `calibration run` lists the older runs as earlier runs, and they don't count toward a pass or the spread.
- **The first golden repo is dbader/schedule at 82a43db,** with expected scores from the 4.3 release gate's grade. Two independent 5.0 runs both came to 6.8 (L1) and disagreed with it on two benchmarks. A1 changes from 8 to 5: an open critical finding (a zero interval hangs the scheduler) holds it at 5 under the enforced limits. E2 changes from 5 to 7: both runs found only minor documentation problems. The runs also split on whether A5 applies to a library that stores nothing, so A5's Assess line now says: `not_applicable` when nothing must outlive the process, and `limited` when a little does. That wording change makes the first three runs earlier runs. Three fresh runs on the clarified rubric (6.7, 6.9 and 6.7, all L1) each fall within tolerance. Calibration doesn't pass yet for two reasons. One run marks X3 not applicable. E2 spreads by 2 because one run filed the broken contributor setup under E2, where its cap applies, while the other two used E3. Both point at wording to clarify. On scoring 5.0, three more runs all gave A1 7, matching the key that was set before they ran, and all reached L2 (6.6–6.9). Two passed. E2 spread again because a minor finding held its cap, and caps now need a major finding. On those rules, three more runs are each 100% within tolerance (6.9–7.2, L2). The only criterion still missed is E2's spread of 2 (8, 8, 6), against a limit of 1.

**Operating cards, and the rubric one benchmark at a time**
- **Each role has a one-page card** in `prompts/cards/` (grader, pr-check, improver, reviewer): the run as `gradekit` commands, what the tools enforce for you, and the rules only an agent can follow. `AGENT.md` and **Start a run** now send agents to their card. The full prompts stay as the reference for details, and for working without Python.
- **The word budget is checked:** a card and the largest benchmark entry fit in 3,000 words (the grader's: about 1,300, down from 11,000 for the prompt and the rubric).
- **`gradekit rubric A3`** prints one benchmark: what it measures, what it isn't, how to assess it, the anchors and the caps. `gradekit rubric B` prints a pillar, and `--json` gives data. `rubric/rubric.json` holds the whole rubric as data, generated from the rubric files.
- **No rule was lost in the move:** `prompts/rules.json` lists every hard rule in the prompts with what keeps it, either the `gradekit` check that enforces it or the card that states it. A test fails if either goes missing.

**`gradekit mcp`, for agents without a shell**
- An MCP server on stdin/stdout (JSON-RPC 2.0, standard library only). Every command is a tool, with an input schema made from its arguments, so the server and the command line can't drift apart.
- Calls run in-process with `--json` and return the envelope. `cwd` sets the folder a tool runs in. Bad arguments, unknown tools and a missing folder come back as error results, never crashes.
- `gradekit mcp --list` shows the tools.

**Work orders**
- **A work order is the request behind a run:** a role (grade, review, improve or prcheck), a commit or change, a delivery, who asked, and notes. `gradekit order new --project NAME --role grade` writes `projects/NAME/orders/<date>-<role>-<n>.json` and prints the ID to give the agent.
- **The report that answers it closes it:** it records the ID with `report new --work-order ID`, as `run.work_order`. `order list` shows open orders (`--all` shows every one, with the answering report), and `order close` closes one by hand.
- **Checks:**
  - `report check` and `gradekit ci` warn when a report names an order the project doesn't have;
  - `gradekit ci` checks order files as settings: they must be well formed, and only `status` and `closed` may change later;
  - `projects/index.json` lists each project's open orders;
  - `schema/work-order.schema.json` documents the format.

**Enforced score limits**
- **The rubric's caps are data.** Each cap now has an ID in the rubric, e.g. "Quickstart fails → max 4 (`E1-cap-1`)". `rubric/catalog.json` lists every benchmark's caps, and a test keeps the two the same.
- **A finding can carry the cap it triggers:** `report finding add … --cap E1-cap-1` (or `finding update --cap`). The cap holds while that finding is open, and lifts when it's fixed or accepted. A cap with no single finding behind it goes on the benchmark (`report score … --cap E1-cap-1`). D2's "any critical gap" applies by itself.
- **Every benchmark gets a computed limit:** the lowest of its caps, max 5 with an open effective-critical finding, max 8 without strengths and max 9 without enforcement. `rollup.limits` lists every benchmark held below 10, and why.
- **Format-5 reports are held to their limits.** `report score` refuses a score above one and says why, and `validate` (with `report check` and `gradekit ci`) fails it. `report.md` shows each benchmark's limit. 4.x reports, and reports migrated from 4.x, keep warnings, as before.
- The limits themselves didn't change; they're enforced now.

**Severity is consequence; zones raise the bar (scoring 5.0.0)**
- **Severity has a definition now.** Graders judge `critical`, `major` and `minor` by what happens when a problem bites, where the code runs. `prompts/grader.md` Part 4 gives each a definition and examples, and the grader card gives the short form.
  - `critical`: serious harm with no reasonable workaround.
  - `major`: a real defect with a workaround or a limited reach.
  - `minor`: little happens.
  - Style and naming are minor anywhere.
- **Zones no longer shift severity.** Before, a grader judged a finding "as if the code were normal", and the tool moved it a level up in hot zones and down in cold ones. One major-or-minor call then moved a score by 2–3 points (an open critical finding holds a benchmark at 5), and when a zone covered most of the code it moved every benchmark. Now the grader judges consequence in place. A wrong total in payment code is critical on its own merits, and a style nit there stays minor.
- **Hot zones raise the bar instead:** L2 still allows no critical findings in them, and **L3 now also allows no major findings in them**. Hot-zone work still ranks first, and graders still read hot zones in full.
- **The scoring version is 5.0.0,** so config fingerprints change. A 4.x report is resolved with the 4.x rules, which ship as `config/scoring/4.2.0.toml`, so it validates and recomputes exactly as it was graded. Its `report.md` still shows severity → effective.
- **A rubric cap needs a finding that's major or worse.** A minor problem no longer puts a hard limit on a score. Before, a wrong install line for a secondary channel held E2 at 5 for two graders. `finding add --cap` refuses a minor finding, and `validate` warns when a capped finding is later lowered to minor.
- A project that still sets `zone_settings.severity_shift` or `never_downgrade` gets a warning; the settings no longer apply. `doctor`'s hot-zone warning now says why a zone covering everything is a problem: it can't say where problems cost more, and L3 allows no major findings in it.
- The glossary, `rubric/weights.md`, the PR-check prompt and card, and report.md (one Severity column) follow suit.

**Moving a project to 5.x with `gradekit migrate`**
- `gradekit migrate --project NAME` sets the pin (`suite = "5"`), changing only that line of `project.toml`. With `--reports`, it also upgrades the project's 4.x reports to format 5:
  - every judgment, score and stored rollup is unchanged, and `migrated.from` records the version that wrote the report;
  - `run.date` becomes a UTC timestamp, and `config.scoring_version` records the rules the report was graded under;
  - every finding gets its fingerprint (withheld ones from `report.private.json`, which is upgraded too but never committed);
  - in PR reports, a `new` finding first seen at the base commit becomes `noticed`;
  - `report.md` is re-rendered.
- **It runs in three ways:** without flags it's a dry run, listing every file and confirming the scores don't change. `--write` writes into this checkout, but never on the default branch. `--run` makes a branch from the default branch (`migrate/NAME-v5`) and commits; `--push` and `--open github|gitlab` work as in `deliver`. To undo it, revert the pull request.
- **`gradekit ci` knows a migration** (label `grading: migration`). It redoes the migration from the base branch's files and needs changes unless every report file is exactly what `migrate` makes. Anything else in the same pull request makes it an ordinary change, where earlier reports may never be edited.
- `doctor` and the tools' pin messages point to `migrate` for projects pinned to 4.

**Every major version at its own address**
- The suite's site serves the newest release of each major at its own path: `/v4/` and, once released, `/v5/`. The root shows the newest. Each copy is built from its release and checked against its own `SHA256SUMS` before it's published.
- `versions.json` beside each copy lists the versions. With it:
  - the pages show a version menu in the top bar that keeps you on the same page;
  - **Start a run** writes prompts that point at the page's own major (`…/v5/AGENT.md`), so a later major can't change a project's rules;
  - `AGENT.md` sends agents to the version a project pins.
- Every built site ships a `versions.json` that lists only itself, so a single-version host changes nothing and makes no failed requests. It isn't in `SHA256SUMS`, because it describes the host. `DEPLOY.md` shows how to host several majors on your own server.

**What the gate's grader runs asked for**
- **Correcting a report without editing its JSON:**
  - `report show REPORT [ID|features|gaps]` numbers what's recorded;
  - `report update REPORT REF` changes a strength or enforcement item (`A3/strength/2`: text, evidence), an action (`A3-act-1`: text, score, effort, what it resolves, decision, optional, `--why-first`) or a gap (`GAP-002`: severity, necessity, status…);
  - `report remove REPORT REF` removes one of those, a feature, or a finding or gap that no earlier report has. IDs that were reported stay, so carry and diff keep tracking them.
- **Enforcement is shaped like strengths:** `{"note": "what enforces it", "evidence": [...]}`, and `report enforcement` takes `--text`. Format-4 reports keep bare evidence objects, which every tool still reads; `migrate` wraps them. The Review page now shows enforcement.
- **Quotes stay short:** `cite` refuses a quote over 3 lines, which grader.md always required, and drops blank lines at either end of the range (an off-by-one). `validate` warns about longer quotes in format-5 reports.
- **`report check` isn't ready too early:** it lists a missing summary, and every benchmark below its target with no non-optional action to get there.
- **`top_priorities` is filled for you:** `report check --write` copies the first ten of the ranking, each with its `why_first` (the action's own, from `report action --why-first`, or a line from its tier) and expected gain.
- **Each action gains only what it adds:** `expected_new_score` counts the benchmark's earlier actions as done, so a second step from 6 to 8 is worth 2 points in the ranking, not 4. `validate` warns when a later action expects less than an earlier one. Format-4 reports keep the gains their stored rollups have.
- **The run:**
  - `report new` and `carry` take `--started`, so the run's minutes count from preflight rather than from `report new`;
  - `redact --in-place` writes `report.private.json` only when something is withheld;
  - `doctor` warns when hot zones cover most of the code (over half its lines, tests left out), where every major-or-minor call moves scores by 2–3 points;
  - `--out` creates its folder, and a stray argument is reported with the command's own usage.
- **The grader card** adds the time for `--started`, the delivery you were asked for (not always `pr`), `--run N/COUNT`, running tools in a copy so CODE stays clean, the 1–3 line quote and copied command excerpts, the correcting commands, and never lowering a severity to get under a limit.
- **From the second round of grader runs:**
  - `cite` prints the line it quoted, so a cite of the wrong line is caught at once. It also says when it trimmed blank lines. When a quote is too long, it suggests a 3-line range; when a line is blank, it points to the nearest line with text.
  - Command evidence takes `--no-output` for a command that printed nothing.
  - `report ran` takes `--workdir` and `--env`, so a command run in a copy of the code can be run again.
  - `report show` lists metrics and commands too.
  - `report set metrics.X` refuses anything but a number, true/false or null.
  - `report update --not-optional` says "no longer optional".
  - `redact` on a report that's already redacted and withholds nothing does nothing, instead of failing.
  - `validate` warns when an action resolves another benchmark's finding, which would count its fix twice in the ranking.
  - The grader card takes the scratch folder (`SCRATCH`) and the delivery (`DELIVERY`) as values, instead of `/tmp` and `pr`, and shows `deliver` for `save`.
  - The metrics table says which linter counts, how to count unrated advisories, and that `setup_second_run_passes` is `null` without setup scripts.
  - `doctor`'s pin warning says the project's owner should add the pin.
  - The X6 heading prints correctly.
  - From the third round:
    - `report remove command/N` removes a wrongly recorded command.
    - `report set` refuses to turn a list (such as `limitations`) into text, and takes `@file` (for example, all the metrics at once).
    - `report score` notes when a score needs a strength or enforcement it doesn't have yet.
    - Maturity blockers name their benchmark in `report.md`.
    - The card has `doctor` check the scratch folder.
    - The card says everything in a first report is `new`.
  - From the fourth round:
    - **A note per piece of evidence:** each `--note` belongs to the `--cite`, `--command` or `--absence` just before it. A single `--note` still goes on every item, as before. A `--note` before any evidence fills in for items without their own, and one note per item after all the evidence pairs up in order, which is how MCP clients send them.
    - **Command evidence is tied to what was run:** `--command @N` takes the exact text of the Nth command recorded with `report ran`. `report check` warns about an excerpt from a command that isn't in `commands_run`.
    - **Limited first, score later:** `report score REPORT A5 --applicability limited --reason "…"` works without a score. A later `--score` keeps it limited, and `report check` lists the score as still to do.
    - **No half-success:** citations are echoed only once the command succeeds. If anything fails, it says nothing was saved.
    - **`report check --write` says what it stored:** the rollup, the finish time and the minutes, or that the rollup waits until nothing is left to do.
    - **An `export` may not outlast an agent's tool call:** the card makes `SCRATCH` and prefixes commands with `TMPDIR=SCRATCH`, instead of exporting it once.
  - From calibration run 13, the first on E2's fixed procedure (100% within tolerance, MAE 0.28, E2 7 as keyed; two more runs needed):
    - **Several pieces of command evidence in one call:** `--command`/`--excerpt` (or `--no-output`) and `--absence`/`--method` repeat, and pair up in order. A second pair used to replace the first without a word. Unpaired options are refused instead of dropped.
    - **Excerpts checked against what was printed:** `report ran --output FILE` keeps a fingerprint of the output (one short hash per distinct line, not the text). `report check` warns about excerpt lines that aren't in it; whitespace evens out, and `...` elides. `report ran` says the command's number for `--command @N`.
    - **Commands corrected in place:** `report update command/N` takes `--command-text`, `--exit-code`, `--summary`, `--workdir` and `--env`, so `@N` numbers stay put. Evidence quoting the old text follows the new.
    - **`lint_errors` when nothing runs:** if CI runs no linter and the documented one can't run, use the language's usual linter at its defaults, and say which.
    - The grader card saves each command's output for `--output`, and chains `report` commands with `&&` so one that fails stops the rest.
    - The golden `schedule` project pins suite 5, as `doctor` asked.
- **Rubric wording, from where graders split:**
  - X3 is `limited` for code that's often called from threads or async code even though it isn't concurrent itself.
  - A broken contributor setup is E3, even when the fault is in its docs. `E2-cap-1` is for instructions users follow.
  - A quickstart that needs something the documented install doesn't provide fails as written (`E1-cap-1`).
  - F3 is `limited` for a library, which has no telemetry of its own.
  - E2 has a fixed procedure: run every example in the README and the main guide, compare the reference with the public names, and check five behaviors users rely on. Its anchors now say what separates 6 from 7 (an example that misleads, or a wrong statement users rely on), and when a docs error is major. In the last calibration round, one grader ran the examples and the other two only read them, which gave E2 a spread of 2.
- **One version on every label:** the prompts, rubric and README say v5.0.0, and a test keeps them in step with the kit. A new `project.toml` says which kit created it, so an older one doesn't read as a mismatch.

**One component system for the pages (U1)**
- **Every tool page is built from one set of components:** banners, chips, badges, cards, form fields, segmented controls, tables and tabs. Each is built by `common.js` (`UI.banner`, `UI.state`, `UI.chip`, `UI.badge`, `UI.card`, `UI.field`, `UI.seg`, `UI.table`, `UI.tabBar`) and styled once in `style.css`.
- **Loading, empty and error states:** `UI.state` shows what a section has instead of content. A loading state is announced as busy, an empty state can offer the next step, and an error state is announced as an alert, with a "Try again" button. Review now shows a loading state while it reads a report, and a load from GitHub shows one while it fetches. A failed review offers to try again.
- **Colors come only from tokens:** one block for light and one for dark mode, with a background, text and border for each tone. Some dark-mode chips, which had no colors of their own, are now readable.
- **No inline styles anywhere:** every page and generated doc uses classes, and bars take their size from CSS custom properties. The site's policy now forbids inline styles (`style-src 'self'`, no `'unsafe-inline'`), in the pages' `<meta>` tag and in `.htaccess`.
- **The components page** (`app/components.html`, linked from the site's footer) shows every component in each of its states. The tests run axe on it in light and dark mode, check its layout at four widths, and screenshot it. Setup and Review are also checked in dark mode now.
- **Tests keep it that way:** they fail on an inline style, a raw color outside the tokens, or a banner or state built by hand in a page.
- The screenshot baselines are remade for the new look.

**The Projects page: every project at once (H3, H4, H5, U5)**
- **All projects (H3):** every project in a grading repo with its overall score, maturity, a trend line, its stage, and what it's waiting on. Projects that need a person come first. It reads `projects/index.json` from a public GitHub grading repo, from a file (any host), or from the sample.
- **Decisions (H4):** every decision question waiting across all projects, answered in one sitting. Each project's answers are appended to its `decisions.json` by the engine, exactly as on Review, with the steps to save it. From GitHub, the page loads each project's existing `decisions.json` first, so earlier answers are kept.
- **Where it stands (H5):** each project's place in the cycle (set up → grade → decide → improve → check → done) and what's waiting on whom: a grader, people, an improver or a PR checker. From GitHub, it also shows the project's open pull requests.
- **Trends and heatmap (U5):** the overall score and each pillar over every full report, as small charts on one 0–10 scale. Each point's value shows on hover or keyboard focus, and a table has the numbers. Maturity history, and a heatmap of every benchmark in every report on one blue scale, with its own steps for dark mode and a text color chosen for contrast in each cell.
- **The index carries it all, computed by gradekit:** each report's pillar and benchmark scores; each pending decision's benchmark and action; `latest.below_target` and `latest.actions_ready`; and `cycle` (stage and waiting-on). The pages only draw them. `schema/index.schema.json` documents the new fields.
- Review and Projects share the GitHub loader and the "save your decisions" steps (`common.js`). Every table that scrolls sideways can be focused and scrolled with the keyboard.

**Review: explain every score, show evidence as code, link to any view (H6, U3, U6)**
- **Why this score (H6):** each benchmark opens with the grader's reasoning and the limits that hold it (only the ones that bind). It also shows the rubric's words for every score band, with this score's band marked, the caps, and the benchmark's score in every report of the project.
- **Evidence as code (U3):** quoted code is shown with its line numbers and the cited lines marked. Copying it copies only the code. Each quote links to those lines at the graded commit on GitHub, GitLab (including self-hosted) or Bitbucket, using the project's `code_repo`. With the code's zip loaded, it also shows the 3 lines around each quote; a new engine call, `code_context`, reads them, and finds a format-5 quote that has no line numbers.
- **Findings open in place:** a finding's row expands to its evidence, any dispute, the cap it holds, and a button to its benchmark. The note about effective severity appears only for reports graded under the 4.x rules.
- **Print or save as PDF (U3):** the whole report, every section in order, every benchmark and finding open, without the controls. Paper is light even in dark mode, and links print their address.
- **Deep links to every view (U6):** `review.html?repo=…&ref=…&project=…&report=…&compare=…#finding=A3-001` (or `#bench=A3`, or `#tab=decisions`). They work on any host, because they're plain query and hash parameters.
  - The address follows what you look at, and **Copy link** buttons give a link to the view, a benchmark or a finding.
  - `?sample=1` opens the sample.
  - A link to a report opened from files shows its view once the same files are loaded again.
- **Projects links into Review:** each project, and each heatmap cell, opens that report at that benchmark, so every number on Projects traces to code in two clicks. Projects has deep links of its own (`?repo=…#tab=project&project=…`).
- **PR descriptions link to the exact report,** and to its decisions when some are waiting.

**Answering decisions by ticking a box (C5)**
- **`gradekit decide`** records answers in `decisions.json`: `--approve ID…`, `--decline ID…`, `--by NAME`, and optionally `--answer TEXT`. It checks each ID against the newest report, takes the question's wording from it, and only appends. Recording the same answer again changes nothing; a change of mind is appended, and the newest answer wins. An answer by an agent comes with a reminder that it counts only with `[review] allow_agent_decisions = true`.
- **`gradekit decisions`** lists the newest report's questions and their answers. With `--approved`, it lists only what may be acted on.
- **The report PR is a checklist.** `deliver` writes each pending question with a box to approve it and a box under it to decline it, plus a `<!-- gradekit:project=NAME -->` marker. `gradekit decide --from-checklist FILE` reads the ticked boxes and finds the project from the marker. Unticked boxes are no answer, and a question with both boxes ticked is skipped.
- **The grading CI records the ticks:**
  - **GitHub:** a new `decide` job runs whenever a report PR's description is edited and commits `decisions.json` to the PR's branch under the editor's login. It needs `contents: write`. Pull requests from forks are skipped, and the description reaches the shell only through an environment variable.
  - **GitLab:** a manual `grading-decide` job does the same when you press play (GitLab has no event for a description edit). It reads the full description through the API and needs `GRADING_BOT_TOKEN`.
- **`gradekit ci` accepts a report PR that also answers its own questions:** the report folder plus appended entries in that project's `decisions.json`. Any other settings change still goes on its own.
- `report.md` says how to answer.

**Saving without pasting (H2), quick setup (H1), work orders from Start a run (C4)**
- **No page asks you to paste JSON or TOML into an editor.** Each save offers, quickest first:
  1. the code host does it: for a new file, a link to GitHub's or GitLab's new-file page with the file filled in; for decisions, the report PR's checkboxes;
  2. a command, or a prompt for an agent, that writes the file with gradekit;
  3. download, then upload (on any host, or for a local folder).
  No host fills in an edit of a file that already exists, so editing an existing file goes by 2 or 3. Some GitLab versions open the new-file editor empty; the page says so. New helpers: `UI.saveFile` and `UI.saveDecisions` (rebuilt), on Set up, Start a run, Review and the Projects inbox.
- **Quick setup:** Set up asks for the code's address, what kind of project it is, and three questions (data sensitivity, audience, impact of failure). The five other questions, more about the project, zones, targets and overrides are under *More* and *Advanced*, with plain labels. A grading repo address (remembered, and shared with Start a run) enables one-click saving. Starter `decisions.json` and `dispositions.json` are optional: the first answer creates them.
- **Start a run writes work orders:** *Record this run as a work order* makes `projects/NAME/orders/<date>-<role>-<n>.json` (valid against `work-order.schema.json`, saved the same three ways) and adds `Work order: ID` to the prompt, so the report closes it.

**A guided first run (U4)**
- *Take a guided first run* on the home page, or `?tour=1` on any app page, starts six steps on the sample: open a report, find the weakest benchmark, answer a decision, see every project, set up your own project, and get the prompt for its first grade. A bar at the top of every app page shows the progress (kept in this browser), links to the next step, and ends the tour.

**Grading on a schedule (N2)**
- **`[schedule]` in `project.toml`:** `grade_every_days` (0, the default, means no schedule) and `only_if_code_changed` (default true). It never changes scores or the config hash. Set up has it under *Advanced*.
- **`gradekit due`** says which projects are due, and why or why not: never graded, or enough days since the last full grade and, by default, new commits on the code's default branch. `--check-code` reads each code repo's newest commit with `git ls-remote`, without cloning; `--code-head NAME=SHA` gives it instead. A project that already has an open grade order isn't due again. `--write-orders` writes a grade work order for each due project, with `requested_by` "schedule", the commit, and the reason.
- **The grading CI runs it.** On GitHub, a new `schedule` job runs every Monday and on demand. On GitLab, `grading-schedule` runs in a pipeline schedule. Each opens one pull request per due project, since `gradekit ci` wants one project per pull request. Permissions are in `ci/README.md`: on GitHub, letting Actions open pull requests, plus `CODE_READ_TOKEN` for private code; on GitLab, `GRADING_BOT_TOKEN`.
- `write_order` is shared by `order new` and `due`.

**Time and cost on the pages (N3)**
- **The index** carries each report's `model` and `usage` (minutes, tokens, cost, where recorded), and each project's `schedule` when it has one. `index.schema.json` describes them.
- **Review** says who graded, with which model, how long it took, what it cost, and the work order, or that the report didn't record them.
- **Projects:**
  - *All projects* adds agent time and cost over the last 30 days. Each row shows its last grade's time and cost, and *due* or the next date when it's on a schedule.
  - *One project* adds a **Time and cost** card, with the average full grade and every run's model, time, tokens and cost. It also says when the project is next due.

**A command palette (U2)**
- **Ctrl/Cmd+K, or Search in the top bar, on every app page** searches the pages, every doc, every benchmark's rubric section and every glossary term (with its definition).
- **On Review:** this report's tabs, benchmarks (with scores) and findings, which open in place, plus print.
- **On Projects:** its projects and tabs.
- **Accessibility:** it's a modal `dialog` with a combobox and listbox. Arrows move, Enter opens, and Esc closes and returns focus.
- The build writes `assets/search.js` from the docs, the rubric and the glossary.

## 4.3.0
Minor release: tools that let agents run the whole cycle without custom scripts, and safer publishing. No scoring changes; config fingerprints and existing reports stay valid. Tested by running the whole cycle on a real repository (dbader/schedule) with `gradekit` commands only: it reproduced the 4.2.2 grade exactly.

**Writing reports with `gradekit report`**
- Graders build `report.json` with commands instead of typing JSON. The tool fills in every benchmark with its name, weight and target, copies each quote from the code so citations always verify, and picks the next free finding, gap and action IDs (never reusing an ID from the project's earlier reports; an ID only mentioned in text, such as a command's summary, doesn't count as taken).
  - `report new` starts a report in `projects/NAME/reports/<date>-<commit>/` (or `runs/run-N.json` for several graders), with previous scores filled in.
  - `report finding add|update`, `score`, `strength`, `enforcement`, `action`, `gap`, `feature`, `flag`, `ran` and `set` record judgments. `report feature` with a name already in the inventory updates that feature, e.g. to replace a citation `carry` couldn't move. `report ran --command` records a command exactly as run; notes go in `--summary`. Evidence comes from `--cite FILE:LINES --repo CODE`, `--command CMD --excerpt TEXT` or `--absence WHAT --method HOW`.
  - `report cite FILE:LINES` prints one evidence object with the exact quote.
  - `report check` runs validation, citation checks and the rollup, and lists what's still missing. Exit code 0 means ready, 5 not finished yet, 1 errors. `--write` stores the rollup and the finish time.
  - Every `report` command takes `--json`.
- The grader prompt shows the commands. Hand-written reports still work.

**Carrying a report forward with `gradekit carry`**
- `carry LAST_REPORT --repo CODE --commit SHA` starts the next report from the last one. Every finding keeps its ID, and every code citation moves to where that code is now. Citations whose lines changed or disappeared are listed, so each one is re-checked rather than silently going stale. Quotes that are part of a line work too.
- **PR mode** (the default, with `--base-commit`): untouched benchmarks are marked `carried_forward`, and the touched ones are cleared for re-grading. The touched benchmarks are suggested from the changed files, which come from git when `--repo` is a checkout: the benchmarks whose evidence cites a changed file, the ones every code change re-grades, and the gates when a hot-zone file changed. `--touched` adds more.
- **Full mode** (`--mode full`): every score is cleared for a fresh grade, but findings and their IDs carry over. The new report folder is made for you.
- `report match REPORT --baseline LAST_REPORT` suggests which earlier finding each newly written finding is, comparing benchmark, files, quoted code and wording. `--apply` renames the clear matches back to their earlier IDs.
- `report score` now clears `carried_forward` on the benchmark it scores.
- The grader and PR-check prompts use these commands, so a PR check no longer needs custom scripts.

**Markdown made from the data with `gradekit render`**
- `render report` writes `report.md` from `report.json`, with the same sections every time: summary, gates and maturity, scorecard by pillar, applicability notes, top priorities, decisions, metrics, findings, feature inventory, gap register, per-benchmark detail, flags and limitations.
- `render pr` gives the grading pull request's branch, title and body, with the decision checklist and a link to the Review page.
- `render check` gives the PR-check comment from the baseline and PR reports.
- `render log` gives the improver's log from a small JSON file, listing pending decisions as blocked by itself. An action's `commit` may name several commits.
- Public text never carries withheld details. In a public grading repo, `render report` and `render pr` withhold sensitive findings even before `redact` has run, and PR-check comments always do.
- New optional report fields: `summary` (set with `report set summary`) and each benchmark's one-line `rationale` (`report score --rationale`).
- The prompts use these commands. The example reports' `report.md` files are now rendered.

**The improver guard with `gradekit guard`**
- "Never trade one benchmark for another" is now checked, not just asked for.
  - **`guard snapshot CODE`**, before any change, runs the code's own checks and records each one's exit code and counts. The checks come from `--check NAME=COMMAND`, the test, lint, type-check, coverage, build and audit commands the grader ran (`--from-report`), or a small detection from the repo. The counts are tests passed, failed and skipped, lint and type problems, formatting, known vulnerabilities and coverage, read from pytest, unittest, jest, vitest, mocha, go, cargo, rspec, ruff, mypy, tsc, eslint, pylint, black, pip-audit and npm audit. From a report it drops graders' notes after a command (`pytest -q  (without pytz)`) and leaves out commands that install packages. It also counts suppressions and skipped tests in the code and fingerprints CI and lint settings. The snapshot is kept in `.git/`, so it can't be committed.
  - **`guard compare CODE`**, after, runs exactly the same commands again. Exit code 2 means something got worse: a check that now fails or times out, fewer tests passing, more failures or problems, lower coverage, more suppressions or skipped tests, or a check that wasn't run. `--explain KEY="reason"` records a deliberate change instead. Changed CI or lint settings are listed for review.
- `render log --guard` puts the before → after table in the improvement log, so the pull request shows the proof.
- The improver prompt takes a snapshot before its first change and compares after each one.

**CI for grading repos**
- `gradekit ci --base origin/main` checks a pull request to a grading repo. It needs only git, so it runs on any host.
  - **One kind of change per pull request:** either one new report folder (`report.json`, `report.md`, `runs/*.json`), or a project's settings (`project.toml`, `decisions.json`, `dispositions.json`, `org.toml`). Anything else, or a mix, needs changes.
  - **Reports:**
    - the report is valid and safe to publish in a public repo;
    - its stored rollup matches its scores, so no hand edits;
    - the folder name matches the graded commit;
    - no `*.private.json` is committed;
    - earlier reports are never edited;
    - `report.md` matches `render report` (a warning).
  - **Settings:** decisions and dispositions are append-only, and their entries have the fields they need. The config resolves, and a change to the scoring config is flagged.
  - **Output:** a summary comment (score, maturity, gates, the decisions waiting as a checklist, a link to the Review page) and the labels `grading: report`, `grading: settings` or `grading: needs changes`. Exit 1 when changes are needed.
- New `ci/` folder in the kit:
  - a GitHub Actions workflow, and a GitLab CI job that comments and labels when given a `GRADING_BOT_TOKEN`;
  - `fetch-kit.py`, which downloads the kit from your suite website and refuses it unless it matches the published checksum.
- `gradekit init --ci github|gitlab --site URL` installs the check. It never overwrites an existing `.gitlab-ci.yml`.

**Supply-chain trust**
- **Pyodide is pinned and checked.** `assets/engine-config.js` holds the SHA-384 hash of every Pyodide core file: the loader, its WebAssembly runtime, the standard library and the lock file. The pages load them with subresource integrity, so the browser refuses any file that doesn't match. Packages are checked against the (checked) lock file. A changed CDN or a wrong self-hosted copy stops the engine with a clear message instead of running.
- **The kit's own files** that the pages run (`gradekit.py`, the config, catalog and schema) are checked against the site's `manifest.json`, so a half-finished deploy or an edited file is refused.
- **A strict content-security policy on every page**, as a `<meta>` tag so it works on any host:
  - scripts only from the site and jsDelivr, never inline, and no `eval`;
  - connections only to the site, jsDelivr and GitHub;
  - no forms or plugins.

  `.htaccess` also sends it as a header, with `frame-ancestors 'none'`.
- **A website with Pyodide included.** Each release adds `code-grading-suite-web-pyodide-vX.Y.Z.zip`: the website with its Python runtime and packages in `pyodide/`. It loads nothing from a CDN, so it works on air-gapped networks and on hosts that allow only their own origin. The new `tools/vendor_pyodide.py` does the same to any built or deployed site. It checks every file against the pins and Pyodide's lock file, switches the pages over, and updates `manifest.json` and `SHA256SUMS`. Relative Pyodide addresses in `engine-config.js` now resolve from the page.
- **Signed releases:** every release has `SHA256SUMS`, and its zips carry signed build provenance (Sigstore, keyless). The release notes show how to check both.
- **New tests:**
  - every page carries the policy, and every page and state works under it with no violations;
  - the real engine starts under it with every file verified;
  - tampered Pyodide files and an edited kit file are refused;
  - the pins match the published Pyodide.

**One vocabulary**
- **`rubric/glossary.json`** defines the suite's 44 terms, from *benchmark* and *gate* to *effective severity*, *accepted finding* and *PR check*. It also lists alternatives to avoid.
- **Generated from it:**
  - **`GLOSSARY.md`**, a new docs page;
  - **the website's "?" help** next to key terms (gates, zones, presets, targets, weights, pillars, maturity, delivery…);
  - **`gradekit glossary [TERM]`**, which also accepts an avoided word and says which term to use.
- **Every prompt** points at the glossary.
- **Tests keep the alternatives out** of the prompts, docs, rendered reports and every page's visible text. File names such as `dispositions.json` are still fine.
- **Wording made consistent:**
  - "PR check" (was also "quality check" and "pull-request check"); the PR-check comment now starts **PR check: PASS/FAIL**, and the PR-check role is the *PR checker*;
  - "rollup";
  - "grading repo";
  - "zones" (Setup's step 5 is now *Mark hot and cold zones*, since "critical" is a severity);
  - "accepted findings";
  - "hidden checks";
  - "busiest code paths" in F4, so it isn't mistaken for a hot zone.

**Start a run remembers your projects**
- **Saved settings:** each project's settings are kept in your browser: where the agent runs, where the code and grading files are, the suite, the number of graders, the improver's budget and source, guidance, code size, and the delivery you chose for each task. A **Your projects** row restores them in one click. Per-run details (commit, pull request, branch, report) start empty each time. Up to 8 projects are kept, and each can be forgotten.
- **What to expect:** a rough agent time for the task and code size (for example, grading a medium codebase takes about 45 min to 1.5 h, and a PR check 10–25 min), what drives the cost, and your part.
- **Where you are in the cycle:** grade → decide → improve → check, with what comes next.

**Accessibility**
- Every page now passes axe-core's WCAG 2.2 AA and best-practice rules, at desktop and phone width, in every state tested: each Review tab with a report loaded, Setup filled in, Start a run with three graders, and every docs page. Fixed along the way:
  - **Tabs** follow the ARIA tabs pattern: a tab list, tab panels, one tab in the Tab order, and arrow keys, Home and End to move between tabs.
  - **Landmarks:** each page has a `main` landmark and a "Skip to content" link, and status messages are announced.
  - **Drop zones** have a real "choose files" button inside, instead of a whole box posing as one.
  - **Scrolling content:** code blocks, generated output and tables that scroll sideways can be reached and scrolled with the keyboard.
  - **Focus outlines** show on every control.
  - **Tap targets** are at least 24×24 px, a WCAG 2.2 requirement (summaries, small buttons).
  - **Motion** is reduced for people who ask for it.
- **Narrow screens:** the home page and the Review overview no longer scroll sideways at 320 px; long gate badges wrap. The top bar wraps its links from 900 px down instead of overflowing at tablet width.
- **New tests:**
  - axe-core on every page and state;
  - keyboard checks: every control reachable with Tab and showing focus, the skip link, tabs, choosing files;
  - layout checks at 320, 390, 768 and 1280 px: no sideways scrolling, no tiny, overlapping or cut-off controls;
  - screenshot comparison, which CI runs against baselines it makes and keeps itself.

**`projects/index.json`**
- `gradekit index` writes one file listing every project in a grading repo. For each project it has the description and preset, the latest full report (score, maturity, next level, failed gates, open findings by effective severity), the decisions still waiting, and the history of every report. Dashboards and the Review page read it. It's derived from the reports and settings with no timestamps of its own, so `index --check` tells whether it's current. Its format is in `schema/index.schema.json`.
- **The CI templates rebuild it** when reports or decisions land on the default branch:
  - **GitHub:** a second job with `contents: write`.
  - **GitLab:** a job that runs only with `GRADING_BOT_TOKEN`.
- **`gradekit ci`** lets a pull request include the index only if it matches what `gradekit index` makes.
- **The Review page**, loading a grading repo with several projects from GitHub, lists them with their scores and decisions waiting from the index, one click each.
- The example grading repo has its index.

**One engine**
- The Review page no longer re-implements gradekit's rules in JavaScript. It calls the engine for:
  - which projects a folder, zip or repo holds (`scan_layout`, from the file paths alone, so files are only read once a project is chosen);
  - the order of reports (`order_report_folders`, which names the few reports whose `run.date` it needs);
  - what each dropped file is (`classify_files`).
- The command line uses the same functions, so the page and the CLI can't disagree. A test keeps the JavaScript copies from coming back.
- A role you pick for a dropped file is now kept: a newer report no longer takes over the "report to review" slot you chose.
- Fixed: dropping a grading repo zip and a code zip together could skip the citation check, if the zip of the code arrived before the report's review had finished.

**A preflight with `gradekit doctor`**
- `doctor` checks, before a run starts, everything the run will need, so a missing permission shows up in seconds rather than after an hour of grading:
  - Python 3.11+, the kit itself, jsonschema (optional) and a writable temp folder;
  - the project's config, `decisions.json` and `dispositions.json`, a writable reports folder, and whether to start with `carry` or `report new`;
  - the code (`--repo`).
- `--delivery pr` adds git, a committer identity, reading the remote and its default branch, and permission to push (a dry run, so nothing is pushed). `--open github|gitlab` adds `gh` or `glab` sign-in.
- `--site URL` checks that the suite website is reachable from the sandbox, that it serves this kit's version, and that the kit's files match the website's copy.
- Each problem comes with its fix. Exit 1 if anything fails. The grader and PR-check prompts run it first.

**Handing reports back with `gradekit deliver`**
- `deliver REPORT --delivery pr|save|return` does what the grader prompt's delivery table says, for any host. Every delivery starts the same way:
  - it refuses an unfinished or invalid report (exit 5 or 1, with the list);
  - it stores the rollup, and withholds sensitive findings in a public grading repo;
  - it checks the report is safe to publish and renders `report.md`.
- **`pr`** prints the branch, commit, title and body, or does the git steps with `--run`. The branch starts from the remote's default branch, or `--base`. Only the report folder is committed, never a `*.private.json`, even without a `.gitignore`. It refuses to commit onto the default branch, and running it again is safe.
- `--push` pushes the branch. `--open github` or `--open gitlab` opens the pull request with `gh` or `glab` when they're installed and signed in. Without them, it says what to open by hand, and the body is written to a file.
- **`save`** leaves the folder in place. **`return`** prints the fenced blocks for the final message, with the private report labeled.
- The example grading repo now has the `.gitignore` that `gradekit init` writes.

**JSON output and exit codes for every command**
- Every command takes `--json` and prints exactly one JSON object: `{ok, exit_code, command, result, text}`, plus `error` on failure. `result` is the command's data (validation errors and warnings, the rollup, the diff, citation results, the resolved config, written paths…), and `text` is what it would have printed, so agents never parse text.
- One exit-code table for every command: 0 ok, 1 failed or error, 2 regression, 3 unstable runs, 4 calibration failed, 5 report not finished, 64 bad arguments. Bad arguments used to exit 2, the same code as a `diff` regression.
- The `report` and `render` commands' JSON now uses the same envelope (their data is in `result`).
- `gradekit` no longer changes the SIGPIPE handling of a Python process that imports it; only the command line does.

**Safe publishing for public grading repos**
- Graders mark findings whose details would help an attacker (an exploitable vulnerability, a leaked secret) with `"sensitive": true`.
- `gradekit redact --in-place` splits a report into a public `report.json` and a full `report.private.json`, which is never committed (`gradekit init` adds `*.private.json` to the grading repo's `.gitignore`). In the public report, a sensitive finding keeps its ID, benchmark, severity, status and the files it concerns, so scores, gates, zones and priorities are exactly the same; its title, quotes and commands, and the wording of the actions and decision questions that fix it, are withheld. `redact` refuses to write anything while withheld text still appears elsewhere in the report, and says where.
- `gradekit redact` (without `--in-place`) withholds sensitive findings too, as well as hidden-check details.
- `gradekit validate --publish` fails until a report is safe to commit. In a public grading repo, `validate` also warns about open security findings of major severity or worse that aren't marked sensitive.
- New `[publishing]` settings: `public` (default true), `sensitive_benchmarks` and `warn_at`. They don't affect scores or the config fingerprint. See TUNING.md.
- Report format: optional `sensitive` on findings, a `withheld` evidence type (written only by `redact`) and a `publishing` block.
- The grader, improver and PR-check prompts say how to handle sensitive findings. `verify-evidence` counts withheld evidence separately.
- **Review a report** marks sensitive and withheld findings, warns when a report isn't safe to commit to a public grading repo, and downloads a copy that is (refusing, with the places to fix, if withheld text still shows elsewhere).
- **Set up a project** has an option for grading repos that only trusted people can read.
- The example grading repo's security finding A2-001 is now withheld, as a grader would publish it.

## 4.2.2
Patch release from an end-to-end run of the whole workflow on a real repository. No scoring changes; config fingerprints and existing reports stay valid.

**Fixes**
- **Reports from the same day are ordered correctly.** Report folders are `<date>-<commit>`, so two from one day were ordered by commit hash, and "latest" could be the older one. Tools and the Review page now order same-day reports by `run.date`. Graders now write it as a UTC timestamp (e.g. `2026-11-07T21:04:00Z`); a plain date still works. The prompts explain which report counts as newest.
- **Citation checks against a zip** no longer strip the leading dot from paths, so quotes from `.github/`, `.gitlab-ci.yml`, `.env.example` and similar files are found. Zone patterns for dot-folders now match only those folders.
- **PR checks (`gradekit diff`):** a finding counts as new only if its ID isn't in the baseline. Findings copied over unchanged with status `new` no longer fail a PR. A problem that already existed before the change (`first_seen_commit` is the PR's base commit, or the baseline's commit) is reported as pre-existing and doesn't fail it either. `pr-review.md` explains how to record one.
- **Review a report, from GitHub:**
  - Reads every file at the branch's current commit, so answers committed a moment ago show up right away. Before, GitHub's file cache could serve the old `decisions.json` for several minutes.
  - No longer logs a 404 for each report without a `runs/` folder.
  - Says when `projects/` exists but is still empty.
  - Explains GitHub's 60-requests-an-hour limit for anonymous users, including when it resets, instead of showing a bare 403.
- **Review a report** loads Pyodide's `jsonschema` package for the full report-format check. If it can't, the page shows a note instead of a report warning, so a valid report reads "Valid".
- **Set up a project:** the downloaded `project.toml` names the real project in its "Check it with" line.

**Layout and usability**
- **Phones:** pages no longer scroll sideways (wide tables and code blocks scroll inside their box), and the main navigation stays available as a second row of the top bar.
- **Set up a project:**
  - Gate chips sit together.
  - Two-column fields line up.
  - Answer dropdowns are wider and show the full answer on hover.
  - The "Level" field appears only for the level target.
- **Review a report:**
  - The overview cards line up.
  - The Load button keeps its size.
  - The findings table keeps IDs, severities and zones on one line.
  - The maturity ladder fits its card on phones.
  - Decision answers use the normal text font.
  - `code` in questions and actions is formatted.
- Any element with the `hidden` attribute now stays hidden whatever its CSS display.

## 4.2.1
Patch release with no scoring changes. Config fingerprints and existing reports stay valid.
- **Review a report** with a zip or folder no longer lists the suite's own example project. When you load a whole grading repo that also contains a copy of the suite (for example in `bundle/`), projects inside that copy are skipped. You still see the example if it's the only project there. `gradekit`'s `scan_zip` behaves the same way.
- **Fixed:** a zip with several projects now shows the "Pick one" project picker. In 4.2.0 it was cleared as soon as it appeared, so nothing loaded.
- `config/defaults.toml` keeps `suite_version = "4.2.0"`, now documented as the version of the scoring rules. It changes only with major or minor versions, so patch releases don't change config fingerprints.
- Generated `project.toml` headers and the website's info call report the kit version (4.2.1); the info call also returns `scoring_version`.

## 4.2.0
Scoring rules are unchanged; scores remain comparable with 4.x.
- **A central grading repo** replaces the `.grading/` folder inside code repos. Each project gets `projects/<name>/` with `project.toml`, `decisions.json`, `dispositions.json` and `reports/<date>-<commit>/` (one folder per report, never overwritten). Code repos stay untouched.
- **Decisions and accepted findings are separate files again** (`decisions.json`, `dispositions.json`), append-only.
- **Graders deliver by pull request by default** (branch `report/<project>/<date>-<commit>`; never to the default branch), or save locally, or return in chat. Decisions go on the report PR, or in a follow-up `decisions/<project>/<date>` PR.
- **Every prompt states the permissions** each delivery option needs.
- **Review a report** loads a whole project: from the grading repo (including a report PR, with deep links), a local folder, or a zip. It picks the latest and previous reports automatically, and lets you choose others.
- **Set up a project** adds the code repo, project name (defaulting to the repo's name) and subfolder for monorepos.
- **Start a run** asks for the grading repo and project name, and the improver can either read from the grading repo or be handed files.
- `gradekit`: `--project NAME` / `--project-dir`; `init --project`; `diff` defaults to the latest two reports; `scan_zip` for the website.
- Removed: `.grading/`, CODEOWNERS guidance, and the pull-request rule about grading files.

## 4.1.0
Scoring rules are unchanged, so scores remain comparable with 4.0.0. Config fingerprints changed: re-run `resolve` before validating older reports.
- **The website is now a set of tools:** **Set up a project**, **Start a run** and **Review a report** run `gradekit.py` in the browser via Pyodide. Nothing to install, and nothing uploaded. Plus a new **Getting started** tutorial with common setups.
- **One grading folder:** `.grading/` in the repo (or anywhere else) holds `project.toml` and the latest `report.json` / `report.md`. Graders read the previous report from there, and git history keeps the older ones.
- **Accepted findings and decisions moved into `project.toml`** as `[[dispositions]]` and `[[decisions]]`, replacing the separate JSON files. Decisions are matched to actions by ID and question text. Agent answers count only when `[review] allow_agent_decisions = true`.
- **Flexible delivery:** graders deliver by pull request, commit, saved files, or back in the chat. Every prompt starts with an inputs table with defaults. New **reviewer** prompt for agent reviewers.
- **Pull-request checks** read their baseline from the base commit, and fail improvement PRs that touch the grading folder.
- Hidden-check details stay next to the checks instead of in the report.
- `gradekit`: `init --grading-dir`; finds `.grading/project.toml` and `.grading/report.json` automatically; `verify-evidence` accepts a repo `.zip`; reusable library functions and a `web_api()` used by the website.
- The config fingerprint now covers only what affects scoring; project prose, dispositions and decisions are excluded.

## 4.0.0
Weights changed, so scores are **not comparable** with 3.x.
- **Everything tunable is now config:** `config/defaults.toml` (commented), layered with an optional org config and a per-project `project.toml`. Replaces `rubric/weights.json`; the benchmark list moved to `rubric/catalog.json`.
- **Weights from questions instead of fixed profile columns:** eight questions about the project (data sensitivity, audience, lifespan, failure impact, team, change rate, delivery, scale) adjust base weights. Presets supply typical answers; overrides need a written reason. `gradekit resolve --explain` shows the reasoning behind each weight.
- **Gates:** Correctness and Security always, plus benchmarks added by answers (e.g. handling money makes Idempotence and Durability gates). A failed gate caps the overall score; maturity levels set gate minimums (replacing "Pillar A minimum").
- **Criticality zones:** hot, normal and cold code. Findings get an effective severity shifted by zone. Maturity levels limit open findings by effective severity and zone, and hot-zone work ranks first.
- **Ranked priorities** computed by `gradekit rollup` (tiers, then weight × gain × zone ÷ effort), instead of being ranked by the grader.
- **New commands:** `init`, `resolve`, `presets`. Every command that scores takes `--config`. Reports record the config hash, and `validate` rejects a report checked against a different config.
- **Report changes:** `config` block replaces `profile` / `target_mode` / `target_overrides`; `config_weight` replaces `profile_weight`; findings may carry `paths`.
- Requires Python 3.11+ (built-in TOML reader).
- New `TUNING.md` and `config/project.example.toml`; `rubric/weights.md` now explains how scoring works.

## 3.1.0
- **Web version:** `tools/build_web.py` generates a static site you can host on any web server. It has a landing page, an `AGENT.md` entry point agents can be pointed at, rendered docs, raw files, a downloadable zip, and `manifest.json` / `SHA256SUMS` for checking downloads. See `DEPLOY.md`.
- Optional `run.suite_source` field records where the suite came from.
- No scoring changes: scores remain comparable with 3.0.0.

## 3.0.0
- Split into a kit: grader, improver and pull-request prompts; one rubric file per pillar; canonical `weights.json`; JSON Schema; `gradekit.py`.
- **Integrity and safety rules:** repo content is evidence, never instruction; attempts to influence the grader become integrity flags that cap maturity at L1; grading runs sandboxed.
- **Independence and hidden checks:** a fresh grader for every run, hidden checks kept from improvers, redacted shared reports, and divergence detection.
- **Metrics block:** raw measurements recorded alongside scores.
- **Calibration:** reference repos with expected scores; stability across runs via median consensus, with unstable benchmarks flagged.
- **Targets:** proportional, maximal or level-based, with per-benchmark overrides, replacing "10 everywhere".
- **Findings:** stable IDs, statuses, and human dispositions.
- **Evidence:** exact-quote code citations, checked by `verify-evidence`; absence evidence.
- **Actions:** `requires_human_decision` with a decision question.
- **Pull-request quick mode** with a pass/fail verdict.
- **Monorepo support** via per-component reports and `rollup-repo`.

## 2.0.0
- Expanded to 29 core benchmarks in 6 pillars plus conditional benchmarks; added "Not this" boundaries, profile weights and the maturity ladder; added applicability (`full`, `limited`, `not_applicable`) and weight notes.

## 1.0.0
- First version: 15 core benchmarks and 4 conditional ones in a single prompt.
