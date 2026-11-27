# Calibration scratch (work in progress, not for merging)

Saved so the 6.0 calibration work survives a restart. To pick it up:

1. Clone the candidate repos into `/tmp/calib/src/` and check out the pinned commits in `setup_run.sh`. For the Angular app, run `git submodule update --init`.
2. Copy the 6.0 kit: `git archive origin/main source | tar -x -C /tmp/calib/kit6`, then delete `source/calibration` and `source/CHANGELOG.md` from the copy.
3. Copy `source/calibration/candidates/<name>/project.toml` to `/tmp/calib/goldens/<name>/`. Copy `go/` to `/tmp/calib/go/`, and `nocreds` to `/tmp/calib/`.
4. Set up a run with `./setup_run.sh GOLDEN TAG`. Write its prompt with `python3 prompt.py GOLDEN TAG > /tmp/calib/GOLDEN-TAG/PROMPT.md`, and copy `nocreds` into the run folder.

- `go/` is the Go service's `go.mod` with `replace` lines to GitHub mirrors, because Go's module proxy is blocked in the sandbox. Use it with `GOFLAGS=-modfile=… GOPROXY=direct GOSUMDB=off` the first time, and with `GOPROXY=off` once the cache is warm.
- `nocreds` drops the sandbox's tokens from the environment of commands that run repo code.
