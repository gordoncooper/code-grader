"""What the 5.0 gate's fourth round of grader runs asked for: a note per piece of evidence, command evidence tied to
the commands recorded, limited without a score yet, no half-success when a citation fails, and a confirmation from
`report check --write`."""
import json

from test_gate_feedback import bench, cli, code, js, load, rel, repo  # noqa: F401  (fixtures)


def notes(repo, rel, fid):
    f = next(f for f in load(repo, rel)["findings"] if f["id"] == fid)
    return [e.get("note") for e in f["evidence"]]


def add(repo, rel, code, *ev):
    return js("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor", "--repo", code, *ev,
              cwd=repo)["result"]["id"]


def test_each_note_belongs_to_the_evidence_before_it(repo, rel, code):
    fid = add(repo, rel, code, "--cite", "m.py:1", "--note", "the definition", "--cite", "m.py:7", "--note", "the call")
    assert notes(repo, rel, fid) == ["the definition", "the call"]


def test_one_note_still_goes_on_every_item(repo, rel, code):
    fid = add(repo, rel, code, "--cite", "m.py:1", "--cite", "m.py:7", "--note", "both")
    assert notes(repo, rel, fid) == ["both", "both"]


def test_notes_after_all_the_evidence_pair_up_in_order(repo, rel, code):
    """This is also how MCP clients send them: every --cite, then every --note."""
    fid = add(repo, rel, code, "--cite", "m.py:1", "--cite", "m.py:7", "--note", "first", "--note", "second")
    assert notes(repo, rel, fid) == ["first", "second"]


def test_a_leading_note_fills_in_for_items_without_their_own(repo, rel, code):
    fid = add(repo, rel, code, "--note", "context", "--cite", "m.py:1", "--cite", "m.py:7", "--note", "the call",
              "--absence", "a test for f", "--method", "grep -r 'def test_f'")
    assert notes(repo, rel, fid) == ["context", "the call", "context"]


def test_two_notes_for_one_item_are_refused(repo, rel, code):
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor", "--repo", code,
            "--cite", "m.py:1", "--note", "a", "--note", "b", "--cite", "m.py:7", cwd=repo, code=1)
    assert "already has a note" in r.stderr


def test_command_evidence_can_point_at_a_recorded_command(repo, rel, code):
    cli("report", "ran", rel, "--command", "python -m pytest -q", "--exit-code", "1", "--summary", "1 failed", cwd=repo)
    fid = add(repo, rel, code, "--command", "@1", "--excerpt", "FAILED test_f - assert 4 == 5")
    ev = next(f for f in load(repo, rel)["findings"] if f["id"] == fid)["evidence"][0]
    assert ev["command"] == "python -m pytest -q"
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor",
            "--command", "@3", "--excerpt", "x", cwd=repo, code=1)
    assert "has 1 recorded command" in r.stderr


def test_check_points_out_excerpts_from_commands_never_recorded(repo, rel, code):
    fid = add(repo, rel, code, "--command", "ruff check .", "--excerpt", "m.py:2:5 F841")
    warnings = js("report", "check", rel, cwd=repo, code=5)["result"]["warnings"]
    assert any(w.startswith(f"{fid}: its excerpt is from `ruff check .`") and "--command @N" in w for w in warnings)
    cli("report", "ran", rel, "--command", "ruff check .", "--exit-code", "1", "--summary", "1 error", cwd=repo)
    assert not any("ruff check" in w for w in js("report", "check", rel, cwd=repo, code=5)["result"]["warnings"])


def test_limited_first_score_later(repo, rel):
    out = cli("report", "score", rel, "A5", "--applicability", "limited", "--reason", "keeps only a small cache", cwd=repo)
    assert "limited, not scored yet" in out.stdout
    b = bench(load(repo, rel), "A5")
    assert (b["applicability"], b["applicability_reason"], b["score"]) == ("limited", "keeps only a small cache", None)
    assert any(t.startswith("A5 ") for t in js("report", "check", rel, cwd=repo, code=5)["result"]["todo"])
    cli("report", "score", rel, "A5", "--score", "6", "--confidence", "medium", cwd=repo)
    b = bench(load(repo, rel), "A5")
    assert (b["applicability"], b["score"]) == ("limited", 6), "scoring later keeps it limited"
    assert "needs --score and --confidence" in cli("report", "score", rel, "A1", "--confidence", "high", cwd=repo, code=1).stderr


def test_a_failed_citation_echoes_nothing_and_saves_nothing(repo, rel, code):
    before = (repo / rel).read_text()
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor", "--repo", code,
            "--cite", "m.py:1", "--cite", "m.py:99", cwd=repo, code=1)
    assert "cited m.py:1" not in r.stderr and "nothing was saved" in r.stderr and "has 7 lines" in r.stderr
    assert (repo / rel).read_text() == before
    ok = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor", "--repo", code,
             "--cite", "m.py:1", cwd=repo)
    assert "cited m.py:1: def f(x):" in ok.stderr


