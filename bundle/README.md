# Bundles

The Code Grading Suite, kept here so graders, reviewers and improvers work from the same copy as the projects they grade.

**Generated, don't edit.** Both folders are built from [`../source/`](../source/) by the *Kit* workflow. `SOURCE-SHA256` records which source they were built from. To change the kit, see [Changing the kit](../README.md#changing-the-kit).

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
| 4.1.0 | [v4.1.0](https://github.com/gordoncooper/code-grader/releases/tag/v4.1.0) | The website becomes three browser tools (Set up, Start a run, Review) that run `gradekit` with no install. Adds a reviewer prompt and flexible delivery. Uses a `.grading/` folder in each code repo, which 4.2.0 replaces with this repo's `projects/` layout. Scores are comparable with 4.0.0. |
| 4.2.0 | [v4.2.0](https://github.com/gordoncooper/code-grader/releases/tag/v4.2.0) | Built for a central grading repo like this one: `projects/<name>/` with separate `decisions.json` and `dispositions.json`, and one dated report folder per report. Graders deliver by PR, the prompts note the permissions each step needs, and Review loads whole projects from GitHub, a folder or a zip. Scores are comparable with 4.x. |
| 4.2.1 | [v4.2.1](https://github.com/gordoncooper/code-grader/releases/tag/v4.2.1) | Review a report no longer lists the suite's bundled example project when you load this whole repo from a zip or folder, and it now shows the project picker for zips with several projects. No scoring changes; config fingerprints are unchanged. |
| 4.2.2 | [v4.2.2](https://github.com/gordoncooper/code-grader/releases/tag/v4.2.2) | **Current.** Fixes from an end-to-end run on a real repo: same-day reports ordered correctly, PR checks no longer fail on pre-existing problems, citation checks handle dot-files, Review reads GitHub at the exact commit, plus phone layout and usability fixes. No scoring changes. |

## Checking a bundle

```bash
cd bundle/web && sha256sum -c SHA256SUMS      # macOS: shasum -a 256 -c SHA256SUMS
```

## Releases

Releases happen on their own. When a release PR merges (one whose `source/CHANGELOG.md` heading isn't marked unreleased, so CI rebuilt `bundle/`), the *Release suite* workflow ([`.github/workflows/release.yml`](../.github/workflows/release.yml)) does three things:

1. Reads the version from `web/manifest.json` and checks it against the top of `bare/CHANGELOG.md`.
2. Tags the merge commit `vX.Y.Z`.
3. Publishes a release with notes from the CHANGELOG and two zips attached: the bare kit and the website.

Versions that are already tagged are skipped, so other edits under `bundle/` don't release anything.

To release a version by hand, go to **Actions → Release suite → Run workflow**. Leave the commit empty to release the newest version on `main`.
