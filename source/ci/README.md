# CI for grading repos

These run `gradekit ci` on every pull request (merge request) to a grading repo. The check:
- makes sure each pull request is **one kind of change**: either a single new report folder, a project's settings (`project.toml`, `decisions.json`, `dispositions.json`, `org.toml`), or a **migration** (`gradekit migrate`) of one project to a newer suite version;
- checks a migration by redoing it from the base branch's files: each changed report must be exactly what `gradekit migrate` makes, so a hand edit to an old report can't slip in with one;
- validates the report: format, rules, citations' shape, a rollup that matches its scores, the folder name, and no private reports or withheld details in a public repo;
- keeps `decisions.json` and `dispositions.json` **append-only**;
- comments a summary (score, maturity, gates, decisions waiting, a link to the Review page) and labels the pull request `grading: report`, `grading: settings`, `grading: migration` or `grading: needs changes`.

When reports or decisions land on the default branch, a second job rebuilds `projects/index.json` with `gradekit index` and commits it. That file holds every project's latest score, maturity, history and the decisions still waiting, and dashboards and the Review page read it. A pull request may include the index, but only if it matches what `gradekit index` makes. To check it yourself, run `gradekit index --check`.

| File | Host | Install |
|---|---|---|
| `github-grading.yml` | GitHub Actions | `gradekit init --ci github --site URL`, or copy to `.github/workflows/grading.yml` |
| `gitlab-grading.yml` | GitLab CI | `gradekit init --ci gitlab --site URL`, or add to `.gitlab-ci.yml` |
| `fetch-kit.py` | any | downloads the kit from your suite website and checks its checksum (both templates use it) |

**Permissions:**
- **GitHub:** the workflow's own token, with `contents: read`, `pull-requests: write` and `issues: write` (for labels). Pull requests from forks are checked but not commented on.
- **GitHub, index job:** `contents: write`. If the default branch doesn't allow direct pushes, let GitHub Actions bypass that rule, or delete the job.
- **GitLab:** comments, labels and the index need a `GRADING_BOT_TOKEN` variable. It's a project access token with the `api` and `write_repository` scopes, and a role that may push to the default branch. Without it, the result is in the job log and the index isn't rebuilt.

**Another host:** run the same two steps in any CI that gives you a checkout with history:

```
KIT=$(python3 fetch-kit.py "$SUITE_SITE" /tmp/kit)
python3 "$KIT/tools/gradekit.py" ci --base origin/main --comment-file comment.md --labels-file labels.txt
```

Then post `comment.md` however your host allows. The exit code is 1 when the pull request needs changes. Add `--json` for everything as data.
