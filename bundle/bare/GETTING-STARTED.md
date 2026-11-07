# Getting started

This guide takes you through a first full cycle: set up a project, have an agent grade it, review the report, and let an agent improve the code. It takes about 20 minutes of your time, plus however long your agents take. **Nothing to install.** You use three pages on this website and whatever coding agent you already have, cloud or local.

## The idea in one minute

Four jobs, each done by a separate agent session (or by you):

| Job | Who | What happens |
|---|---|---|
| **Grade** | An agent | Reads the code, runs its tests and tools, and scores 35 benchmarks from 1 to 10 with evidence. Produces `report.json` and `report.md`. |
| **Review** | You (or an agent helping you) | Checks the report, and answers the few questions that need a person's call. |
| **Improve** | An agent | Works down the report's ranked to-do list and opens a pull request. |
| **Check** | An agent | On each pull request, re-grades only what changed, and fails anything that made the code worse. |

A fresh grader session each time keeps the grading honest: an agent never grades its own work.

## Where things live

| What | Where | Who changes it |
|---|---|---|
| **The suite** (rubric, prompts, tools) | This website | Nobody during a cycle |
| **`project.toml`**: your settings, plus accepted findings and answers to decision questions | `.grading/` in your repo | **People only** |
| **`report.json` / `report.md`**: the latest report | `.grading/` in your repo | Graders (older reports stay in git history) |
| **Hidden checks** (optional): private tests graders run and improvers never see | Anywhere *outside* the repo | You |

That's the default, and the simplest. If you'd rather improvers couldn't even read the grading folder, keep it in a separate private repo or folder instead. Everything works the same; you just point agents at that location.

## Your first cycle

### 1. Set up the project (about 5 minutes, once)

Open **[Set up a project](../app/setup.html)**.

1. **Pick a preset** that's closest to your project (e.g. *service*, *web app*, *library*).
2. **Check the eight questions.** The preset fills them in; change any that don't fit. The panel on the right shows how each answer moves the weights, and which benchmarks become **gates** (non-negotiable).
3. **Mark critical code.** Add a hot zone for anything that moves money, controls access or writes important data, and a cold zone for scripts and examples. Use **Test a path** to check your patterns.
4. **Download `project.toml`** and save it as `.grading/project.toml` in your repo. On GitHub: **Add file → Upload files**. Download the folder's README from the same page and add that too.
5. *Recommended:* add `/.grading/ @your-team` to `.github/CODEOWNERS`, so changes to the folder need your team's approval.

### 2. Grade (2 minutes of your time)

Open **[Start a run](../app/run.html)** and choose **Grade the code**.

- **Where are things?** Pick cloud or local, give the repo URL or folder, and leave the grading folder as `.grading/`.
- **How should it hand back results?** For a GitHub repo, **Open a pull request** is easiest: the report arrives as a PR that you review and merge. Local agents can just **save the files**. For someone else's public repo, choose **Give them back in the chat**.

Copy the prompt and paste it into a **fresh** agent session. A full grading takes a while (often 30–90 minutes for a medium codebase), because the agent reads the code and runs its tests and tools.

### 3. Review and decide (about 10 minutes)

Open **[Review a report](../app/review.html)**.

- **Public GitHub repo:** enter the repo, or paste the grader's PR URL, and click **Load from GitHub**. The page fetches the report, your `project.toml` and the previous report.
- **Anything else:** drop in `report.json` and `project.toml`. Add the repo's `.zip` (GitHub: **Code → Download ZIP**) if you want every quoted line of code checked.

Then read the tabs in order:

1. **Overview:** the overall score, maturity level, gates, and what blocks the next level. The checks list tells you whether to trust the report.
2. **Decisions:** questions only a person should answer, such as "drop this deprecated endpoint?" Choose Approve, Decline or Not yet. The page produces a few lines to add to `project.toml`.
3. **Priorities:** the order improvers will work in.
4. **Scorecard, Findings, Compare:** the detail, when you want it.

