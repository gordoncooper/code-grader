# Candidate golden repos

Repos graded once by a reference grader. Their expected scores are proposals that no person has reviewed yet, so `gradekit calibration run` doesn't count them. A candidate becomes a golden repo when a person has reviewed its scores and it has three independent runs.

| Candidate | Kind | Language | Commit |
|---|---|---|---|
| `realworld-go` | service | Go | gothinkster/golang-gin-realworld-example-app @ de2be2a |
| `realworld-angular` | web app | TypeScript | gothinkster/angular-realworld-example-app @ a7a19c5 |
| `hexyl` | command-line tool | Rust | sharkdp/hexyl @ 6ecc29b |
| `nanogpt` | data and ML | Python | karpathy/nanoGPT @ 93a43d9, its last code change before the README marked it deprecated |

Each folder holds:
- `project.toml`: the project's answers and zones, which a reviewer checks too;
- `expected.json`: the scores proposed from the reference grade, with `set_by` saying so;
- `runs/run-1.json`: the reference grade itself.

`gradekit calibration analyze` reads candidates by default. Each one adds a repo to the comparison across repos: which benchmarks move together, and which rarely apply. One run says nothing about how far graders spread.

The reference grades were made before the 6.0 wording pass that their own graders asked for (see `CHANGELOG.md`). Where that pass changed a rule a reference applied, its proposed score may need adjusting in review.

## Promoting a candidate
1. Review `project.toml` and `expected.json`. Change what you disagree with, and say in `set_by` who reviewed it and when.
2. Move the folder to `calibration/golden/`. Delete `runs/run-1.json`: it set the scores it would be compared with.
3. Add three independent runs with `gradekit calibration add-run`, each from a fresh grader with no access to the other runs, then run `gradekit calibration run`.

## Running a grade in a sandbox
These notes are from the 6.0 runs, in a sandbox with registry and GitHub access only:
- **Go modules:** Go's module proxy was blocked, so the Go service was built with a copy of its `go.mod`, kept outside the repo, whose `replace` lines point each module at its GitHub mirror at the same version (`GOFLAGS=-modfile=… GOPROXY=direct GOSUMDB=off`).
- **Running as root:** one of the Go service's tests chmods a file to 0000 and expects the open to fail, which never happens for root. Graders were told they ran as root, and not to count failures caused by the sandbox.
- **Credentials:** the shell held tokens, so commands that ran the repos' code went through a wrapper that unset them (`gradekit doctor` lists the ones it sees).
