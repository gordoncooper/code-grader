"""What the first 6.0 calibration runs (three graders of dbader/schedule) asked for: cut quotes flagged, a command run
twice, color codes in output, the order of a benchmark's actions, credentials in the environment, and kit text that
agrees with the rubric."""
import json
import re

from test_gate_feedback import EXAMPLE, PROJ, bench, cli, code, js, load, rel, repo  # noqa: F401  (fixtures)
from test_grader_friction import add

ROOT = EXAMPLE.parents[1] if (EXAMPLE.parents[1] / "config").is_dir() else EXAMPLE.parent


def warnings(repo, rel):
    return js("report", "check", rel, cwd=repo, code=5)["result"]["warnings"]


def test_a_cut_quote_is_listed_until_it_is_cited_again(repo, rel, code):
    fid = add(repo, rel, code, "--cite", "m.py:1-6")
    ev = next(f for f in load(repo, rel)["findings"] if f["id"] == fid)["evidence"][0]
    assert (ev["lines"], ev["cut_from"]) == ("1-3", "1-6")
    assert any(w.startswith(f"finding {fid}: its quote from m.py kept lines 1-3 of the 1-6 you cited") for w in warnings(repo, rel))
    cli("report", "finding", "update", rel, fid, "--cite", "m.py:1-3", "--replace-evidence", "--repo", code, cwd=repo)
    assert not any("you cited" in w for w in warnings(repo, rel)), "the same lines, cited again, are the grader's choice"


def test_a_command_run_twice_keeps_both_outputs(repo, rel, code, tmp_path):
    for n, text in enumerate(("ModuleNotFoundError: No module named 'pytz'\n", "next run at 07:20:30\n"), 1):
        (tmp_path / f"{n}.txt").write_text(text)
        cli("report", "ran", rel, "--command", "python quickstart.py", "--exit-code", "0", "--summary", "s",
            "--output", tmp_path / f"{n}.txt", cwd=repo)
    second = add(repo, rel, code, "--command", "@2", "--excerpt", "next run at 07:20:30")
    first = add(repo, rel, code, "--command", "python quickstart.py", "--excerpt", "ModuleNotFoundError: No module named 'pytz'")
    assert not any(w.startswith((second + ":", first + ":")) for w in warnings(repo, rel))
    cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor",
        "--command", "@1", "--excerpt", "next run at 07:20:30", cwd=repo, code=1)   # @1 is the first run, which didn't print it


def test_renaming_a_command_leaves_its_twins_evidence_alone(repo, rel, code, tmp_path):
    for n, text in enumerate(("1 failed\n", "3 passed\n"), 1):
        (tmp_path / f"{n}.txt").write_text(text)
        cli("report", "ran", rel, "--command", "pytest -q", "--exit-code", "0", "--summary", "s", "--output", tmp_path / f"{n}.txt", cwd=repo)
    a = add(repo, rel, code, "--command", "@1", "--excerpt", "1 failed")
    b = add(repo, rel, code, "--command", "@2", "--excerpt", "3 passed")
    out = cli("report", "update", rel, "command/2", "--command-text", "pytest -q -p no:randomly", cwd=repo).stdout
    assert "1 evidence item still quote the old text" in out
    by_id = {f["id"]: f["evidence"][0]["command"] for f in load(repo, rel)["findings"]}
    assert by_id == {a: "pytest -q", b: "pytest -q -p no:randomly"}


def test_color_codes_dont_count_in_excerpts(repo, rel, code, tmp_path):
    (tmp_path / "out.txt").write_text("Checking dist/x.whl: \x1b[32mPASSED\x1b[0m\n")
    cli("report", "ran", rel, "--command", "twine check dist/*", "--exit-code", "0", "--summary", "s", "--output", tmp_path / "out.txt", cwd=repo)
    fid = add(repo, rel, code, "--command", "@1", "--excerpt", "Checking dist/x.whl: PASSED")
    assert not any(w.startswith(fid + ":") for w in warnings(repo, rel))


def test_an_action_never_ranks_above_an_earlier_one_on_its_benchmark(gk):
    cfg = gk.resolve_config([str(EXAMPLE / PROJ / "project.toml")])
    r = json.loads((EXAMPLE / PROJ / "reports" / "2026-11-07-a1b2c3d" / "report.json").read_text())
    b = bench(r, "C4")
    b["score"] = 4
    b["path_to_target"] = [   # the slow first step makes the quick second one possible
        {"id": "C4-act-1", "action": "a", "resolves": [], "expected_new_score": 5, "effort": "L", "requires_human_decision": False},
        {"id": "C4-act-2", "action": "b", "resolves": [], "expected_new_score": 8, "effort": "S", "requires_human_decision": False}]
    roll = gk.compute_rollup(r, cfg)
    order = [p["action_id"] for p in roll["priorities"]]
    one, two = order.index("C4-act-1"), order.index("C4-act-2")
    assert two == one + 1, order
    p = {p["action_id"]: p for p in roll["priorities"]}
    assert p["C4-act-1"]["priority"] < p["C4-act-2"]["priority"], "each keeps its own priority; only the order changes"
    why = {t["action_id"]: t.get("why_first", "") for t in gk.derived_top_priorities(r, roll)}
    if "C4-act-2" in why:
        assert why["C4-act-2"].endswith(", after C4-act-1")


