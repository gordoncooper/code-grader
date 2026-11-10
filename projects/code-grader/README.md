# The suite grading itself

This project is the Code Grading Suite graded with its own kit. It lives only on the `grading/code-grader` branch, never on `main`:

- `project.toml` and the answers in `decisions.json` and `dispositions.json` are on this branch.
- **Reports** come in as pull requests from `report/code-grader/…` branches into `grading/code-grader`, so merging one records it here, not on `main`.
- **The grading check** (`.github/workflows/grading.yml`, on this branch only) runs on those pull requests. It checks the report, comments, labels it, and records the decision boxes you tick in its description. It uses the 5.x kit from the suite website's `/v5/` address and GitHub's built-in token. It never reads the graded code.
- The workflow's `index` and `schedule` jobs only run on the default branch, so they never run here.
