"""Shared fixtures: a site built from source/, local servers for it, and a browser."""
import functools
import http.server
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source"
EXAMPLE = SRC / "examples" / "grading-repo"
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import bundles  # noqa: E402  (the same build CI uses)


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: drives the website in Chromium (needs Playwright)")
    config.addinivalue_line("markers", "network: loads the real Pyodide runtime from its CDN (needs the internet)")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def gk():
    """gradekit from source/, imported as a module."""
    # GRADEKIT=path/to/gradekit.py runs the tests against another copy (e.g. an older release, to see them fail).
    return load_module("gradekit_src", Path(os.environ.get("GRADEKIT", SRC / "tools" / "gradekit.py")))


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> Path:
    """bundle/bare and bundle/web, freshly built from source/ (dest/bare, dest/web)."""
    dest = tmp_path_factory.mktemp("build")
    bundles.build(dest)
    return dest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(handler) -> tuple:
    port = free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


@pytest.fixture(scope="session")
def site(built):
    """The built site with a test engine: the page's gradekit calls run in CPython, not Pyodide (no network)."""
    web = built / "web"
    engine = load_module("gradekit_site", web / "suite" / "tools" / "gradekit.py")
    uploads = Path(tempfile.mkdtemp())

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(web), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.split("?")[0].endswith("/assets/engine-config.js"):
                body = b'window.GK_CONFIG = { engine: "http" };'
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if u.path.endswith("/__engine/__file"):
                ext = urllib.parse.parse_qs(u.query).get("ext", [""])[0]
                p = uploads / f"f{len(list(uploads.iterdir()))}{ext}"
                p.write_bytes(data)
                out = {"path": str(p)}
            else:
                out = engine.web_api(urllib.parse.unquote(u.path.rsplit("/", 1)[1]), json.loads(data or b"{}"))
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server, port = serve(Handler)
    yield f"http://127.0.0.1:{port}/"
    server.shutdown()


@pytest.fixture(scope="session")
def static_site(built, tmp_path_factory):
    """The built site, untouched, on a plain static server under a sub-path (any host must work)."""
    root = tmp_path_factory.mktemp("host")
    shutil.copytree(built / "web", root / "grading" / "vtest")
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    yield f"http://127.0.0.1:{port}/grading/vtest/"
    server.shutdown()


@pytest.fixture(scope="session")
def browser():
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    kwargs = {"args": ["--no-sandbox"]}
    if os.environ.get("CHROME_PATH"):
        kwargs["executable_path"] = os.environ["CHROME_PATH"]
    if os.environ.get("HTTPS_PROXY"):
        kwargs["proxy"] = {"server": os.environ["HTTPS_PROXY"], "bypass": "127.0.0.1,localhost"}
    b = pw.chromium.launch(**kwargs)
    yield b
    b.close()
    pw.stop()


class PageErrors(list):
    """Collects console errors and uncaught exceptions from a page."""

    def watch(self, page):
        page.on("pageerror", lambda e: self.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and self.append(f"console: {m.text}"))
        return page


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1320, "height": 1000}, accept_downloads=True)
    p = ctx.new_page()
    errors = PageErrors()
    errors.watch(p)
    p.errors = errors
    yield p
    ctx.close()
