"""Download the grading kit from a suite website and check it against the site's checksum.

    python3 fetch-kit.py SUITE_SITE [DEST]     # prints the kit folder (the one with tools/gradekit.py)

Used by the CI templates in this folder; standard library only, so it runs before the kit exists.
"""
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("usage: fetch-kit.py SUITE_SITE [DEST]   (SUITE_SITE: the suite website's address)")
    site = sys.argv[1].rstrip("/") + "/"
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else "gradekit-kit")
    manifest = json.load(urllib.request.urlopen(site + "manifest.json", timeout=60))
    dl = manifest["download"]
    data = urllib.request.urlopen(site + dl["path"], timeout=120).read()
    if hashlib.sha256(data).hexdigest() != dl["sha256"]:
        sys.exit(f"the kit from {site} doesn't match its published checksum; not using it")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                sys.exit(f"unsafe path in the kit archive: {name}")
        zf.extractall(dest)
    tool = next(dest.rglob("tools/gradekit.py"), None)
    if tool is None:
        sys.exit("the kit archive has no tools/gradekit.py")
    print(tool.parent.parent.resolve())
    print(f"kit {manifest.get('version')} from {site}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
