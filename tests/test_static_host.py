"""The built site, unmodified, on a plain static server under a sub-path, with the real Pyodide engine.

Proves the site needs no particular host. Needs the internet (Pyodide loads from its CDN)."""
import pytest

pytestmark = [pytest.mark.browser, pytest.mark.network]


def test_real_engine_on_a_plain_static_host(page, static_site):
    page.goto(static_site + "app/review.html")
    page.wait_for_selector("#engine-pill.ready", timeout=180000)
    page.click("#sample")
    page.wait_for_selector("#results:not([hidden])", timeout=60000)
    assert "Report format and rules: Valid" in page.inner_text("#panel-overview .checks")
    page.goto(static_site + "app/setup.html")
    page.wait_for_selector("#engine-pill.ready", timeout=180000)
    page.wait_for_function("document.querySelector('#pv-status').textContent.includes('Valid')", timeout=60000)
    assert not page.errors
