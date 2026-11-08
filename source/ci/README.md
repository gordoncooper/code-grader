# CI for grading repos

These run `gradekit ci` on every pull request (merge request) to a grading repo. The check:
- makes sure each pull request is **one kind of change**: either a single new report folder, or a project's settings (`project.toml`, `decisions.json`, `dispositions.json`, `org.toml`);
- validates the report: format, rules, citations' shape, a rollup that matches its scores, the folder name, and no private reports or withheld details in a public repo;
- keeps `decisions.json` and `dispositions.json` **append-only**;
- comments a summary (score, maturity, gates, decisions waiting, a link to the Review page) and labels the pull request `grading: report`, `grading: settings` or `grading: needs changes`.

| File | Host | Install |
|---|---|---|
| `github-grading.yml` | GitHub Actions | `gradekit init --ci github --site URL`, or copy to `.github/workflows/grading.yml` |
| `gitlab-grading.yml` | GitLab CI | `gradekit init --ci gitlab --site URL`, or add to `.gitlab-ci.yml` |
| `fetch-kit.py` | any | downloads the kit from your suite website and checks its checksum (both templates use it) |

**Permissions:**
- **GitHub:** the workflow's own token, with `contents: read`, `pull-requests: write` and `issues: write` (for labels). Pull requests from forks are checked but not commented on.
- **GitLab:** comments and labels need a `GRADING_BOT_TOKEN` variable, which is a project access token with `api` scope. Without it, the result is in the job log.

**Another host:** run the same two steps in any CI that gives you a checkout with history:

```
KIT=$(python3 fetch-kit.py "$SUITE_SITE" /tmp/kit)
python3 "$KIT/tools/gradekit.py" ci --base origin/main --comment-file comment.md --labels-file labels.txt
```

Then post `comment.md` however your host allows. The exit code is 1 when the pull request needs changes. Add `--json` for everything as data.