**Save your answers** by adding the lines to the end of `.grading/project.toml` **on the grader's pull request branch**. On GitHub: click the PR's branch name near the top of the PR, open `.grading/project.toml`, click the pencil (**Edit**), paste at the end, and **commit directly to that branch**. Then **merge the PR**. That closes the cycle: the report and your decisions are now on your main branch.

### 4. Improve

Back on **[Start a run](../app/run.html)**, choose **Improve the code**, set a budget (start small: tiers 0–1), and paste the prompt into a new agent session. It reads `.grading/` itself, works down the priorities, skips anything you haven't approved, and opens a pull request with a log of what it did. Review it like any other pull request.

### 5. Check every change

Choose **Check a pull request** on Start a run and paste the prompt into an agent with the PR's URL. It answers **PASS** or **FAIL**, with the reasons. It also fails any improvement PR that touches `.grading/`. Once you trust the loop, you can run this automatically in CI.

Then repeat: grade again after a batch of improvements, and use **Compare** to see what changed.

## Common setups

**Solo developer, local agent.** Keep `.grading/` in the repo. Grader delivery: *save files* (or *commit*). Review by dropping the files into the Review page. Paste decisions into `project.toml` and commit.

**Team on GitHub, cloud agents.** Keep `.grading/` in the repo, protected with CODEOWNERS. Grader delivery: *open a pull request*. Reviewers load the PR on the Review page, paste decisions on the PR and merge. Run pull-request checks on every improver PR.

**Grading a public repo you don't own.** Grader delivery: *give them back in the chat*. Save `report.json` from the chat and drop it into the Review page. There's no `project.toml` unless you write one: the report is checked against the suite defaults, which is fine for a one-off look.

**Strict separation.** Keep the grading folder in a private repo that improver sessions can't access, and give graders the hidden checks. On Start a run, choose *grading folder: somewhere else* and give its location.

**Milestone audit.** On Start a run, choose *three independent graders*. Run the three prompts in three fresh sessions. Drop all three run files into the Review page: it shows where the graders disagreed, and lets you download the consensus as `report.json`.

## Keeping agents honest

- **Improvers never change `.grading/`.** The pull-request check fails any PR that does, and CODEOWNERS makes it need your approval anyway.
- **Every grading is a fresh session,** never the agent that did the improving.
- **Decisions are yours.** Agents may recommend answers, but only approve them if you turn that on in `project.toml`.
- **Hidden checks stay private.** Graders report only the pass rate. If visible scores rise while hidden checks fall, the Compare tab warns you that the code may be being tuned to the rubric.
- **Every quote is checkable.** Drop the repo's zip on the Review page to verify that each piece of evidence really exists.

## When something looks off

| You see | What to do |
|---|---|
| "This report has errors" | Usually a grader slip, such as wrong arithmetic or a missing field. Re-run the grader rather than patching the report. |
| "Graded with a different config" | `project.toml` changed since the grading. Scores still stand; overall and maturity are recomputed with your current settings. |
| A citation fails | The quoted code isn't where the grader said. Treat that finding with suspicion, and re-grade if there are several. |
| The grader can't push or open a PR | Choose *save files* or *give them back in the chat* on Start a run. |
| "The in-browser engine couldn't start" | The pages load a Python runtime from a CDN the first time. Check your connection, or self-host it (see [Hosting](DEPLOY.html)). |
| Scores dropped right after you changed settings | Weights changed, not the code. Compare reports graded with the same config. |

## Prefer the command line?

Everything the pages do is also available through `tools/gradekit.py` in the downloadable kit (Python 3.11+, no other installs). Inside a repo with a `.grading/` folder:

```bash
python3 SUITE_DIR/tools/gradekit.py init --preset service --grading-dir .grading   # set up
python3 SUITE_DIR/tools/gradekit.py resolve                                       # see weights, gates, zones
python3 SUITE_DIR/tools/gradekit.py validate && python3 SUITE_DIR/tools/gradekit.py rollup
```

See the [overview](README.html) for every command, and the [tuning guide](TUNING.html) for customizing scoring.