def test_check_write_says_what_it_wrote(repo, rel):
    out = js("report", "check", rel, "--write", cwd=repo, code=5)["result"]
    assert out["wrote"] == f"wrote {rel} (tidied); the rollup isn't stored until nothing is left to do"
    assert "rollup isn't stored" in cli("report", "check", rel, "--write", cwd=repo, code=5).stdout


# --------------------------------------------------------------------------- from calibration run 13

def evidence(repo, rel, fid):
    return next(f for f in load(repo, rel)["findings"] if f["id"] == fid)["evidence"]


def test_several_command_excerpt_pairs_are_all_kept(repo, rel, code):
    cli("report", "ran", rel, "--command", "mypy --strict schedule", "--exit-code", "1", "--summary", "s", cwd=repo)
    cli("report", "ran", rel, "--command", "pyright schedule", "--exit-code", "0", "--summary", "s", cwd=repo)
    fid = add(repo, rel, code, "--command", "@1", "--excerpt", 'Revealed type is "Any"', "--note", "mypy",
              "--command", "@2", "--no-output", "--note", "pyright prints nothing for it")
    ev = evidence(repo, rel, fid)
    assert [(e["command"], e["excerpt"], e.get("note")) for e in ev] == [
        ("mypy --strict schedule", 'Revealed type is "Any"', "mypy"), ("pyright schedule", "(no output)", "pyright prints nothing for it")]


def test_unpaired_evidence_is_refused_not_dropped(repo, rel, code):
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor",
            "--command", "a", "--command", "b", "--excerpt", "x", cwd=repo, code=1)
    assert "each --command needs its own --excerpt (or --no-output)" in r.stderr and "got 2 --command and 1" in r.stderr
    r = cli("report", "finding", "add", rel, "--benchmark", "A1", "--title", "t", "--severity", "minor",
            "--cite", "m.py:1", "--repo", code, "--excerpt", "x", cwd=repo, code=1)
    assert "--excerpt goes with --command" in r.stderr
    fid = add(repo, rel, code, "--absence", "a test for f", "--method", "grep -r test_f", "--absence", "CI", "--method", "ls .github")
    assert [e["method"] for e in evidence(repo, rel, fid)] == ["grep -r test_f", "ls .github"]


def test_a_command_record_can_be_corrected_in_place(repo, rel, code):
    cli("report", "ran", rel, "--command", "pytest -q  # notes here", "--exit-code", "0", "--summary", "s", cwd=repo)
    cli("report", "ran", rel, "--command", "flake8", "--exit-code", "1", "--summary", "117", cwd=repo)
    fid = add(repo, rel, code, "--command", "@1", "--excerpt", "3 passed")
    out = cli("report", "update", rel, "command/1", "--command-text", "pytest -q", "--summary", "3 passed", cwd=repo).stdout
    assert "1 evidence item now quote the new text" in out
    r = load(repo, rel)
    assert [c["command"] for c in r["commands_run"]] == ["pytest -q", "flake8"], "the numbering stays"
    assert r["commands_run"][0]["result_summary"] == "3 passed" and evidence(repo, rel, fid)[0]["command"] == "pytest -q"


def test_excerpts_are_checked_against_the_recorded_output(repo, rel, code, tmp_path):
    out = tmp_path / "out.txt"
    out.write_text("collected 3 items\n\ntest_a.py ..F\n  FAILED test_a.py::test_f - assert 4 == 5\n3 run, 1 failed\n")
    rec = cli("report", "ran", rel, "--command", "pytest -q", "--exit-code", "1", "--summary", "1 failed", "--output", out, cwd=repo)
    assert "as command 1" in rec.stdout and "fingerprint of its 4 output lines" in rec.stdout
    r = load(repo, rel)
    assert r["commands_run"][0]["output"]["lines"] == 4 and "collected" not in json.dumps(r), "only hashes are kept"
    good = add(repo, rel, code, "--command", "@1", "--excerpt", "FAILED   test_a.py::test_f - assert 4 == 5\n...\n3 run, 1 failed")
    bad = add(repo, rel, code, "--command", "@1", "--excerpt", "test_f fails: 4 != 5")
    warnings = js("report", "check", rel, cwd=repo, code=5)["result"]["warnings"]
    assert not any(w.startswith(good + ":") for w in warnings), "whitespace evens out, and '...' elides"
    assert any(w.startswith(f"{bad}: 1 line of its excerpt") and "never from your own notes" in w for w in warnings)
