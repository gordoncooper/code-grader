# CI for grading repos

These run `gradekit ci` on every pull request (merge request) to a grading repo. The check:
- makes sure each pull request is **one kind of change**: either a single new report folder, a project's settings (`project.toml`, `decisions.json`, `dispositions.json`, `org.toml`), or a **migration** (`gradekit migrate`) of one project to a newer suite version;
- checks a migration by redoing it from the base branch's files: each changed report must be exactly what `gradekit migrate` makes, so a hand edit to an old report can't slip in with one;
- validates the report: format, rules, citations' shape, a rollup that matches its scores, the folder name, and no private reports or withheld details in a public repo;
- keeps `decisions.json` and `dispositions.json` **append-only**;
- comments a summary (score, maturity, gates, decisions waiting, a link to the Review page) and labels the pull request `grading: report`, `grading: settings`, `grading: migration` or `grading: needs changes`.

**Grading on a schedule.** Projects with `[schedule] grade_every_days` set are checked weekly by a scheduled job: `gradekit due --check-code --write-orders` writes a grade work order for each one that's due (enough days since its last full grade and, by default, new commits on the code's default branch), and the job sends each as its own pull request. Your graders pick open orders up with `gradekit order list`.

When reports or decisions land on the default branch, a second job rebuilds `projects/index.json` with `gradekit index` and commits it. That file holds every project's latest score, maturity, history and the decisions still waiting, and dashboards and the Review page read it. A pull request may include the index, but only if it matches what `gradekit index` makes. To check it yourself, run `gradekit index --check`.

**Answering decisions by ticking boxes.** A report's pull request lists its decision questions as a checklist: a box to approve each, and a *Decline* box under it. A third job records what's ticked in that project's `decisions.json` on the pull request's branch, under the login of the person who answered, using `gradekit decide --from-checklist`. Answers already recorded aren't written again, unticked boxes are no answer, and a question with both boxes ticked is skipped. On GitHub it runs whenever the description is edited. GitLab has no event for that, so there it's a manual job: tick, then press play on `grading-decide` in the merge request's pipeline. On any host, or without CI, a person or agent can run `gradekit decide --project NAME --approve ID --by NAME` (or `--decline`), and `gradekit decisions --project NAME --approved` lists exactly what may be acted on.

| File | Host | Install |
|---|---|---|
| `github-grading.yml` | GitHub Actions | `gradekit init --ci github --site URL`, or copy to `.github/workflows/grading.yml` |
| `gitlab-grading.yml` | GitLab CI | `gradekit init --ci gitlab --site URL`, or add to `.gitlab-ci.yml` |
| `fetch-kit.py` | any | downloads the kit from your suite website and checks its checksum (both templates use it) |

**Permissions:**
- **GitHub:** the workflow's own token, with `contents: read`, `pull-requests: write` and `issues: write` (for labels). Pull requests from forks are checked but not commented on.
- **GitHub, decide job:** `contents: write`, to commit `decisions.json` to the report's branch. Anyone who can edit the description can answer: people with write access, and the pull request's author. Pull requests from forks are skipped. A commit made with the workflow's token doesn't start another run, so the check doesn't re-run on it; `gradekit decide` checks each answer against the report itself.
- **GitHub, schedule job:** `contents: write` and `pull-requests: write`, and **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests**. It runs every Monday and on demand (Actions → Grading check → Run workflow), and opens one pull request per project that's due, adding a grade work order. Pull requests opened with the workflow's token don't start workflows, so the check doesn't run on them; if a branch rule requires it, merge them as an admin or use a token of your own. To tell whether **private** code has changed, add a `CODE_READ_TOKEN` secret that can read the code repos (a fine-grained token with *Contents: read*). Without it, a project whose code can't be read isn't due until `only_if_code_changed = false`. GitHub pauses scheduled workflows in public repositories after 60 days without activity.
- **GitHub, index job:** `contents: write`. If the default branch doesn't allow direct pushes, let GitHub Actions bypass that rule, or delete the job.
- **GitLab:** comments, labels and the index need a `GRADING_BOT_TOKEN` variable. It's a project access token with the `api` and `write_repository` scopes, and a role that may push to the default branch. Without it, the result is in the job log, the index isn't rebuilt and `grading-decide` doesn't appear. Anyone who may run the merge request's jobs (Developer or above) can record decisions; the token needs to be allowed to push to the merge request's branch. Merge requests from forks are skipped.
- **GitLab, schedule:** add a pipeline schedule (**Build → Pipeline schedules**, e.g. weekly). The `grading-schedule` job opens one merge request per project that's due, with `GRADING_BOT_TOKEN`. To read private code repos, add a `CODE_READ_TOKEN` variable with `read_repository`.

**Another host:** run the same two steps in any CI that gives you a checkout with history:

```
KIT=$(python3 fetch-kit.py "$SUITE_SITE" /tmp/kit)
python3 "$KIT/tools/gradekit.py" ci --base origin/main --comment-file comment.md --labels-file labels.txt
```

Then post `comment.md` however your host allows. The exit code is 1 when the pull request needs changes. Add `--json` for everything as data.
