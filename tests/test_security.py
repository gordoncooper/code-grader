"""Supply-chain trust (4.3): the content-security policy, pinned Pyodide files and checksummed kit files."""
import base64
import functools
import hashlib
import http.server
import json
import re
import shutil
import urllib.request

import pytest

from conftest import SRC, serve
from states import STATES

POLICY_START = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'wasm-unsafe-eval';"


def test_every_page_carries_the_policy(built):
    pages = [p for p in (built / "web").rglob("*.html") if "suite" not in p.relative_to(built / "web").parts]
    assert len(pages) > 20
    for p in pages:
        m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', p.read_text())
        assert m and m.group(1).startswith(POLICY_START), p
        assert "'unsafe-eval'" not in m.group(1) and "'unsafe-inline'" not in m.group(1), p   # 5.0: no inline styles either
    htaccess = (built / "web" / ".htaccess").read_text()
    assert "Content-Security-Policy" in htaccess and "frame-ancestors 'none'" in htaccess


def test_engine_config_pins_every_core_file():
    cfg = (SRC / "tools" / "web" / "engine-config.js").read_text()
    for name in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
        assert re.search(rf'"{re.escape(name)}": "sha384-[A-Za-z0-9+/=]{{64}}"', cfg), name


@pytest.mark.browser
@pytest.mark.parametrize("state", STATES, ids=[s.__name__ for s in STATES])
def test_pages_work_under_the_policy(strict_page, site, state):
    state(strict_page, site)
    assert strict_page.csp_violations() == []
    assert not strict_page.errors


@pytest.mark.browser
def test_changed_pyodide_files_are_refused(strict_page, built, tmp_path):
    """A self-hosted (or CDN) Pyodide whose files don't match the pins never runs. Offline: fake files."""
    root = tmp_path / "host"
    shutil.copytree(built / "web", root)
    fake = root / "pyodide"
    fake.mkdir()
    (fake / "pyodide-lock.json").write_text(json.dumps({"info": {}, "packages": {}}))
    (fake / "pyodide.js").write_text("window.loadPyodide = async () => { throw new Error('should never run') };")
    cfg = root / "assets" / "engine-config.js"
    cfg.write_text(cfg.read_text().replace('pyodideIndexURL: "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/"', 'pyodideIndexURL: "../pyodide/"'))
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    try:
        strict_page.goto(f"http://127.0.0.1:{port}/app/review.html")
        strict_page.wait_for_selector("#engine-pill.failed", timeout=30000)
        assert "don't match the pinned hashes" in strict_page.get_attribute("#engine-pill", "title")
    finally:
        server.shutdown()


@pytest.mark.network
def test_pins_match_the_published_pyodide():
    cfg = (SRC / "tools" / "web" / "engine-config.js").read_text()
    index = re.search(r'pyodideIndexURL: "([^"]+)"', cfg).group(1)
    for name, pin in re.findall(r'"([\w.-]+)": "(sha384-[^"]+)"', cfg):
        data = urllib.request.urlopen(index + name, timeout=120).read()
        assert "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode() == pin, name
