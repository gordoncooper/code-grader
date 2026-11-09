# Getting started

This guide takes you through a first full cycle: set up a project, have an agent grade it, review the report, and let an agent improve the code. It takes about 20 minutes of your time, plus however long your agents take. **Nothing to install.** You use three pages on this website and whatever coding agent you already have, cloud or local.

## The idea in one minute

Four jobs, each done by a separate agent session (or by you):

| Job | Who | What happens |
|---|---|---|
| **Grade** | An agent | Reads the code, runs its tests and tools, and scores 35 benchmarks from 1 to 10 with evidence. Produces `report.json` and `report.md`. |
| **Review** | You (or an agent helping you) | Checks the report, compares it with the previous one, and answers the few questions that need a person's call. |
| **Improve** | An agent | Works down the report's ranked to-do list and opens a pull request on your code. |
| **Check** | An agent | On each code pull request, re-grades only what changed, and fails anything that made the code worse. |

A fresh grader session each time keeps the grading honest: an agent never grades its own work.

## Where things live

Your code repos stay untouched. Everything about grading lives in **one central grading repo** (or, if you prefer, plain local folders with the same layout):

```
grading/                          your grading repo
├── README.md
├── org.toml                      optional: house rules for every project
└── projects/
    └── orders-api/               one folder per graded codebase
        ├── project.toml          settings: preset, answers, zones, targets
        ├── decisions.json        your answers to decision questions
        ├── dispositions.json     findings you've accepted as-is
        └── reports/
            ├── 2026-10-24-9f8e7d6/      one folder per report
            │   ├── report.json
            │   └── report.md
            └── 2026-11-07-a1b2c3d/
```

- **A report is never overwritten.** Each grading adds a dated folder. The newest folder is the latest report, and the one before it is what it's compared with.
- **People own the three project files.** Graders only add report folders, through pull requests. Improvers only read.
- **The suite itself** (rubric, prompts, tools) lives on this website.

## Your first cycle

### 1. Set up the project (about 5 minutes, once)

Open **[Set up a project](../app/setup.html)**.

1. **Enter the code repository.** The project name fills in from it (e.g. `orders-api`). For a monorepo, add a subfolder (`apps/web`) and give each part its own project.
2. **Pick a preset** that's closest to your project (e.g. *service*, *web app*, *library*).
3. **Check the eight questions.** The preset fills them in; change any that don't fit. The panel on the right shows how each answer moves the weights, and which benchmarks become **gates** (non-negotiable).
4. **Mark hot and cold zones.** Add a hot zone for anything that moves money, controls access or writes important data, and a cold zone for scripts and examples. Use **Test a path** to check your patterns.
5. **Download `project.toml`** and add it to your grading repo as `projects/orders-api/project.toml`. The page also gives you starter `decisions.json` and `dispositions.json` files, and a README for a brand-new grading repo. On GitHub: **Add file → Upload files**. *Needs write access to the grading repo.*

### 2. Grade (2 minutes of your time)

Open **[Start a run](../app/run.html)** and choose **Grade the code**.

- **Where are things?** Pick cloud or local, give the code repo, the grading repo and the project name.
- **How should it hand back results?** **Open a pull request** is the default: the grader adds only the new report folder, on a branch like `report/orders-api/2026-11-07-a1b2c3d`. It can also **save the files locally** or **give them back in the chat**.

Copy the prompt and paste it into a **fresh** agent session. A full grading often takes 30–90 minutes for a medium codebase, because the agent reads the code and runs its tests and tools. *Needs read access to the code and, for a pull request, permission to push branches to the grading repo.*

### 3. Review and decide (about 10 minutes)

Open **[Review a report](../app/review.html)**. The grader's PR description links straight to it.

- **From the grading repo:** enter the repo and project name, or paste the report PR's URL. The page loads the settings, decisions and all reports, reviews the newest, and compares it with the one before. You can pick any other report from the bar at the top.
- **From files:** choose the project folder, drop a zip of the grading repo, or drop individual files. Add a zip of the *code* (GitHub: **Code → Download ZIP**) if you want every quoted line of code checked.

Then read the tabs in order:

1. **Overview:** the overall score, maturity level, gates, and what blocks the next level. The checks list tells you whether to trust the report.
2. **Decisions:** questions only a person should answer, such as "drop this deprecated endpoint?" Choose Approve, Decline or Not yet. The page produces an updated `decisions.json`.
3. **Priorities:** the order improvers will work in.
4. **Compare:** what got better or worse since the previous report.
5. **Scorecard, Findings, More:** the detail, when you want it. Open a benchmark to see why it got its score, what each score band means in the rubric, and its history. Open a finding to see its code, with a link to those lines at the graded commit.

**Share a view:** the page's address always points at what you're looking at. **Copy link** on a benchmark or finding gives a link straight to it, and **Print or save as PDF** gives the whole report on paper.

