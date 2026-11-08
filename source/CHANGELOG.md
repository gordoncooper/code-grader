# Changelog

Versioning rules for the suite itself:
- **Major:** a change that can break existing setups: the report format, the prompts' workflow, or the scoring rules. Each project pins the major it uses (`suite = "5"` in `project.toml`).
- **Scoring version:** separate from the kit version, it changes only with rules that can move scores, i.e. new or removed benchmarks, changed anchors, caps, weights, targets or maturity rules. It's `suite_version` in `config/defaults.toml`, part of every config fingerprint. Scores from different scoring majors are **not comparable**, and `gradekit diff` won't treat their deltas as regressions.
- **Minor:** clarified wording that shouldn't move scores, new optional fields, new tool commands. Re-run calibration to confirm.
- **Patch:** typos, formatting, documentation.

After any major or minor change, re-run calibration (`calibration/README.md`) before trusting new scores.

## 5.0.0 (unreleased)
Major release, in progress: a beta for agents first, then the pages for people. The 35 benchmarks, their anchors and the scoring version (4.2.0) don't change, so config fingerprints stay the same and scores stay comparable with 4.x.

**Versions and pins**
- **Three versions, each with its own job:**
  - the **kit version** (5.0.0): prompts, tools and report format;
  - the **scoring version** (still 4.2.0): the rules that move scores;
  - each report's `suite_version`: the kit that wrote it.

  New reports also record their scoring version (`config.scoring_version`). `gradekit diff` compares reports for regressions whenever their scoring majors match, so a PR check of a 5.0 report against a 4.x baseline still fails on a dropped score.
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
