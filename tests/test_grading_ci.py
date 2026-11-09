"""CI for grading repos (4.3): `gradekit ci`, the host templates and fetch-kit.py."""
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLE, SRC, serve

KIT = [sys.executable, str(SRC / "tools" / "gradekit.py")]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", **GIT_ENV)
PROJ = "projects/orders-api"
NEW = f"{PROJ}/reports/2026-11-07-a1b2c3d"


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


def ci(repo, *extra):
    r = subprocess.run(KIT + ["ci", "--base", "main", "--json", *map(str, extra)], cwd=repo, env=ENV, capture_output=True, text=True)
    out = json.loads(r.stdout)
    assert out["exit_code"] == r.returncode
    return out["result"]


@pytest.fixture
def repo(tmp_path):
    """The example grading repo in git, without its newest report; work happens on branch `pr`."""
    g = tmp_path / "grading"
    shutil.copytree(EXAMPLE, g)
    shutil.move(str(g / NEW), str(tmp_path / "newest"))
    git(g, "init", "-q", "-b", "main")
    git(g, "add", "-A")
    git(g, "commit", "-qm", "base")
    git(g, "switch", "-q", "-c", "pr")
    return g


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def add_newest(repo):
    shutil.copytree(repo.parent / "newest", repo / NEW)


def test_a_good_report_pull_request(repo):
    add_newest(repo)
    commit(repo)
    res = ci(repo, "--site", "https://example.com/suite", "--grading-repo-url", "https://github.com/acme/grading",
             "--branch", "report/orders-api/2026-11-07-a1b2c3d")
    assert res["ok"] and res["kind"] == "report" and res["labels"] == ["grading: report"], res
    assert res["summary"]["overall"] == 4.9 and res["summary"]["level"] == "L0"
    c = res["comment"]
    assert c.startswith("<!-- gradekit-ci -->") and "✅ passed" in c and "- [ ] D1-act-1:" in c
    assert "review.html?repo=https://github.com/acme/grading&project=orders-api&ref=report/orders-api/2026-11-07-a1b2c3d" in c


@pytest.mark.parametrize("change, expect", [
    ("private", "private report"),
    ("edit-old", "never edited"),
    ("two", "adds one report"),
    ("mixed", "changes only its report folder"),
    ("stray", "holds only report.json"),
    ("hand-edit", "doesn't match the report"),
    ("wrong-folder", "expected <date>-a1b2c3d"),
    ("other-file", "grading changes come on their own"),
])
def test_report_pull_requests_that_need_changes(repo, change, expect):
    add_newest(repo)
    new = repo / NEW
    if change == "private":
        (new / "report.private.json").write_text("{}")
        git(repo, "add", "-f", str(new / "report.private.json"))   # past the .gitignore, as a careless push would
    elif change == "edit-old":
        old = repo / PROJ / "reports" / "2026-10-24-9f8e7d6" / "report.md"
        old.write_text(old.read_text() + "\nedited\n")
    elif change == "two":
        shutil.copytree(new, repo / PROJ / "reports" / "2026-11-08-a1b2c3d")
    elif change == "mixed":
        (repo / PROJ / "project.toml").write_text((repo / PROJ / "project.toml").read_text() + "\n# note\n")
    elif change == "stray":
        (new / "notes.txt").write_text("hi")
    elif change == "hand-edit":
        r = json.loads((new / "report.json").read_text())
        r["rollup"]["overall_score"] = 9.9
        (new / "report.json").write_text(json.dumps(r, indent=2))
    elif change == "wrong-folder":
        shutil.move(str(new), str(repo / PROJ / "reports" / "2026-11-07-0000000"))
    elif change == "other-file":
        (repo / "notes.md").write_text("hi")
    commit(repo)
    res = ci(repo)
    assert not res["ok"] and "grading: needs changes" in res["labels"], res
    assert any(expect in p for p in res["problems"]), res["problems"]
    assert "❌ needs changes" in res["comment"]


def test_decisions_are_append_only(repo):
    d = repo / PROJ / "decisions.json"
    data = json.loads(d.read_text())
    data["decisions"].append({"action_id": "D1-act-1", "approved": True, "answer": "Implement CSV only", "decided_by": "jane@example.com"})
    d.write_text(json.dumps(data, indent=2))
    commit(repo, "decide")
    res = ci(repo)
    assert res["ok"] and res["kind"] == "settings" and res["labels"] == ["grading: settings"], res
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "pr")
    git(repo, "switch", "-q", "pr")
    data["decisions"][0]["approved"] = False
    d.write_text(json.dumps(data, indent=2))
    commit(repo, "rewrite history")
    res = ci(repo)
    assert not res["ok"] and any("append-only" in p for p in res["problems"])


def test_entries_need_their_fields(repo):
    d = repo / PROJ / "dispositions.json"
    data = json.loads(d.read_text())
    data["dispositions"].append({"finding_id": "A3-001"})
    d.write_text(json.dumps(data))
    commit(repo)
    res = ci(repo)
    assert any("needs decision, reason" in p for p in res["problems"])


