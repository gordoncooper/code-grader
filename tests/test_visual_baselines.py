"""The screenshot baselines' branch (.github/scripts/visual_baselines.py), against a scratch remote."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "visual_baselines.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def run(*args, cwd, check=True):
    r = subprocess.run([*args], cwd=cwd, env=ENV, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def vb(work, *args):
    return run(sys.executable, str(SCRIPT), *args, cwd=work).stdout


@pytest.fixture
def work(tmp_path):
    run("git", "init", "-q", "--bare", "remote.git", cwd=tmp_path)
    run("git", "clone", "-q", "remote.git", "work", cwd=tmp_path)
    w = tmp_path / "work"
    run("git", "commit", "-q", "--allow-empty", "-m", "init", cwd=w)
    for b in ("main", "kit/ui", "kit/other"):
        run("git", "push", "-q", "origin", f"HEAD:{b}", cwd=w)
    return w


def shots(d: Path, **files):
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "baselines.json").write_text("{}\n")
    return d


def tree(work):
    run("git", "fetch", "-q", "origin", "visual-baselines", cwd=work)
    names = run("git", "ls-tree", "-r", "--name-only", "FETCH_HEAD", cwd=work).stdout.split()
    commits = int(run("git", "rev-list", "--count", "FETCH_HEAD", cwd=work).stdout)
    return sorted(names), commits


def test_a_branch_uses_its_own_baselines_or_mains(work, tmp_path):
    assert "will make them" in vb(work, "fetch", "--branch", "main", "--into", str(tmp_path / "got"))
    vb(work, "save", "--branch", "main", "--from", str(shots(tmp_path / "m", **{"home.png": b"main"})))
    vb(work, "save", "--branch", "kit/ui", "--from", str(shots(tmp_path / "u", **{"home.png": b"ui"})))
    assert vb(work, "which", "--branch", "kit/ui").strip() == "kit--ui"
    assert vb(work, "which", "--branch", "kit/other").strip() == "main"
    got = tmp_path / "got"
    vb(work, "fetch", "--branch", "kit/ui", "--into", str(got))
    assert (got / "home.png").read_bytes() == b"ui"
    vb(work, "fetch", "--branch", "kit/other", "--into", str(got))
    assert (got / "home.png").read_bytes() == b"main"
    assert tree(work) == (["kit--ui/baselines.json", "kit--ui/home.png", "main/baselines.json", "main/home.png"], 1), \
        "always one commit: old images don't pile up"


def test_merging_promotes_and_deleted_branches_are_dropped(work, tmp_path):
    vb(work, "save", "--branch", "main", "--from", str(shots(tmp_path / "m", **{"home.png": b"main", "old.png": b"x"})))
    vb(work, "save", "--branch", "kit/ui", "--from", str(shots(tmp_path / "u", **{"home.png": b"ui"})))
    vb(work, "save", "--branch", "kit/other", "--from", str(shots(tmp_path / "o", **{"home.png": b"other"})))
    assert "Baselines for main, from kit/ui" in vb(work, "promote", "--branch", "kit/ui")
    names, commits = tree(work)
    assert names == ["kit--other/baselines.json", "kit--other/home.png", "main/baselines.json", "main/home.png"] and commits == 1
    got = tmp_path / "got"
    vb(work, "fetch", "--branch", "main", "--into", str(got))
    assert (got / "home.png").read_bytes() == b"ui" and not (got / "old.png").exists(), "the folder is replaced, not merged"
    run("git", "push", "-q", "origin", "--delete", "kit/other", cwd=work)
    vb(work, "save", "--branch", "main", "--from", str(shots(tmp_path / "m2", **{"home.png": b"main2"})))
    assert tree(work)[0] == ["main/baselines.json", "main/home.png"]
    assert "has no baselines of its own" in vb(work, "promote", "--branch", "kit/none")
    assert "nothing changed" in vb(work, "save", "--branch", "main", "--from", str(tmp_path / "m2"))


def test_the_workflow_writes_baselines_from_one_job_only():
    import re
    text = (SCRIPT.parent.parent / "workflows" / "tests.yml").read_text()
    jobs = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", text[text.index("\njobs:\n"):], re.M | re.S))
    assert set(jobs) == {"engine", "website", "baselines"}
    writers = [n for n, body in jobs.items() if re.search(r"^\s+contents: write", body, re.M)]
    assert writers == ["baselines"]
    assert re.search(r"concurrency:\n\s+group: visual-baselines\n\s+cancel-in-progress: false", jobs["baselines"])
    assert "git push" not in text and "git commit" not in text, "nothing commits to the branch under test any more"
    assert (SCRIPT.parent.parent.parent / ".gitignore").read_text().count("tests/visual/*.png") == 1
