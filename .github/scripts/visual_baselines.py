#!/usr/bin/env python3
"""Screenshot baselines live on their own branch, `visual-baselines`, not in main's history.

Images barely compress from one version to the next, so committing every set of baselines to main grew the repo by
megabytes a week. The `visual-baselines` branch instead holds a single commit, replaced on every save, with one folder
per branch that has its own baselines:

    main/            the baselines main is compared with
    kit--my-change/  a pull request's own, made with the update-visual label (branch name, '/' as '--')

Tests use their branch's folder, or main's when it has none. When a pull request with its own folder merges, `promote`
makes that folder main's. Every save drops the folders of branches that no longer exist.

    visual_baselines.py fetch   --branch B --into tests/visual [--remote URL]
    visual_baselines.py save    --branch B --from tests/visual [--remote URL]
    visual_baselines.py promote --branch B                     [--remote URL]
    visual_baselines.py which   --branch B                     [--remote URL]   (prints the folder fetch would use)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "visual-baselines"
REF = f"refs/remotes/baselines/{BRANCH}"
FILES = ("*.png", "baselines.json")


def git(*args: str, env: dict | None = None, check: bool = True, inp: bytes | None = None) -> str:
    r = subprocess.run(["git", *args], capture_output=True, input=inp, env={**os.environ, **(env or {})})
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args[:3])}…: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode(errors="replace").strip()


def folder(branch: str) -> str:
    return branch.replace("/", "--")


def fetch_branch(remote: str) -> str | None:
    """The baselines commit, fetched into REF, or None if the branch doesn't exist yet."""
    r = subprocess.run(["git", "fetch", "--quiet", "--depth=1", remote, f"+refs/heads/{BRANCH}:{REF}"], capture_output=True)
    if r.returncode != 0:
        return None
    return git("rev-parse", REF)


def folders(commit: str | None) -> list[str]:
    if not commit:
        return []
    return [l.split("\t", 1)[1] for l in git("ls-tree", commit).splitlines() if l.split()[1] == "tree"]


def which(remote: str, branch: str) -> tuple[str | None, str | None]:
    commit = fetch_branch(remote)
    have = folders(commit)
    for f in (folder(branch), "main"):
        if f in have:
            return commit, f
    return commit, None


def cmd_which(a) -> int:
    _, f = which(a.remote, a.branch)
    print(f or "")
    return 0


def cmd_fetch(a) -> int:
    commit, f = which(a.remote, a.branch)
    into = Path(a.into)
    into.mkdir(parents=True, exist_ok=True)
    for pattern in FILES:
        for old in into.glob(pattern):
            old.unlink()
    if not f:
        print(f"no screenshot baselines on {BRANCH} for {a.branch} or main: the tests will make them")
        return 0
    for line in git("ls-tree", f"{commit}:{f}").splitlines():
        mode, kind, sha, name = line.split(None, 3)
        if kind == "blob":
            (into / name).write_bytes(subprocess.run(["git", "cat-file", "blob", sha], capture_output=True, check=True).stdout)
    print(f"screenshot baselines: {BRANCH}/{f}/ ({len(list(into.glob('*.png')))} images) for {a.branch}")
    return 0


def live_branches(remote: str) -> set[str]:
    out = git("ls-remote", "--heads", remote)
    return {folder(l.split("refs/heads/", 1)[1]) for l in out.splitlines() if "refs/heads/" in l}


def write(remote: str, change, message: str) -> int:
    """Replace the branch's single commit with `change(index_env)` applied, retrying if someone else saved first."""
    for attempt in range(5):
        old = fetch_branch(remote)
        live = live_branches(remote)
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            if old:
                git("read-tree", old, env=env)
            for f in folders(old):   # branches that are gone take their baselines with them
                if f != "main" and f not in live:
                    git("rm", "-r", "--cached", "--quiet", f"{f}/", env=env)
            change(env, old)
            tree = git("write-tree", env=env)
        if old and tree == git("rev-parse", f"{old}^{{tree}}"):
            print("screenshot baselines: nothing changed")
            return 0
        commit = git("commit-tree", tree, "-m", message,
                     env={"GIT_AUTHOR_NAME": "github-actions[bot]", "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
                          "GIT_COMMITTER_NAME": "github-actions[bot]", "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"})
        lease = f"--force-with-lease=refs/heads/{BRANCH}:{old or ''}"
        r = subprocess.run(["git", "push", "--quiet", lease, remote, f"{commit}:refs/heads/{BRANCH}"], capture_output=True)
        if r.returncode == 0:
            print(f"screenshot baselines: {message}")
            return 0
        print(f"push rejected (attempt {attempt + 1}): {r.stderr.decode(errors='replace').strip()}", file=sys.stderr)
    sys.exit("couldn't save the screenshot baselines: the branch kept changing")


def cmd_save(a) -> int:
    src = Path(a.src)
    files = sorted(p for pattern in FILES for p in src.glob(pattern))
    if not any(p.suffix == ".png" for p in files):
        sys.exit(f"no baselines in {src}")
    f = folder(a.branch)

    def change(env, old):
        if f in folders(old):
            git("rm", "-r", "--cached", "--quiet", f"{f}/", env=env)
        for p in files:
            sha = git("hash-object", "-w", str(p))
            git("update-index", "--add", "--cacheinfo", f"100644,{sha},{f}/{p.name}", env=env)
    return write(a.remote, change, f"Baselines for {a.branch} ({sum(p.suffix == '.png' for p in files)} images)")


def cmd_promote(a) -> int:
    f = folder(a.branch)
    if f == "main":
        return 0
    old = fetch_branch(a.remote)
    if f not in folders(old):
        print(f"{a.branch} has no baselines of its own: main's stay")
        return 0

    def change(env, old):
        tree = git("rev-parse", f"{old}:{f}")
        if "main" in folders(old):
            git("rm", "-r", "--cached", "--quiet", "main/", env=env)
        git("read-tree", "--prefix=main/", tree, env=env)
        git("rm", "-r", "--cached", "--quiet", f"{f}/", env=env)
    return write(a.remote, change, f"Baselines for main, from {a.branch}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("fetch", cmd_fetch), ("save", cmd_save), ("promote", cmd_promote), ("which", cmd_which)):
        q = sub.add_parser(name)
        q.add_argument("--branch", required=True)
        q.add_argument("--remote", default="origin")
        if name == "fetch":
            q.add_argument("--into", default="tests/visual")
        if name == "save":
            q.add_argument("--from", dest="src", default="tests/visual")
        q.set_defaults(fn=fn)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