def test_doctor_names_the_credentials_it_sees(gk):
    env = {"GH_TOKEN": "x", "AWS_SECRET_ACCESS_KEY": "y", "OPENAI_API_KEY": "z", "EMPTY_TOKEN": "", "MAX_THINKING_TOKENS": "9", "PATH": "/bin"}
    assert gk.credential_vars(env) == ["AWS_SECRET_ACCESS_KEY", "GH_TOKEN", "OPENAI_API_KEY"]


def test_a_planned_10_says_what_it_still_needs(repo, rel):
    out = cli("report", "action", rel, "B1", "--action", "x", "--new-score", "10", "--effort", "S", cwd=repo).stdout
    assert "a 10 needs strengths and enforcement, and B1 has none recorded" in out and "expect 8" in out
    out = cli("report", "action", rel, "B2", "--action", "x", "--new-score", "8", "--effort", "S", cwd=repo).stdout
    assert "needs" not in out


def test_limitations_are_shown_numbered(repo, rel):
    for text in ("no network", "no GPU"):
        cli("report", "set", rel, "limitations", text, "--append", cwd=repo)
    out = cli("report", "show", rel, "limitations", cwd=repo).stdout
    assert "1. no network" in out and "2. no GPU" in out


def test_a_report_never_carries_a_local_path_to_its_config(repo, rel):
    source = load(repo, rel)["config"]["source"]
    assert source and not source.startswith("/") and "tmp" not in source


def test_kit_text_agrees_with_the_rubric(gk):
    src = ROOT
    base = re.search(r"\[weights\.base\](.*?)\n\[", (src / "config" / "defaults.toml").read_text(), re.S).group(1)
    named = dict(re.findall(r"^([A-Z]\d+)\s*=\s*\d+\s*#\s*(.+?)\s*$", base, re.M))
    assert named and all(gk.RUBRIC.names[b] == n for b, n in named.items()), named
    versions = set(re.findall(r'"scoring_version": "([\d.]+)"', (src / "prompts" / "grader.md").read_text()))
    assert versions == {gk.load_catalog()["suite_version"]}
    assert (src / "rubric" / "weights.md").read_text().count("**Bold** = gate for that preset.") == 1
    assert "35" not in (src / "GLOSSARY.md").read_text().split("Benchmark", 1)[-1][:200]


def test_running_the_kit_leaves_its_folders_as_copied(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    kit = tmp_path / "kit"
    shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns("__pycache__", "calibration", "examples", "bundle"))
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")}
    subprocess.run([sys.executable, str(kit / "tools" / "gradekit.py"), "presets"], env=env, check=True, capture_output=True)
    assert not list(kit.rglob("__pycache__"))


def test_a_command_only_a_withheld_finding_cites_is_withheld_too(gk):
    forged = "curl -H 'Authorization: Token eyJhbGciOi.forged' localhost:8080/api/user"
    report = {"findings": [
        {"id": "A2-001", "benchmark_id": "A2", "severity": "critical", "title": "Tokens can be forged", "sensitive": True,
         "evidence": [{"type": "command", "command": forged, "excerpt": "200 OK"}]},
        {"id": "A1-001", "benchmark_id": "A1", "severity": "minor", "title": "t",
         "evidence": [{"type": "command", "command": "go test ./...", "excerpt": "FAIL"}]}],
        "benchmarks": [], "commands_run": [{"command": forged, "exit_code": 0, "summary": "a forged token is accepted"},
                                           {"command": "go test ./...", "exit_code": 1, "summary": "1 failed"}]}
    public, _ = gk.redact_report(report)
    assert [c["command"] for c in public["commands_run"]] == ["(withheld: only a withheld finding cites it)", "go test ./..."]
    assert public["commands_run"][0]["summary"] == "[redacted]" and "forged" not in json.dumps(public["commands_run"])


def test_gaming_flags_can_be_cleared(repo, rel):
    cli("report", "score", rel, "B6", "--score", "5", "--confidence", "medium", "--rationale", "r", "--gaming-flag", "a", "--gaming-flag", "a again", cwd=repo)
    cli("report", "score", rel, "B6", "--score", "5", "--confidence", "medium", "--rationale", "r", "--clear-gaming-flags", "--gaming-flag", "a", cwd=repo)
    assert bench(load(repo, rel), "B6")["gaming_flags"] == ["a"]