**Save your answers.** The page shows the steps; the short version:
- **Suggested:** on the report's PR, edit `projects/orders-api/decisions.json`, paste the updated file, commit to the PR's branch, then **merge the PR**. Merging means "accepted."
- **Already merged?** Edit the file on the default branch and let GitHub create a small pull request on a branch named `decisions/orders-api/<date>`.

### Several projects

**[Projects](../app/projects.html)** reads the grading repo's `projects/index.json` (CI keeps it current) and shows every project at once:
- **All projects:** each one's score, level, trend, and what it's waiting on.
- **Decisions:** every question waiting for a person, across projects, answered in one sitting. Each project's answers become its `decisions.json`, saved the same way as above.
- **One project:** where it stands in the cycle, with its open pull requests; trends for the overall score and each pillar; and every benchmark's score in every report.

*Needs write access to the grading repo.*

### 4. Improve

On **[Start a run](../app/run.html)**, choose **Improve the code**, then choose how it gets the report:
- **It reads it from the grading repo:** it opens only the project's latest report, `decisions.json` and `project.toml`.
- **You hand it the files.**

Set a budget (start small: tiers 0–1) and paste the prompt into a new agent session. It works down the priorities, skips anything you haven't approved, and opens a pull request on your code with a log of what it did. *Needs push access to the code repo.*

### 5. Check every change

Choose **Check a pull request** on Start a run and give it the code PR. It compares against the latest merged report and answers **PASS** or **FAIL**, with the reasons. Once you trust the loop, you can run this automatically in CI. *Needs read access to both repos, and permission to comment on the code PR.*

Then repeat: grade again after a batch of improvements, and the new report is compared with this one.

## Common setups

**Team on GitHub (the default).** One grading repo for all projects. Graders open report PRs, you answer decisions on them and merge, improvers open PRs on the code, and PR checks guard each change.

**Solo, local agent.** The same layout in a local folder. Graders **save files** into `projects/<name>/reports/`. Open the project folder in the Review page, save `decisions.json` next to `project.toml`, and hand the improver the files.

**Someone else's public repo.** No grading repo needed. Graders **give the files back in the chat**; save them into a folder and open it in the Review page. Without a `project.toml`, reports are checked against the suite defaults, which is fine for a one-off look.

**Milestone audit.** On Start a run, choose *three independent graders* and run the three prompts in three fresh sessions. They write `runs/run-1.json` and so on into the same report folder. The Review page shows where they disagreed, and lets you download the consensus as that folder's `report.json`.

**Monorepo.** One project per part, e.g. `shop-web` with `path = "apps/web"` and `shop-api` with `path = "services/api"`. Each gets its own reports and decisions.

## Keeping agents honest

- **Every grading is a fresh session,** never the agent that did the improving.
- **Decisions are yours.** Agents may recommend answers, but only approve them if you turn that on in `project.toml`.
- **Improvers read only what you point them to,** and never change grading files.
- **Every quote is checkable.** Drop the code's zip on the Review page to verify that each piece of evidence really exists.
- **Hidden checks** (optional, for later): private tests in `projects/<name>/hidden-checks/` that graders run and you don't show improvers. If visible scores rise while hidden checks fall, the code is being tuned to the rubric. See [Hidden checks](holdout/README.html).

## When something looks off

| You see | What to do |
|---|---|
| "This report has errors" | Usually a grader slip, such as wrong arithmetic or a missing field. Re-run the grader rather than patching the report. |
| "Graded with a different config" | `project.toml` changed since the grading. Scores still stand; overall and maturity are recomputed with your current settings. |
| A citation fails | The quoted code isn't where the grader said. Treat that finding with suspicion, and re-grade if there are several. |
| "Couldn't load from GitHub" | Check that the grading repo is public and the project name matches its folder. Otherwise, download a zip of the repo and drop it in. |
| The grader can't push or open a PR | Choose *save files* or *give them back in the chat* on Start a run. |
| "The in-browser engine couldn't start" | The pages load a Python runtime from a CDN the first time. Check your connection, or self-host it (see [Hosting](DEPLOY.html)). |
| Scores dropped right after you changed settings | Weights changed, not the code. Compare reports graded with the same config. |

## Prefer the command line?

Everything the pages do is also available through `tools/gradekit.py` in the downloadable kit (Python 3.11+, no other installs). From the root of your grading repo:

```bash
K="python3 SUITE_DIR/tools/gradekit.py"
$K init --project orders-api --code-repo https://github.com/acme/orders-api --preset service
$K resolve --project orders-api              # weights, gates and zones it produces
$K rollup  --project orders-api              # the latest report: gates, maturity, priorities
$K diff    --project orders-api              # the latest report vs the one before
```

See the [overview](README.html) for every command, and the [tuning guide](TUNING.html) for customizing scoring.
