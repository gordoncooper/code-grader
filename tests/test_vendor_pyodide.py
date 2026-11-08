"""A website with Pyodide included (4.3): tools/vendor_pyodide.py, for air-gapped and strict-policy hosts."""
import functools
import hashlib
import http.server
import json
import shutil
import subprocess
import sys

import pytest

from conftest import SRC, serve

TOOL = [sys.executable, str(SRC / "tools" / "vendor_pyodide.py")]


def vendor(site, *extra):
    return subprocess.run(TOOL + [str(site), *map(str, extra)], capture_output=True, text=True)


def test_refuses_files_that_dont_match_the_pins(built, tmp_path):
    site = tmp_path / "web"
    shutil.copytree(built / "web", site)
    fake = tmp_path / "fake"
    fake.mkdir()
    for name in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
        (fake / name).write_text("not pyodide")
    before = (site / "assets" / "engine-config.js").read_text()
    r = vendor(site, "--from", fake)
    assert r.returncode != 0 and "doesn't match its pinned hash" in r.stderr
    assert (site / "assets" / "engine-config.js").read_text() == before, "nothing is switched over on failure"


def test_needs_a_built_site(tmp_path):
    r = vendor(tmp_path)
    assert r.returncode != 0 and "isn't a built website" in r.stderr


@pytest.fixture(scope="session")
def vendored(built, tmp_path_factory):
    site = tmp_path_factory.mktemp("vendored") / "web"
    shutil.copytree(built / "web", site)
    r = vendor(site)
    if r.returncode != 0:
        pytest.skip(f"couldn't download Pyodide: {r.stderr.strip()}")
    return site


@pytest.mark.network
def test_the_site_is_consistent_after(vendored):
    cfg = (vendored / "assets" / "engine-config.js").read_text()
    assert 'pyodideIndexURL: "../pyodide/"' in cfg
    manifest = json.loads((vendored / "manifest.json").read_text())
    paths = {f["path"]: f["sha256"] for f in manifest["files"]}
    assert "pyodide/pyodide.asm.wasm" in paths and any(p.startswith("pyodide/jsonschema-") for p in paths)
    for path, digest in paths.items():
        assert hashlib.sha256((vendored / path).read_bytes()).hexdigest() == digest, path
    assert (vendored / "SHA256SUMS").read_text().count("\n") == len(paths)
    again = vendor(vendored)
    assert again.returncode != 0 and "already includes Pyodide" in again.stderr


@pytest.mark.browser
@pytest.mark.network
def test_runs_with_no_cdn_at_all(strict_page, vendored):
    """The CDN is blocked outright: the pages still work, under the strict policy, with every file checked."""
    page = strict_page
    cdn, loaded = [], []
    page.context.route("https://cdn.jsdelivr.net/**", lambda route: (cdn.append(route.request.url), route.abort()))
    page.on("requestfinished", lambda r: loaded.append(r.url))
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(vendored)))
    try:
        page.goto(f"http://127.0.0.1:{port}/app/review.html")
        page.wait_for_selector("#engine-pill.ready", timeout=180000)
        page.click("#sample")
        page.wait_for_selector("#results:not([hidden])", timeout=60000)
        assert "Report format and rules: Valid" in page.inner_text("#panel-overview .checks"), "jsonschema loaded locally"
        assert cdn == [] and page.csp_violations() == []
        assert any("/pyodide/jsonschema-" in u for u in loaded) and any(u.endswith("/pyodide/pyodide.asm.wasm") for u in loaded)
    finally:
        server.shutdown()
