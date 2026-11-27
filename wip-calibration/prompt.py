"""Print the grader prompt for one calibration run: python3 prompt.py GOLDEN TAG"""
import subprocess
import sys

G, T = sys.argv[1], sys.argv[2]
R = f"/tmp/calib/{G}-{T}"
INFO = {
    "realworld-go": ("golang-gin-realworld-example-app", "https://github.com/gothinkster/golang-gin-realworld-example-app",
        f"- Go's module proxy is blocked here. Build and test with `export GOFLAGS=-modfile={R}/gomod/go.mod GOPROXY=off GOSUMDB=off`. "
        "That file is a copy of the repo's `go.mod` with `replace` lines that point each module that isn't on GitHub at its GitHub mirror, "
        "at the same version, and every module is already in the module cache. It's outside the repo and isn't part of what you grade."),
    "realworld-angular": ("angular-realworld-example-app", "https://github.com/gothinkster/angular-realworld-example-app",
        "- Bun is installed at `/root/.bun/bin/bun` but isn't on PATH. Its package cache is warm, so installs are quick. "
        "The `realworld` git submodule is checked out."),
    "hexyl": ("hexyl", "https://github.com/sharkdp/hexyl",
        "- Cargo's registry cache is warm, so builds don't need to download crates."),
    "nanogpt": ("nanoGPT", "https://github.com/karpathy/nanoGPT",
        "- PyTorch from PyPI (about 3 GB) is in uv's cache. Install it into a virtual environment with `uv pip install`, which is quick "
        "and uses little disk; plain pip would download it again, and the disk can't hold many copies. Training can only run on the CPU here."),
}
code, repo, extra = INFO[G]
sha = subprocess.run(["git", "-C", f"{R}/{code}", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
reference = ("\n**Your grade is this repo's reference.** A person will review it to set the repo's expected scores, "
             "so make sure each score's evidence and reasoning would convince them.\n") if T == "ref" else ""
print(f"""You're grading a codebase with the Code Grading Suite, a kit for grading code against a rubric. This is a calibration run: your grade will be compared with other graders' to find where the rubric's wording is loose. So grade exactly as the kit says, and work on your own.

**Your inputs** (the items in Part 0 of the grader prompt):
- SUITE_DIR: `{R}/kit`
- Code: `{R}/{code}`, a local checkout of {repo}
- COMMIT: `{sha}` (checked out)
- Grading repo: `{R}/grading` (local)
- Project: `{G}`, so PROJECT_DIR is `{R}/grading/projects/{G}`
- Delivery: `save`
- Runs: 1 of 1
- Scratch folder: `{R}/scratch`

**What to do:** read `SUITE_DIR/prompts/grader.md` and do a full grade as it says (not a PR review), writing the report with the `gradekit report` commands. You're done when `report check --write` passes and `report.md` is rendered. Put the minutes you spent in `run.usage.minutes`.
{reference}
**Stay independent.** Work only in `{R}` (and package caches). Don't read anything else under `/tmp/calib`, and don't look online for reviews, grades or audits of this repo. Don't change the kit, and don't commit to the code.

**The sandbox:**
- You run as root, on 2 CPUs with no GPU. The network reaches package registries (PyPI, npm, crates.io) and GitHub; other hosts are blocked. Other graders may be running at the same time, so builds and tests can be slow.
- When something fails because of the sandbox rather than the code (running as root, a blocked host, no GPU), don't count it against the code. Note it under limitations, and treat what it stopped you from checking as unverified.
- The shell's environment holds credentials (GitHub, AWS and Google Cloud tokens). Run the repo's own code (installs, builds, tests, examples) through `{R}/nocreds`, which drops them and keeps what the network needs, e.g. `{R}/nocreds make test`.
{extra}

**Known kit problems:** earlier graders already reported these, so you don't need to again.
- `doctor` fails `pr` delivery because the grading repo has no remote. Run it with `--delivery save`.
- `--cite` keeps only the first 3 lines of a longer range, so cite the 3 or fewer lines that show the point.
- Excerpts must match the output exactly, including color codes. Turn color off (`NO_COLOR=1`, `--no-color`), or pass the excerpt from a file with `@file`. You also need `@file` to quote two lines that aren't next to each other.
- Evidence is matched to a command by its text, so `--command @N` can check the wrong run when two commands have the same text. Make repeated commands' texts differ.
- A single `--note` applies to every evidence item in that call. Give one `--note` per item.
- `report show REPORT limitations` fails. `report set R limitations.N` counts from 1.
- Record commands without the `nocreds` prefix, and mention it in `--env`.
- `GLOSSARY.md` says there are 35 benchmarks, but there are 31. The comment in `defaults.toml` names A4 "Idempotence & Determinism", but the rubric's name is the right one.

**When you're done,** reply in under 300 words with:
1. the report path;
2. the overall score and level;
3. the minutes you spent;
4. every place the kit's instructions were unclear or contradictory, or made you guess: the file and section, and what you did. This is the most useful part;
5. what the sandbox stopped you from checking.""")
