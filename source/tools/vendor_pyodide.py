#!/usr/bin/env python3
"""Put the Python runtime (Pyodide) inside a built Code Grading Suite website.

    python3 vendor_pyodide.py SITE_DIR [--from DIR_OR_URL] [--packages jsonschema …]

The website's Setup and Review pages run gradekit in the browser with Pyodide, which they normally
load from the jsDelivr CDN. For an air-gapped network, or a host whose security policy allows only
its own origin, this copies Pyodide into SITE_DIR/pyodide/ and points the pages at it:

  1. reads the Pyodide version and the pinned SHA-384 hashes from SITE_DIR/assets/engine-config.js;
  2. gets the core files (from the pinned CDN address, or --from a folder or URL with the same release)
     and the packages the pages use (jsonschema and what it needs), and refuses any file whose hash
     doesn't match its pin (core files) or Pyodide's lock file (packages);
  3. sets pyodideIndexURL to the local copy, and rewrites manifest.json and SHA256SUMS.

The pins don't change, so the pages still check every file as they load it. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

CORE = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
LOCAL_INDEX = "../pyodide/"   # relative to the pages (app/*.html)


def die(msg: str) -> None:
    sys.exit(f"error: {msg}")


def read_config(site: Path) -> tuple[str, dict]:
    cfg = (site / "assets" / "engine-config.js").read_text(encoding="utf-8")
    index = re.search(r'pyodideIndexURL:\s*"([^"]+)"', cfg)
    pins = dict(re.findall(r'"([\w.-]+)":\s*"(sha384-[A-Za-z0-9+/=]+)"', cfg))
    if not index:
        die("assets/engine-config.js has no pyodideIndexURL")
    missing = [f for f in CORE if f not in pins]
    if missing:
        die(f"assets/engine-config.js has no pinned hash for {', '.join(missing)}")
    return index.group(1), pins


def fetch(source: str, name: str) -> bytes:
    if re.match(r"https?://", source):
        try:
            with urllib.request.urlopen(source.rstrip("/") + "/" + name, timeout=300) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001 - say which file, whatever went wrong
            die(f"couldn't download {name} from {source}: {exc}")
    path = Path(source) / name
    if not path.is_file():
        die(f"{path} not found (use the same Pyodide release's files)")
    return path.read_bytes()


def sri384(data: bytes) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()


def needed(lock: dict, wanted: list[str]) -> list[str]:
    """The packages to include: those asked for, and everything they depend on."""
    pkgs = {k.lower(): v for k, v in lock.get("packages", {}).items()}
    out, todo = [], [w.lower() for w in wanted]
    while todo:
        name = todo.pop().replace("_", "-")
        key = name if name in pkgs else name.replace("-", "_")
        if key not in pkgs:
            die(f"package '{name}' isn't in this Pyodide release's lock file")
        if key in out:
            continue
        out.append(key)
        todo += [d.lower() for d in pkgs[key].get("depends", [])]
    return sorted(out)


def rewrite_manifest(site: Path) -> None:
    manifest_path = site / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = []
    for p in sorted(site.rglob("*")):
        if p.is_file() and p.name not in ("manifest.json", "SHA256SUMS", "versions.json"):   # versions.json describes the host
            data = p.read_bytes()
            entries.append({"path": p.relative_to(site).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest["files"] = entries
    manifest["pyodide"] = "included (pyodide/)"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (site / "SHA256SUMS").write_text("".join(f"{e['sha256']}  {e['path']}\n" for e in entries), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n\n".join(__doc__.split("\n\n")[1:]))
    ap.add_argument("site", help="a built website folder (bundle/web, or an unpacked web zip)")
    ap.add_argument("--from", dest="source", metavar="DIR_OR_URL",
                    help="where to get Pyodide's files (default: the pinned CDN address in engine-config.js)")
    ap.add_argument("--packages", nargs="+", default=["jsonschema"], help="Pyodide packages the pages need (default: jsonschema)")
    args = ap.parse_args(argv)

    site = Path(args.site)
    if not (site / "manifest.json").is_file() or not (site / "assets" / "engine-config.js").is_file():
        die(f"{site} isn't a built website (no manifest.json or assets/engine-config.js)")
    index, pins = read_config(site)
    if index == LOCAL_INDEX:
        die(f"{site} already includes Pyodide")
    source = args.source or index
    dest = site / "pyodide"
    dest.mkdir(exist_ok=True)

    for name in CORE:
        data = fetch(source, name)
        if sri384(data) != pins[name]:
            die(f"{name} from {source} doesn't match its pinned hash; not using it")
        (dest / name).write_bytes(data)
        print(f"  {name:<22} {len(data) / 1e6:6.1f} MB  checked")
    lock = json.loads((dest / "pyodide-lock.json").read_text(encoding="utf-8"))
    for key in needed(lock, args.packages):
        pkg = {k.lower(): v for k, v in lock["packages"].items()}[key]
        data = fetch(source, pkg["file_name"])
        if hashlib.sha256(data).hexdigest() != pkg["sha256"]:
            die(f"{pkg['file_name']} doesn't match Pyodide's lock file; not using it")
        (dest / pkg["file_name"]).write_bytes(data)
        print(f"  {pkg['file_name']:<22} {len(data) / 1e6:6.1f} MB  checked")

    cfg_path = site / "assets" / "engine-config.js"
    cfg = cfg_path.read_text(encoding="utf-8")
    cfg = re.sub(r'pyodideIndexURL:\s*"[^"]+"', f'pyodideIndexURL: "{LOCAL_INDEX}"', cfg, count=1)
    cfg = cfg.replace("window.GK_CONFIG = {", "// This site includes Pyodide (tools/vendor_pyodide.py): it loads nothing from a CDN.\nwindow.GK_CONFIG = {", 1)
    cfg_path.write_text(cfg, encoding="utf-8")
    rewrite_manifest(site)
    print(f"Pyodide is now in {dest} and the pages load it from there; manifest.json and SHA256SUMS updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
