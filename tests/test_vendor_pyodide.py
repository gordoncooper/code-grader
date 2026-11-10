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


# --------------------------------------------------------------------------- license notices (5.0.1)

def test_notices_list_everything_copied_with_its_license(tmp_path):
    import importlib.util
    import io
    import zipfile
    spec = importlib.util.spec_from_file_location("vendor_pyodide", SRC / "tools" / "vendor_pyodide.py")
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("attrs-25.3.0.dist-info/licenses/LICENSE", "The MIT License (MIT)\nCopyright (c) 2015 Hynek")
        z.writestr("attrs-25.3.0.dist-info/METADATA", "Name: attrs")
        z.writestr("attrs/__init__.py", "")
    lic = vp.wheel_licenses(buf.getvalue())
    assert list(lic) == ["attrs-25.3.0.dist-info/licenses/LICENSE"]
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "pyodide-LICENSE").write_text("Mozilla Public License Version 2.0")
    (texts / "cpython-LICENSE").write_text("PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2")
    dest = tmp_path / "pyodide"
    dest.mkdir()
    vp.write_notices(dest, "0.29.3", "3.13.2",
                     [{"name": "attrs", "version": "25.3.0", "file_name": "attrs-25.3.0-py3-none-any.whl", "licenses": lic},
                      {"name": "bare", "version": "1.0", "file_name": "bare-1.0.zip", "licenses": {}}], str(texts))
    notes = (dest / "THIRD-PARTY-NOTICES.md").read_text()
    assert "| Pyodide (" in notes and "MPL-2.0 | https://github.com/pyodide/pyodide/tree/0.29.3" in notes
    assert "PSF-2.0 | https://github.com/python/cpython/tree/v3.13.2" in notes
    assert "`licenses/attrs-25.3.0/licenses/LICENSE`" in notes and "none in its wheel: see https://pypi.org/project/bare/1.0/" in notes
    assert (dest / "licenses" / "attrs-25.3.0" / "licenses" / "LICENSE").read_text().startswith("The MIT License")
    assert (dest / "licenses" / "pyodide-LICENSE").read_text().startswith("Mozilla Public License")
    assert vp.pyodide_version("https://cdn.jsdelivr.net/pyodide/v0.29.3/full/") == "0.29.3"


@pytest.mark.network
def test_the_vendored_site_carries_the_notices(vendored):
    notes = (vendored / "pyodide" / "THIRD-PARTY-NOTICES.md").read_text()
    assert "MPL-2.0" in notes and "PSF-2.0" in notes and "jsonschema" in notes
    assert "Mozilla Public License" in (vendored / "pyodide" / "licenses" / "pyodide-LICENSE").read_text()
    paths = {f["path"] for f in json.loads((vendored / "manifest.json").read_text())["files"]}
    assert "pyodide/THIRD-PARTY-NOTICES.md" in paths, "the notices are part of the checked site"
