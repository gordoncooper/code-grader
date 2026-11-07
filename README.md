# Code Grading

This is the central grading repo. Coding agents grade a codebase on 35 benchmarks, each scored 1–10, and every report lands here. Improver agents then use those reports as targets, and people stay in charge of the settings and decisions.

This repo also holds the **Code Grading Suite** itself (the prompts, rubric, config and the `gradekit` tool) and its website, so one clone gives an agent everything it needs.

> **This repo is public.** Anyone can read the reports here, including security findings and quoted code. Only grade code here that you're happy to show, or scrub reports first with `gradekit redact`.

## Website

**https://gordoncooper.github.io/code-grader/**

It has three browser tools and needs no installs:

| Page | What it's for |
|---|---|
| [Set up a project](https://gordoncooper.github.io/code-grader/app/setup.html) | Pick a preset, answer 8 questions, mark hot and cold zones, and download `project.toml` |
| [Start a run](https://gordoncooper.github.io/code-grader/app/run.html) | Get a ready-to-paste prompt for a grader, reviewer, improver or pull-request check |
| [Review a report](https://gordoncooper.github.io/code-grader/app/review.html?repo=gordoncooper/code-grader) | Load a project from this repo (or from files), check the report, compare it with the last one, and answer decisions |

The site always serves the newest bundle in [`bundle/web/`](bundle/). It's published by [`.github/workflows/pages.yml`](.github/workflows/pages.yml) whenever that folder changes on `main`.

## Layout

```
code-grader/
├── README.md                     this file
├── LICENSE                       MIT
├── org.toml                      optional house rules for every project (people)
├── projects/
│   └── <project>/                one folder per graded codebase
│       ├── project.toml          settings: preset, answers, zones, targets        (people)
│       ├── decisions.json        answers to decision questions                    (people)
│       ├── dispositions.json     findings accepted as they are                    (people)
│       └── reports/
│           └── <date>-<commit>/  one folder per report, never overwritten          (graders, by pull request)
│               ├── report.json
│               └── report.md
└── bundle/
    ├── bare/                     the kit: prompts, rubric, config, schema, gradekit, docs
    └── web/                      the built website (served by GitHub Pages)
```

- **Project names** default to the code repo's name, in lowercase with hyphens (for example `orders-api`). For a monorepo, make one project per part, each with a `path` in its `project.toml`. See [`projects/`](projects/).
- **Report folders** are named `YYYY-MM-DD-<short commit>` after the commit that was graded. A new grading run always adds a new folder.
- **`org.toml`** is optional. Anything set there applies to every project, and a project's own `project.toml` overrides it.

## The cycle

| Step | Who | What lands where | Permissions needed |
|---|---|---|---|
| 0. Set up (once per project) | You | `projects/<name>/project.toml` plus starter `decisions.json` and `dispositions.json` | write to this repo |
| 1. Grade | A fresh agent session | A pull request on `report/<project>/<date>-<short-commit>` that adds one report folder. It can also save locally or return the files in chat. | read the code; push branches and open pull requests here |
| 2. Review and decide | You, or an agent if allowed | Decisions in `decisions.json`, on the report's pull request or a follow-up `decisions/<project>/<date>` pull request. Then merge. | write to this repo |
| 3. Improve | Another fresh agent session | A pull request on the **code** repo, working from the newest merged report plus its decisions | read this repo; push branches and open pull requests on the code repo |
| 4. Guard | An agent, or CI | PASS or FAIL as a comment on a code pull request, compared with the newest merged report | read both repos; comment on code pull requests |

Repeat from step 1. **Start a run** builds the prompt for each step with the repo, project and delivery already filled in.

## Ground rules

1. **Nothing goes straight to `main`** except changes people make to settings and docs. Graders and agent reviewers always open pull requests.
2. **People own the settings:** `org.toml`, `project.toml`, `decisions.json` and `dispositions.json`. Agents read them but don't change them. The one exception: an agent reviewer may append decisions if the project sets `[review] allow_agent_decisions = true`.
3. **Graders are independent and sandboxed.** Use a fresh session every time, never the one that did the improving, and run it with no production credentials.
4. **Scores come from `gradekit`**, never from an agent's own arithmetic.
5. **Hidden checks** aren't used yet. When they are, they'll live in `projects/<name>/hidden-checks/`, and improvers won't be pointed at them.

## Using the kit from this repo

Agents that clone this repo can run the tool directly. It needs Python 3.11 or newer and nothing else:

```bash
python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api   # new project folder
python3 bundle/bare/tools/gradekit.py resolve --project orders-api                 # effective weights and gates
python3 bundle/bare/tools/gradekit.py validate projects/orders-api/reports/<date>-<commit>/report.json
```

Agents that only have a URL can start from the site's [`AGENT.md`](https://gordoncooper.github.io/code-grader/AGENT.md).

Start with `bundle/bare/GETTING-STARTED.md` for the walkthrough, then `README.md` and `TUNING.md` in the same folder.

## Versions

Each version of the suite is a tagged [release](https://github.com/gordoncooper/code-grader/releases), with the bare kit and the website attached as zips. `bundle/` always holds the newest version. To see an older one, browse its tag. The full list is in [`bundle/README.md`](bundle/README.md).

## License

[MIT](LICENSE). This covers everything in the repo, including the reports in `projects/`.
