#!/usr/bin/env python3
"""Build bundle/ from source/, the kit's single source of truth.

    python3 .github/scripts/bundles.py status        # what state source/ and bundle/ are in
    python3 .github/scripts/bundles.py smoke         # quick checks that the kit in source/ works
    python3 .github/scripts/bundles.py sync --check  # fail if bundle/ needs rebuilding (CI on main)
    python3 .github/scripts/bundles.py sync --write  # rebuild bundle/ when it should be (CI on pull requests)

The rules:
- source/ holds the kit. bundle/ is generated from it; never edit bundle/ by hand.
- bundle/SOURCE-SHA256 records which source/ the bundles were built from.
- The top heading of source/CHANGELOG.md says what source/ is:
    "## 4.3.0 (unreleased)"  work in progress: bundle/ stays at the last release
    "## 4.3.0"               a release: bundle/ is rebuilt and the release workflow publishes it
- Changing source/ needs a new version heading. Without one, the released bundle and its
  source would disagree, so sync fails and asks for it.

CI rebuilds bundle/ (sync --write) on pull requests and commits the result to the PR branch,
so every bundle is built the same way (zip bytes depend on the zlib in use).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "source"
BUNDLE = ROOT / "bundle"
HASH_FILE = BUNDLE / "SOURCE-SHA256"
BARE_EXCLUDE = ("tools/build_web.py", "tools/web/")  # the website builder; its output is bundle/web/
SKIP_PARTS = {"__pycache__", ".DS_Store"}


class SyncError(Exception):
    pass


def source_files():
    out = []
    for p in sorted(SRC.rglob("*")):
        rel = p.relative_to(SRC).as_posix()
        if p.is_file() and not (set(p.relative_to(SRC).parts) & SKIP_PARTS) and not rel.endswith(".pyc"):
            out.append((rel, p))
    return out


def source_hash() -> str:
    h = hashlib.sha256()
    for rel, p in source_files():
        h.update(rel.encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def source_version() -> str:
    return json.loads((SRC / "rubric" / "catalog.json").read_text(encoding="utf-8"))["suite_version"]


def changelog_top() -> tuple:
    for line in (SRC / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (\d+\.\d+\.\d+)(.*)$", line)
        if m:
            return m.group(1), "unreleased" in m.group(2).lower()
    raise SyncError("source/CHANGELOG.md has no '## X.Y.Z' heading")


def bundle_version():
    manifest = BUNDLE / "web" / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["version"] if manifest.exists() else None


def recorded_hash():
    return HASH_FILE.read_text(encoding="utf-8").strip() if HASH_FILE.exists() else None


def state() -> dict:
    version = source_version()
    top, unreleased = changelog_top()
    if top != version:
        raise SyncError(f"source/rubric/catalog.json says {version} but source/CHANGELOG.md starts at {top}")
    return {"version": version, "unreleased": unreleased, "bundle_version": bundle_version(),
            "source_hash": source_hash(), "recorded_hash": recorded_hash()}


def clean_pycache():
    for d in SRC.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def build(dest: Path) -> None:
    """Build bare/ and web/ under dest."""
    bare = dest / "bare"
    for rel, p in source_files():
        if rel.startswith(BARE_EXCLUDE):
            continue
        target = bare / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(SRC / "tools" / "build_web.py"), "--out", str(dest / "web")], check=True, env=env)
    clean_pycache()


def verify_sums(web: Path) -> None:
    for line in (web / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        name = name.lstrip("*")
        if hashlib.sha256((web / name).read_bytes()).hexdigest() != digest:
            raise SyncError(f"bundle/web checksum mismatch: {name}")


def cmd_status(_args) -> int:
    print(json.dumps(state(), indent=2))
    return 0


def cmd_smoke(_args) -> int:
    """Quick checks that the kit in source/ runs. The full test suite lives in its own workflow."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    kit = [sys.executable, str(SRC / "tools" / "gradekit.py")]
    example = SRC / "examples" / "grading-repo"
    checks = [
        (kit + ["validate", "--project", "orders-api"], example, 0),
        (kit + ["verify-evidence", "--project", "orders-api", "--repo", "../sample-repo"], example, 0),
        (kit + ["rollup", "--project", "orders-api"], example, 0),
        (kit + ["resolve", "--project", "orders-api"], example, 0),
        (kit + ["presets"], example, 0),
    ]
    failed = 0
    for argv, cwd, want in checks:
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
        ok = r.returncode == want
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {' '.join(argv[2:])} (exit {r.returncode})")
        if not ok:
            print(r.stdout[-2000:], r.stderr[-2000:], sep="\n")
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))
        verify_sums(Path(tmp) / "web")
        print(f"ok   website builds ({sum(1 for _ in (Path(tmp) / 'web').rglob('*') if _.is_file())} files, checksums verify)")
    clean_pycache()
    return 1 if failed else 0


def cmd_sync(args) -> int:
    s = state()
    out = os.environ.get("GITHUB_OUTPUT")

    def emit(changed: bool):
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"changed={'true' if changed else 'false'}\nversion={s['version']}\n")

    if s["unreleased"]:
        if s["version"] == s["bundle_version"]:
            raise SyncError(f"{s['version']} is marked unreleased but bundle/ already holds {s['version']}; use the next version number")
        print(f"source/ is {s['version']} (unreleased); bundle/ stays at {s['bundle_version']}")
        emit(False)
        return 0
    same_version = s["version"] == s["bundle_version"]
    if same_version and s["source_hash"] == s["recorded_hash"]:
        print(f"bundle/ is up to date with source/ ({s['version']})")
        emit(False)
        return 0
    if same_version and s["recorded_hash"] is not None:
        raise SyncError(f"source/ changed but is still {s['version']}, which is already released. Add a CHANGELOG heading for the "
                        f"next version (and set rubric/catalog.json to it), marked '(unreleased)' until you release it.")
    reason = "first build from source/" if same_version else f"release {s['version']} (bundle/ holds {s['bundle_version']})"
    if args.check:
        raise SyncError(f"bundle/ needs rebuilding ({reason}). CI does this on the pull request; locally: "
                        f"python3 .github/scripts/bundles.py sync --write")
    print(f"rebuilding bundle/: {reason}")
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))
        verify_sums(Path(tmp) / "web")
        for part in ("bare", "web"):
            shutil.rmtree(BUNDLE / part, ignore_errors=True)
            shutil.copytree(Path(tmp) / part, BUNDLE / part)
    HASH_FILE.write_text(s["source_hash"] + "\n", encoding="utf-8")
    emit(True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("smoke")
    p = sub.add_parser("sync")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    try:
        return {"status": cmd_status, "smoke": cmd_smoke, "sync": cmd_sync}[args.cmd](args)
    except SyncError as e:
        print(f"::error::{e}" if os.environ.get("GITHUB_ACTIONS") else f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