def test_config_changes_are_flagged(repo):
    t = repo / PROJ / "project.toml"
    t.write_text(t.read_text().replace('data_sensitivity = "financial"', 'data_sensitivity = "none"') if 'data_sensitivity = "financial"' in t.read_text()
                 else t.read_text() + '\n[overrides]\nF4 = { weight = 1, reason = "test" }\n')
    commit(repo)
    res = ci(repo)
    assert res["ok"] and any("scoring config changes" in w for w in res["warnings"]), res


def test_a_new_project(repo):
    subprocess.run(KIT + ["init", "--project", "shop", "--preset", "web_app"], cwd=repo, env=ENV, check=True, capture_output=True)
    commit(repo)
    res = ci(repo)
    assert res["ok"] and res["kind"] == "settings" and res["summary"]["new_projects"] == ["shop"], res


def test_nothing_to_check(repo):
    (repo / "notes.md").write_text("hi")
    commit(repo)
    res = ci(repo)
    assert res["ok"] and res["kind"] == "other" and res["labels"] == []


# --------------------------------------------------------------------------- fetch-kit.py and the templates

def test_fetch_kit_from_a_site(static_site, tmp_path):
    r = subprocess.run([sys.executable, str(SRC / "ci" / "fetch-kit.py"), static_site, str(tmp_path / "kit")],
                       env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    kit = r.stdout.strip()
    assert os.path.isfile(os.path.join(kit, "tools", "gradekit.py"))
    v = subprocess.run([sys.executable, os.path.join(kit, "tools", "gradekit.py"), "ci", "--help"], capture_output=True, text=True)
    assert v.returncode == 0


def test_fetch_kit_refuses_a_tampered_kit(built, tmp_path):
    root = tmp_path / "host"
    shutil.copytree(built / "web", root)
    m = json.loads((root / "manifest.json").read_text())
    z = root / m["download"]["path"]
    z.write_bytes(z.read_bytes() + b"tampered")
    server, port = serve(functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    try:
        r = subprocess.run([sys.executable, str(SRC / "ci" / "fetch-kit.py"), f"http://127.0.0.1:{port}/", str(tmp_path / "kit")],
                           env=ENV, capture_output=True, text=True)
    finally:
        server.shutdown()
    assert r.returncode != 0 and "checksum" in r.stderr and not (tmp_path / "kit").exists()


@pytest.mark.parametrize("name", ["github-grading.yml", "gitlab-grading.yml"])
def test_templates_call_ci_with_real_flags(name):
    text = (SRC / "ci" / name).read_text()
    assert "__SUITE_SITE__" in text and "fetch-kit.py" in text
    call = re.search(r'gradekit\.py" ci (.+?)(?:\|\| status|\n\s*\n|\n      - )', text, re.S).group(1)
    helptext = subprocess.run(KIT + ["ci", "--help"], capture_output=True, text=True).stdout
    for flag in set(re.findall(r"--[a-z-]+", call)):
        assert flag in helptext, f"{name} uses {flag}, which `gradekit ci` doesn't have"


def test_init_adds_the_check(tmp_path):
    subprocess.run(KIT + ["init", "--project", "a", "--ci", "github", "--site", "https://acme.example/g/"], cwd=tmp_path, check=True, capture_output=True)
    wf = (tmp_path / ".github" / "workflows" / "grading.yml").read_text()
    assert "vars.SUITE_SITE || 'https://acme.example/g'" in wf
    (tmp_path / ".gitlab-ci.yml").write_text("build:\n  script: [make]\n")
    out = subprocess.run(KIT + ["init", "--project", "b", "--ci", "gitlab"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout
    assert (tmp_path / ".gitlab" / "grading.yml").exists() and "include:" in out
    assert (tmp_path / ".gitlab-ci.yml").read_text() == "build:\n  script: [make]\n", "an existing pipeline is never overwritten"


def test_a_report_pull_request_may_carry_answers_to_its_own_questions(repo):
    """The decide job commits ticked answers to the report's branch (5.0): appended to that project's decisions.json."""
    add_newest(repo)
    commit(repo, "report")
    subprocess.run(KIT + ["decide", "--project", "orders-api", "--approve", "D1-act-1", "--by", "octocat"], cwd=repo, check=True,
                   capture_output=True)
    commit(repo, "answers")
    res = ci(repo)
    assert res["ok"] and res["kind"] == "report", res["problems"]
    assert res["summary"]["pending_decisions"] == [], "the comment counts the answers on the branch"


def test_answers_on_a_report_pull_request_are_still_append_only(repo):
    d = repo / PROJ / "decisions.json"
    data = json.loads(d.read_text())
    data["decisions"].append({"action_id": "D1-act-1", "approved": True, "decided_by": "a", "date": "2026-11-01"})
    d.write_text(json.dumps(data, indent=2))
    commit(repo, "earlier answer")
    git(repo, "branch", "-f", "main")
    add_newest(repo)
    data["decisions"][-1]["approved"] = False
    d.write_text(json.dumps(data, indent=2))
    commit(repo)
    res = ci(repo)
    assert not res["ok"] and any("append-only" in p for p in res["problems"]), res["problems"]
