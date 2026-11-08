"""One engine (4.3): the rules for finding projects, ordering reports and recognising files live only in
gradekit, which the website calls. These tests pin the rules and keep them out of the JavaScript."""
import re

from conftest import SRC

WEB = SRC / "tools" / "web"


def test_scan_layout_uses_paths_only(gk):
    paths = ["org.toml", "projects/api/project.toml", "projects/api/decisions.json",
             "projects/api/reports/2026-11-01-aaa/report.json", "projects/api/reports/2026-11-01-aaa/runs/run-1.json",
             "projects/api/reports/2026-11-02-bbb/report.json", "projects/api/reports/2026-11-03-ccc/notes.md",
             "projects/web/project.toml", "kit/tools/gradekit.py", "kit/examples/grading-repo/projects/demo/project.toml"]
    projects = gk.scan_layout(paths)
    assert [p["name"] for p in projects] == ["api", "web"], "the kit copy's example is skipped"
    api = projects[0]
    assert api["side"] == {"project.toml": "projects/api/project.toml", "decisions.json": "projects/api/decisions.json"}
    assert api["org"] == "org.toml"
    assert sorted(api["reports"]) == ["2026-11-01-aaa", "2026-11-02-bbb"], "folders without report.json are ignored"
    assert api["reports"]["2026-11-01-aaa"]["runs"] == ["projects/api/reports/2026-11-01-aaa/runs/run-1.json"]


def test_only_the_example_inside_kit_copies(gk):
    paths = ["a/tools/gradekit.py", "a/examples/grading-repo/projects/demo/project.toml",
             "b/suite/tools/gradekit.py", "b/suite/examples/grading-repo/projects/demo/project.toml"]
    assert [p["root"] for p in gk.scan_layout(paths)] == ["a/examples/grading-repo/projects/demo"]


def test_order_reads_run_dates_only_for_same_day_reports(gk):
    folders = ["2026-11-03-c", "2026-11-01-a", "2026-11-03-b", "2026-11-02-x"]
    ordered, need = gk.order_report_folders(folders)
    assert sorted(need) == ["2026-11-03-b", "2026-11-03-c"]
    ordered, need = gk.order_report_folders(folders, {"2026-11-03-b": "2026-11-03T18:00:00Z", "2026-11-03-c": "2026-11-03T09:00:00Z"})
    assert need == [] and ordered == ["2026-11-01-a", "2026-11-02-x", "2026-11-03-c", "2026-11-03-b"]


def report(commit, date):
    return {"benchmarks": [], "run": {"commit": commit, "date": date}}


def test_classify_loose_files(gk):
    files = [{"name": "old.json", "json": report("aaa", "2026-10-01")},
             {"name": "new.json", "json": report("bbb", "2026-11-01")},
             {"name": "run-2.json", "json": report("bbb", "2026-11-01T02:00:00Z")},
             {"name": "project.toml"}, {"name": "extra.toml"}, {"name": "code.zip"},
             {"name": "d.json", "json": {"decisions": []}}, {"name": "x.json", "json": {"dispositions": []}},
             {"name": "broken.json", "error": "not valid JSON"}, {"name": "notes.json", "json": {"hello": 1}}]
    assert gk.classify_files(files) == ["previous", "report", "run", "project", "org", "zip",
                                        "decisions", "dispositions", "ignore", "ignore"]


def test_a_chosen_role_is_kept(gk):
    files = [{"name": "a.json", "json": report("aaa", "2026-10-01"), "role": "report"},
             {"name": "b.json", "json": report("bbb", "2026-11-01")}]
    assert gk.classify_files(files) == ["report", "previous"], "a newer report doesn't replace one the person chose"


def test_the_review_page_has_no_copies_of_these_rules():
    js = (WEB / "review.js").read_text()
    for pattern in (r'lastIndexOf\("reports"\)', r"tools/gradekit\\\.py", r"Array\.isArray\(f\.json\.benchmarks\)"):
        assert not re.search(pattern, js), f"review.js re-implements an engine rule: {pattern}"
    for call in ("scan_layout", "order_reports", "classify"):
        assert f'GK.call("{call}"' in js
