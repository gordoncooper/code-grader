# Bundles

The Code Grading Suite, kept here so graders, reviewers and improvers work from the same copy as the projects they grade.

| Folder | What it is | Who uses it |
|---|---|---|
| `bare/` | The kit: prompts, rubric, config, schema, `gradekit.py`, docs, calibration and examples. The website builder files are left out, because the built site is in `web/`. | Agents and the command line: `python3 bundle/bare/tools/gradekit.py …` |
| `web/` | The built website, exactly as released, including its checksums (`SHA256SUMS`, `manifest.json`) and its own copy of the kit zip in `downloads/` | People, through [GitHub Pages](https://gordoncooper.github.io/code-grader/); agents, through its `AGENT.md` |

## Versions

Both folders always hold the **newest** version. Each version arrived in its own pull request, so that pull request's diff shows what changed. Older versions stay available at their tags.

| Version | Release | Notes |
|---|---|---|
| 3.1.0 | [v3.1.0](https://github.com/gordoncooper/code-grader/releases/tag/v3.1.0) | First web version: a static site with an `AGENT.md` entry point, rendered docs, a download, and checksums. No scoring changes from 3.0.0. |
| 4.0.0 | [v4.0.0](https://github.com/gordoncooper/code-grader/releases/tag/v4.0.0) | Everything tunable moves into config files. Weights come from 8 questions about the project, and the release adds gates, hot/normal/cold zones and ranked priorities. **Scores aren't comparable with 3.x.** |

*(Versions are added one pull request at a time.)*

## Checking a bundle

```bash
cd bundle/web && sha256sum -c SHA256SUMS      # macOS: shasum -a 256 -c SHA256SUMS
```

Each release also attaches the bare and web zips as downloads.
