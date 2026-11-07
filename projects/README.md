# Projects

Each graded codebase gets its own folder here:

```
projects/<project>/
├── project.toml          settings: preset, answers, zones, targets   (people)
├── decisions.json        answers to decision questions               (people)
├── dispositions.json     findings accepted as they are               (people)
└── reports/
    └── <date>-<commit>/  one folder per report                        (graders, by pull request)
```

## Add a project

**From the website:** open [Set up a project](https://gordoncooper.github.io/code-grader/app/setup.html) and download the three files. Then, on GitHub, go to **Add file → Upload files** into `projects/<project>/`. *This needs write access to this repo.*

**From the command line,** at the root of this repo:

```bash
python3 bundle/bare/tools/gradekit.py init --preset service --project orders-api \
    --code-repo https://github.com/OWNER/orders-api
python3 bundle/bare/tools/gradekit.py resolve --project orders-api   # check the weights and gates
```

Run `python3 bundle/bare/tools/gradekit.py presets` to see the presets side by side.

## Naming

- Use the code repo's name, in lowercase with hyphens: `orders-api`, `web-checkout`.
- For a monorepo, make one project per part (for example `shop-api` and `shop-web`), and set `path` in each `project.toml` to that part's subfolder.
- Don't rename a project folder once it has reports. Report history and comparisons rely on the folder name.

## Rules

- Never edit or delete a report folder. A new grading run always adds a new one.
- `decisions.json` and `dispositions.json` only grow: add entries, don't rewrite old ones. The newest answer wins.
- Change `project.toml` between grading runs, not during one.
