"""The built site, unmodified, on a plain static server under a sub-path, with the real Pyodide engine.

Proves the site needs no particular host, and that the real engine starts under the pages'
content-security policy with every Pyodide file checked against its pinned hash. Needs the internet
(Pyodide loads from its CDN)."""
import shutil

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.network]


def test_real_engine_on_a_plain_static_host(strict_page, static_site):
    page = strict_page
    requests = []
    page.on("requestfinished", lambda r: requests.append(r.url))
    page.goto(static_site + "app/review.html")
    page.wait_for_selector("#engine-pill.ready", timeout=180000)
    page.click("#sample")
    page.wait_for_selector("#results:not([hidden])", timeout=60000)
    assert "Report format and rules: Valid" in page.inner_text("#panel-overview .checks")
    assert any(u.endswith("/jsonschema-4.23.0-py3-none-any.whl") for u in requests), "packages load (and are checked)"
    page.goto(static_site + "app/setup.html")
    page.wait_for_selector("#engine-pill.ready", timeout=180000)
    page.wait_for_selector("#pv-status:has-text('Valid')", timeout=60000)
    assert page.csp_violations() == []
    assert not page.errors


def test_a_changed_kit_file_is_refused(strict_page, built, tmp_path):
    """The engine checks the suite's files against manifest.json before running them."""
    import functools
    import http.server
    from conftest import serve
    root = tmp_path / "host"
    shutil.copytree(built / "web", root)
    gk = root / "suite" / "tools" / "gradekit.py"
    gk.write_text(gk.read_text() + "\n# changed after the build\n")
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    try:
        strict_page.goto(f"http://127.0.0.1:{port}/app/review.html")
        strict_page.wait_for_selector("#engine-pill.failed", timeout=180000)
        assert "manifest.json" in strict_page.get_attribute("#engine-pill", "title")
    finally:
        server.shutdown()
