"""Versioned site paths (5.0): GitHub Pages serves every major at /vN/ from the release tags, with versions.json;
the pages show a version menu and Start a run points prompts at the page's own major."""
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, serve
from test_accessibility import axe, axe_source  # noqa: F401  (a fixture)

sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import site_versions  # noqa: E402

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], env=GIT_ENV, capture_output=True, check=True)


def fake_site(web, version):
    """A minimal bundle/web: index.html, manifest.json and SHA256SUMS that matches them."""
    if web.exists():
        shutil.rmtree(web)
    web.mkdir(parents=True)
    (web / "index.html").write_text(f"<p>{version}</p>")
    (web / "manifest.json").write_text(json.dumps({"version": version}))
    sums = "".join(f"{hashlib.sha256((web / n).read_bytes()).hexdigest()}  {n}\n" for n in ("index.html", "manifest.json"))
    (web / "SHA256SUMS").write_text(sums)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "code-grader"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    for v in ("3.1.0", "4.2.0", "4.3.0"):
        fake_site(r / "bundle" / "web", v)
        git(r, "add", "-A")
        git(r, "commit", "-qm", v)
        git(r, "tag", f"v{v}")
    fake_site(r / "bundle" / "web", "5.0.0")      # merged, but the release workflow hasn't tagged it yet
    git(r, "add", "-A")
    git(r, "commit", "-qm", "5.0.0")
    return r


def test_every_major_at_its_own_path(repo, tmp_path):
    out = tmp_path / "site"
    res = site_versions.assemble(repo, out)
    assert res["latest"] == "5.0.0"
    assert [(v["major"], v["version"]) for v in res["hosted"]] == [("5", "5.0.0"), ("4", "4.3.0"), ("3", "3.1.0")]
    assert (out / "index.html").read_text() == "<p>5.0.0</p>"
    assert (out / "v5" / "index.html").read_text() == "<p>5.0.0</p>", "the newest major comes from the checkout, not a tag"
    assert (out / "v4" / "index.html").read_text() == "<p>4.3.0</p>", "each older major is its newest release"
    assert (out / "v3" / "index.html").read_text() == "<p>3.1.0</p>"
    root = json.loads((out / "versions.json").read_text())
    assert root["latest"] == "5.0.0" and [v["path"] for v in root["versions"]] == ["v5/", "v4/", "v3/"]
    inner = json.loads((out / "v4" / "versions.json").read_text())
    assert [v["path"] for v in inner["versions"]] == ["../v5/", "../v4/", "../v3/"]


def test_a_copy_that_doesnt_match_its_checksums_is_refused(repo, tmp_path):
    (repo / "bundle" / "web" / "index.html").write_text("<p>edited</p>")
    with pytest.raises(site_versions.SiteError, match="don't match SHA256SUMS"):
        site_versions.assemble(repo, tmp_path / "site")


def test_a_tag_without_checksums_is_refused(repo, tmp_path):
    git(repo, "checkout", "-q", "v4.3.0")
    (repo / "bundle" / "web" / "SHA256SUMS").unlink()
    git(repo, "commit", "-qam", "no sums")
    git(repo, "tag", "v4.3.1")
    git(repo, "checkout", "-q", "main")
    with pytest.raises(site_versions.SiteError, match="v4.3.1: no SHA256SUMS"):
        site_versions.assemble(repo, tmp_path / "site")


def test_the_cli(repo, tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / ".github" / "scripts" / "site_versions.py"), str(tmp_path / "s"), "--repo", str(repo)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "v4/ = 4.3.0" in r.stdout


def test_the_pages_workflow_publishes_the_assembled_site():
    wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text()
    assert "site_versions.py _site" in wf and "path: _site" in wf and "fetch-depth: 0" in wf


# --------------------------------------------------------------------------- the pages

@pytest.fixture(scope="module")
def versioned(built, tmp_path_factory):
    """The built site at /, /v5/ and /v4/ on a plain static server, with versions.json, as Pages serves it."""
    root = tmp_path_factory.mktemp("pages") / "site"
    web = built / "web"
    version = json.loads((web / "manifest.json").read_text())["version"]
    major = version.split(".")[0]
    shutil.copytree(web, root)
    shutil.copytree(web, root / f"v{major}")
    shutil.copytree(web, root / "v4")
    for html in (root / "v4").rglob("*.html"):   # stands in for a 4.x release: its pages say 4.3.0
        html.write_text(html.read_text().replace(f'<span class="ver">v{version}</span>', '<span class="ver">v4.3.0</span>'))
    versions = [{"major": major, "version": version}, {"major": "4", "version": "4.3.0"}]
    for folder, prefix in ((root, ""), (root / f"v{major}", "../"), (root / "v4", "../")):
        (folder / "versions.json").write_text(json.dumps({"latest": version, "versions": [
            {**v, "path": f"{prefix}v{v['major']}/"} for v in versions]}))
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    yield f"http://127.0.0.1:{port}/", version, major
    server.shutdown()


@pytest.mark.browser
def test_the_version_menu(page, versioned):
    url, version, major = versioned
    page.goto(url + "index.html")
    page.wait_for_selector(".ver-menu summary")
    page.click(".ver-menu summary")
    links = page.eval_on_selector_all(".ver-menu a", "els => els.map(a => [a.textContent, a.href, a.getAttribute('aria-current')])")
    assert links[0] == [f"v{version} (newest)", f"{url}v{major}/index.html", "page"]
    assert links[1][:2] == ["v4.3.0", f"{url}v4/index.html"]
    page.keyboard.press("Escape")
    assert not page.eval_on_selector(".ver-menu", "d => d.open")
    assert not page.errors


@pytest.mark.browser
def test_a_single_version_site_has_no_menu(page, static_site):
    page.goto(static_site + "index.html")
    page.wait_for_timeout(500)
    assert page.locator(".topbar .ver-menu").count() == 0 and page.locator(".topbar span.ver").count() == 1


@pytest.mark.browser
def test_prompts_point_at_the_pages_own_major(page, versioned):
    url, version, major = versioned
    page.goto(url + "app/run.html")
    page.wait_for_selector("#roles .choice")
    page.fill("#code-loc", "https://github.com/acme/orders-api")
    page.wait_for_function(f"document.querySelector('#prompt-out').textContent.includes('{url}v{major}/AGENT.md')")
    page.goto(url + "v4/app/run.html")
    page.wait_for_selector("#roles .choice")
    page.fill("#code-loc", "https://github.com/acme/orders-api")
    page.wait_for_timeout(500)
    assert f"{url}v4/AGENT.md" in page.inner_text("#prompt-out")


@pytest.mark.browser
def test_the_version_menu_is_accessible(page, versioned, axe_source):
    url, _, _ = versioned
    page.goto(url + "index.html")
    page.wait_for_selector(".ver-menu summary")
    page.click(".ver-menu summary")
    assert axe(page, axe_source) == []


def test_a_built_site_lists_only_itself_outside_its_checksums(built):
    web = built / "web"
    version = json.loads((web / "manifest.json").read_text())["version"]
    doc = json.loads((web / "versions.json").read_text())
    assert doc["versions"] == [{"major": version.split(".")[0], "version": version, "path": "./"}]
    assert "versions.json" not in (web / "SHA256SUMS").read_text(), "a host replaces it, so it can't be checksummed"
