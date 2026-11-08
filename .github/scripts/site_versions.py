#!/usr/bin/env python3
"""Assemble the website for GitHub Pages with every major version at its own path.

    python3 .github/scripts/site_versions.py OUT [--repo DIR]

OUT/            the newest version: bundle/web/ as it is in the checkout (main)
OUT/vN/         the newest release of each major N. The checkout's own major comes from the checkout too, so a
                release that is still being tagged is never served from the previous tag. Older majors come
                from the newest vN.x.y tag's bundle/web/.
versions.json   in OUT/ and in every OUT/vN/: the versions on the site, newest first, with paths relative to
                that file. The pages show a version menu from it, and AGENT.md tells agents to use it to follow
                a project's pin (suite = "N" in project.toml).

Every copy is checked against its own SHA256SUMS before it's used. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ABOUT = ("The versions of the Code Grading Suite this site hosts, newest first. `path` is relative to this file. "
         "Projects pin a major version (suite = \"N\" in project.toml); use that major's path.")


class SiteError(Exception):
    pass


def semver(tag: str):
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(x) for x in m.groups()) if m else None


def git(repo: Path, *args, binary=False):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if r.returncode != 0:
        raise SiteError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout if binary else r.stdout.decode().strip()


def verify(site: Path, label: str) -> None:
    sums = site / "SHA256SUMS"
    if not sums.is_file():
        raise SiteError(f"{label}: no SHA256SUMS")
    bad = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        f = site / name.lstrip("*").strip()
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            bad.append(name.strip())
    if bad:
        raise SiteError(f"{label}: {len(bad)} file(s) don't match SHA256SUMS, e.g. {bad[0]}")


def site_version(site: Path) -> str:
    return json.loads((site / "manifest.json").read_text(encoding="utf-8"))["version"]


def extract_tag(repo: Path, tag: str, dest: Path) -> None:
    data = git(repo, "archive", "--format=tar", tag, "bundle/web", binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if parts[:2] != ("bundle", "web") or ".." in parts or m.issym() or m.islnk():
                continue
            rel = Path(*parts[2:]) if len(parts) > 2 else None
            if rel is None:
                continue
            target = dest / rel
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())


def assemble(repo: Path, out: Path) -> dict:
    web = repo / "bundle" / "web"
    if not (web / "index.html").is_file():
        raise SiteError("bundle/web/index.html not found; nothing to publish yet")
    verify(web, "bundle/web")
    newest = site_version(web)
    newest_major = newest.split(".")[0]
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out)
    shutil.copytree(web, out / f"v{newest_major}")
    hosted = {newest_major: newest}

    tags = [t for t in git(repo, "tag", "-l", "v*").splitlines() if semver(t)]
    best: dict[str, str] = {}
    for t in sorted(tags, key=semver):
        best[str(semver(t)[0])] = t
    for maj, tag in sorted(best.items(), key=lambda kv: -int(kv[0])):
        if maj == newest_major or int(maj) > int(newest_major):
            continue
        try:
            git(repo, "cat-file", "-e", f"{tag}:bundle/web/index.html")
        except SiteError:
            print(f"skip {tag}: it has no bundle/web/")
            continue
        dest = out / f"v{maj}"
        extract_tag(repo, tag, dest)
        verify(dest, tag)
        hosted[maj] = site_version(dest)

    versions = [{"major": m, "version": hosted[m]} for m in sorted(hosted, key=int, reverse=True)]
    for folder, prefix in [(out, "")] + [(out / f"v{m}", "../") for m in hosted]:
        doc = {"_about": ABOUT, "latest": newest,
               "versions": [{**v, "path": f"{prefix}v{v['major']}/"} for v in versions]}
        (folder / "versions.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"latest": newest, "hosted": versions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="where to write the site (replaced)")
    ap.add_argument("--repo", default=".", help="the code-grader checkout, with tags (default: here)")
    args = ap.parse_args(argv)
    try:
        res = assemble(Path(args.repo).resolve(), Path(args.out).resolve())
    except SiteError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"site: {res['latest']} at the root; " + ", ".join(f"v{v['major']}/ = {v['version']}" for v in res["hosted"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
