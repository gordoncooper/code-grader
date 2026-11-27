"""guard: what an improver's checks may change, and whether they did."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .common import die, emit, git_out, load_json, load_report, write_json


# The improver's proof that nothing got worse. `guard snapshot` runs the code's own checks (tests,
# linters, type checker, build) and counts suppressions and skipped tests; `guard compare` runs the
# very same commands again and lists what got worse. It never judges quality: the next grade does.

GUARD_VERSION = 1
GUARD_TIMEOUT = 1800
GUARD_TAIL_LINES = 40

# How a command from a report's commands_run is recognised. First match wins; anything else
# (git log, cloc, ls…) isn't a check and is left out.
GUARD_KIND_PATTERNS = [
    ("types", r"\b(mypy|pyright|pytype|tsc|flow check|(npm|yarn|pnpm)( run)? (typecheck|type-check|types))\b"),
    ("lint", r"\b(ruff|flake8|pylint|eslint|biome|golangci-lint|go vet|cargo clippy|clippy|rubocop|shellcheck|stylelint|standardrb"
             r"|prettier (--check|-c)|black --check|isort (--check|-c)|gofmt|cargo fmt|(npm|yarn|pnpm)( run)? lint)\b"),
    ("audit", r"\b(pip-audit|(npm|yarn|pnpm) audit|cargo audit|govulncheck|safety check|bundle audit|osv-scanner)\b"),
    ("coverage", r"\b(coverage (report|xml|json)|go tool cover)\b"),
    ("tests", r"\b(pytest|unittest|nose2?|tox|nox|jest|vitest|mocha|ava|go test|cargo test|rspec|phpunit|dotnet test|ctest"
              r"|bun test|deno test|coverage run|(npm|yarn|pnpm)( run)? test|make (test|check)"
              r"|mvnw?\b.*\b(test|verify)|gradlew?\b.*\b(test|check))\b"),
    ("build", r"\b((npm|yarn|pnpm) run build|cargo build|go build|mvnw?\b.*\b(package|compile|install)|gradlew?\b.*\bbuild"
              r"|python3? -m build|dotnet build|cmake --build)\b"),
]

# From a report, guard runs a command only if it's one plain check command that stays inside the checkout. A report is
# a grader's output, and graders read code they don't trust (prompt injection), while improvers hold push access: a
# report mustn't choose what runs here. So: no shell syntax, quotes, globs or URLs; no absolute paths or `..`; and the
# program is the check tool itself, run directly or through a runner (python -m, npx, uv run…). Anything else is
# listed and left out, and `--check NAME=COMMAND` runs it on purpose.
GUARD_NOT_PLAIN = re.compile(r"[;&|`$<>#\\(){}\[\]*?!~'\"\n\r]|://")
GUARD_RUNNERS = (("python3", "-m"), ("python", "-m"), ("py", "-m"), ("npx",), ("bunx",), ("pnpm", "exec"), ("yarn", "exec"),
                 ("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("hatch", "run"), ("pdm", "run"), ("rye", "run"),
                 ("bundle", "exec"), ("env",))
GUARD_ENV_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")


def guard_plain_kind(command: str) -> str | None:
    """The kind of check a command from a report is, if guard may run it as it stands; None if it isn't one plain check."""
    if not command or GUARD_NOT_PLAIN.search(command):
        return None
    words = command.split()
    for w in words:   # paths stay inside the checkout and out of .git, and so do flags' values
        value = w.split("=", 1)[1] if "=" in w else w
        if value.startswith("/") or ".." in value.split("/") or ".git" in value.split("/"):
            return None
        if w.split("=", 1)[0] in GUARD_WRITE_FLAGS:
            return None
    forms = []
    while words:
        while words and GUARD_ENV_WORD.fullmatch(words[0]):
            words = words[1:]
        if not words:
            break
        forms.append([words[0][2:] if words[0].startswith("./") else words[0]] + words[1:])
        runner = next((r for r in GUARD_RUNNERS if tuple(words[:len(r)]) == r), None)
        if runner is None:
            break
        words = words[len(runner):]
    for form in forms:
        text = " ".join(form)
        for kind, pat in GUARD_KIND_PATTERNS:
            m = re.match(pat, text)
            if m and m.group(0).split()[0] == form[0]:   # the program is the tool, not a name that starts like one
                return kind if guard_build_goals_ok(form) else None
    return None


# Build tools run whatever goals, targets or sessions they're given (exec:java, deploy, `make release`, a tox env
# that publishes…), so a report's command may name only these, plus flags and the values of the flags listed. Flags
# that write or delete files (pytest deletes its --basetemp) aren't taken from a report at all.
GUARD_WRITE_FLAGS = {"--basetemp", "--junitxml", "--junit-xml", "--report-log", "--resultlog", "--output", "--output-file",
                     "--outfile", "--out", "--log-file"}
GUARD_TEST_ENVS = r"(py[0-9.]*|pypy[0-9.]*|tests?|unit|lint|ruff|flake8|mypy|types?|typing|coverage|cov)"
GUARD_BUILD_GOALS = {"mvn": {"clean", "validate", "compile", "test-compile", "test", "package", "verify", "integration-test"},
                     "gradle": {"clean", "test", "check", "build", "assemble", "compileJava", "compileTestJava"},
                     "make": {"test", "check", "tests"}, "cmake": set(), "tox": set(), "nox": set(), "coverage": None}
GUARD_BUILD_VALUE_FLAGS = {"mvn": {"-pl", "--projects", "-P", "--activate-profiles", "-T", "--threads", "-rf", "--resume-from"},
                           "gradle": {"-p", "--project-dir", "-x", "--exclude-task"}, "make": {"-j", "--jobs"},
                           "cmake": {"--build", "-j", "--parallel", "--config"}, "tox": {"-e", "--parallel", "-p"},
                           "nox": {"-s", "--session", "--sessions", "-p", "--python"}, "coverage": set()}


def guard_build_goals_ok(form: list[str]) -> bool:
    tool = {"mvn": "mvn", "mvnw": "mvn", "gradle": "gradle", "gradlew": "gradle", "make": "make", "cmake": "cmake",
            "tox": "tox", "nox": "nox", "coverage": "coverage"}.get(form[0])
    if tool is None:
        return True
    words, i = form[1:], 0
    while i < len(words):
        w = words[i]
        if tool == "coverage" and (w == "-o" or w.startswith("-o")):   # writes its report wherever -o says
            return False
        if tool in ("tox", "nox") and w in ("-e", "-s", "--session", "--sessions") and i + 1 < len(words):
            if not all(re.fullmatch(GUARD_TEST_ENVS, e) for e in words[i + 1].split(",")):
                return False   # a tox env or nox session that isn't a test, lint or type run could publish or deploy
        if tool == "cmake" and w in ("--target", "-t"):
            return False
        if w.startswith("-"):
            i += 2 if w in GUARD_BUILD_VALUE_FLAGS[tool] else 1
            continue
        if tool == "coverage":
            i += 1
            continue
        if "=" in w or w not in GUARD_BUILD_GOALS[tool]:   # make VAR=value changes what a target runs
            return False
        i += 1
    return True

# Markers a change can add to make a check quieter without making the code better. Counted per line.
GUARD_MARKERS = {
    "suppressions": [
        r"#\s*noqa\b", r"#\s*type:\s*ignore", r"#\s*pragma:\s*no\s*cover", r"#\s*pylint:\s*disable", r"#\s*pyright:\s*ignore",
        r"#\s*nosec\b", r"eslint-disable", r"@ts-ignore", r"@ts-expect-error", r"@ts-nocheck", r"\bnolint\b", r"\bNOLINT",
        r"#!?\[allow\(", r"@SuppressWarnings", r"NOSONAR", r"rubocop:disable", r"istanbul ignore", r"c8 ignore",
        r"@phpstan-ignore", r"@psalm-suppress", r"swiftlint:disable", r"biome-ignore", r"prettier-ignore",
    ],
    "skipped_tests": [
        r"@pytest\.mark\.(skip|skipif|xfail)\b", r"\bpytest\.(skip|xfail)\(", r"@unittest\.(skip|skipIf|skipUnless|expectedFailure)\b",
        r"\b(it|test|describe|context)\.(skip|todo)\(", r"\bx(it|describe|test|context)\(", r"\bt\.Skip(f|Now)?\(",
        r"#\[ignore\]", r"@Disabled\b", r"@Ignore\b", r"\bskip\s*:\s*true\b",
    ],
}
GUARD_MARKER_RE = {k: re.compile("|".join(v)) for k, v in GUARD_MARKERS.items()}

# Files that configure a gate: CI, lint, type-check, coverage and test settings. A change to one is listed
# for review (adding a check is fine; weakening one never is). Matched on the file name, at any depth.
GUARD_GATE_FILES = (
    "*.gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "bitbucket-pipelines.yml", ".pre-commit-config.yaml",
    "pyproject.toml", "setup.cfg", "tox.ini", "noxfile.py", ".coveragerc", "pytest.ini", "mypy.ini", ".mypy.ini",
    "pyrightconfig.json", "ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", "pylintrc", "package.json", ".eslintrc*",
    "eslint.config.*", "tsconfig*.json", "jest.config.*", "vitest.config.*", "biome.json", "biome.jsonc", ".golangci.y*ml",
    "clippy.toml", ".clippy.toml", "Cargo.toml", "codecov.yml", ".codecov.yml", "sonar-project.properties", "CODEOWNERS",
    "Makefile", ".rubocop.yml", "phpunit.xml*", "phpstan.neon*",
)
GUARD_GATE_DIRS = (".github/workflows", ".gitlab/ci", ".circleci", ".buildkite")
GUARD_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".nox", "dist", "build", "target",
                   ".mypy_cache", ".pytest_cache", ".ruff_cache", "vendor", ".next", "coverage", "htmlcov"}

# Direction of each count: which way is better.
GUARD_HIGHER = ("passed", "packages_ok", "coverage_pct", "pylint_score")
GUARD_LOWER = ("failed", "errors", "skipped", "xfailed", "pending", "problems", "warnings", "diagnostics", "packages_failed",
               "vulnerabilities")
GUARD_COUNT_ORDER = ("passed", "failed", "errors", "skipped", "xfailed", "pending", "packages_ok", "packages_failed",
                     "problems", "warnings", "vulnerabilities", "diagnostics", "coverage_pct", "pylint_score")
GUARD_LABEL = {"passed": "passed", "failed": "failed", "errors": "errors", "skipped": "skipped", "xfailed": "xfailed",
               "pending": "pending", "packages_ok": "packages ok", "packages_failed": "packages failed",
               "problems": "problems", "warnings": "warnings", "vulnerabilities": "vulnerabilities", "diagnostics": "diagnostic lines",
               "coverage_pct": "coverage %", "pylint_score": "pylint score"}

GUARD_SCORES = ("coverage_pct", "pylint_score")
_TESTS = {"passed", "failed", "errors", "skipped", "xfailed", "pending", "packages_ok", "packages_failed"}
_LINT = {"problems", "warnings"}
GUARD_FAMILY = {**{k: _TESTS for k in _TESTS}, **{k: _LINT for k in _LINT}, "diagnostics": {"diagnostics"},
                "vulnerabilities": {"vulnerabilities"}}


def guard_count_text(k: str, v) -> str:
    if k == "coverage_pct":
        return f"coverage {v:g}%"
    if k == "pylint_score":
        return f"pylint {v:g}/10"
    label = GUARD_LABEL[k]
    if v == 1:
        label = {"errors": "error", "problems": "problem", "warnings": "warning", "vulnerabilities": "vulnerability",
                 "diagnostic lines": "diagnostic line",
                 "packages ok": "package ok", "packages failed": "package failed"}.get(label, label)
    return f"{v:g} {label}" if isinstance(v, float) else f"{v} {label}"


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


GUARD_INSTALL_RE = re.compile(r"\b(pip3?|python3? -m pip|uv pip|npm|yarn|pnpm|bun|gem|bundle|cargo|go|apt(-get)?|brew|conda|poetry)"
                              r"\s+(install|add|ci|get|sync)\b")


def guard_trim_note(command: str) -> str:
    """Graders often note something after a command: `pytest -q  (venv without pytz)`. A `(…)` straight after a word
    isn't valid shell, so it's a note, not part of the command. After `&&`, `|` or `;` it's a subshell, and stays."""
    m = re.search(r"\s+\([^()]*\)\s*$", command)
    if m and not re.search(r"(&&|\|\||[|;&])\s*$", command[:m.start()]):
        return command[:m.start()].rstrip()
    return command


def guard_kind(command: str) -> str | None:
    for kind, pat in GUARD_KIND_PATTERNS:
        if re.search(pat, command):
            return kind
    return None


def guard_counts(output: str) -> dict:
    """Numbers a check's output reports, read from the summary lines of common tools. Unknown tools give {}
    (only the exit code is compared), except that file:line diagnostics are counted."""
    text = ANSI_RE.sub("", output).replace("\r", "")
    c: dict = {}

    def add(key, n):
        c[key] = c.get(key, 0) + int(n)

    def pairs(s, mapping):
        for n, w in re.findall(r"(\d+) (\w+)", s):
            key = mapping.get(w.lower())
            if key:
                add(key, n)

    # pytest: "3 failed, 41 passed, 2 skipped in 1.20s" (with or without ===)
    py = re.findall(r"^=*\s*((?:\d+ [a-z]+,? ?)+) in [\d.]+s\b.*$", text, re.M)
    if py and re.search(r"\d+ (passed|failed|error|errors|skipped|deselected|xfailed|xpassed|warnings?)\b", py[-1]):
        pairs(py[-1], {"passed": "passed", "failed": "failed", "error": "errors", "errors": "errors", "skipped": "skipped",
                       "xfailed": "xfailed", "warning": "warnings", "warnings": "warnings"})
    # unittest: "Ran 12 tests in 0.1s" … "FAILED (failures=1, errors=2, skipped=3)" / "OK (skipped=1)"
    ran = re.findall(r"^Ran (\d+) tests? in ", text, re.M)
    if ran and not py:
        total = int(ran[-1])
        st = re.findall(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", text, re.M)
        detail = dict((k.strip(), int(v)) for k, v in re.findall(r"([\w ]+)=(\d+)", st[-1][1] if st else ""))
        failed, errors, skipped = detail.get("failures", 0), detail.get("errors", 0), detail.get("skipped", 0)
        xf = detail.get("expected failures", 0)
        add("passed", max(0, total - failed - errors - skipped - xf))
        add("failed", failed), add("errors", errors), add("skipped", skipped)
        if xf:
            add("xfailed", xf)
    # jest: "Tests:       1 failed, 2 skipped, 40 passed, 43 total"
    for line in re.findall(r"^Tests:\s+(.*\d+ total)\s*$", text, re.M)[-1:]:
        pairs(line, {"passed": "passed", "failed": "failed", "skipped": "skipped", "todo": "skipped"})
    # vitest: " Tests  1 failed | 40 passed | 2 skipped (43)"
    for line in re.findall(r"^\s*Tests\s+(\d+ \w+(?: \| \d+ \w+)*) \(\d+\)\s*$", text, re.M)[-1:]:
        pairs(line, {"passed": "passed", "failed": "failed", "skipped": "skipped", "todo": "skipped"})
    # mocha: "  40 passing (12ms)", "  1 failing", "  2 pending"
    for word, key in (("passing", "passed"), ("failing", "failed"), ("pending", "pending")):
        m = re.findall(rf"^\s*(\d+) {word}\b", text, re.M)
        if m:
            add(key, m[-1])
    # go test: "--- FAIL: TestX", "ok  	pkg	0.1s", "FAIL	pkg	0.2s"
    if re.search(r"^(ok|FAIL|---) ", text, re.M) and re.search(r"^(ok|FAIL)\s+\S+\s+(\d|\[)", text, re.M):
        add("packages_ok", len(re.findall(r"^ok\s+\S+\s", text, re.M)))
        add("packages_failed", len(re.findall(r"^FAIL\s+\S+\s+(\d|\[)", text, re.M)))
        add("failed", len(re.findall(r"^\s*--- FAIL: ", text, re.M)))
        if re.search(r"^\s*--- PASS: ", text, re.M):
            add("passed", len(re.findall(r"^\s*--- PASS: ", text, re.M)))
        if re.search(r"^\s*--- SKIP: ", text, re.M):
            add("skipped", len(re.findall(r"^\s*--- SKIP: ", text, re.M)))
    # cargo test: "test result: ok. 12 passed; 0 failed; 1 ignored; …" (one per test binary)
    for p_, f_, i_ in re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text):
        add("passed", p_), add("failed", f_), add("skipped", i_)
    # rspec: "43 examples, 1 failure, 2 pending"
    for line in re.findall(r"^(\d+ examples?, \d+ failures?(?:, \d+ pending)?)", text, re.M)[-1:]:
        n = [int(x) for x in re.findall(r"\d+", line)]
        add("passed", n[0] - n[1] - (n[2] if len(n) > 2 else 0)), add("failed", n[1])
        if len(n) > 2:
            add("pending", n[2])
    # ruff / mypy / tsc: "Found 3 errors." ; clean runs say so
    found = re.findall(r"^Found (\d+) errors?\b", text, re.M)
    if found:
        add("problems", found[-1])
    elif re.search(r"^(All checks passed!|Success: no issues found)", text, re.M):
        add("problems", 0)
    # eslint: "✖ 5 problems (3 errors, 2 warnings)"
    es = re.findall(r"✖ (\d+) problems? \((\d+) errors?, (\d+) warnings?\)", text)
    if es:
        add("problems", es[-1][0]), add("warnings", es[-1][2])
    # black --check: "3 files would be reformatted, 1 file would be left unchanged."
    bl = re.findall(r"^(?:Oh no!.*\n)?(\d+) files? would be reformatted", text, re.M)
    if bl:
        add("problems", bl[-1])
    elif re.search(r"^\d+ files? would be left unchanged\.$", text, re.M):
        add("problems", 0)
    # pip-audit: "Found 5 known vulnerabilities in 1 package" / "No known vulnerabilities found";
    # npm audit: "found 3 vulnerabilities" / "3 vulnerabilities (1 low, 2 high)"
    va = re.findall(r"Found (\d+) known vulnerabilit(?:y|ies)", text) or re.findall(r"^(?:found )?(\d+) vulnerabilit(?:y|ies)\b", text, re.M | re.I)
    if va:
        add("vulnerabilities", va[-1])
    elif re.search(r"No known vulnerabilities found|found 0 vulnerabilities", text):
        add("vulnerabilities", 0)
    # pylint: "Your code has been rated at 9.12/10"
    pl = re.findall(r"rated at (-?[\d.]+)/10", text)
    if pl:
        c["pylint_score"] = float(pl[-1])
    # coverage: coverage.py / pytest-cov TOTAL row, istanbul's "All files", go tool cover, tarpaulin
    cov = (re.findall(r"^TOTAL\s.*?(\d+(?:\.\d+)?)%\s*$", text, re.M) or re.findall(r"^All files\s*\|\s*([\d.]+)", text, re.M)
           or re.findall(r"^total:\s+\(statements\)\s+([\d.]+)%", text, re.M) or re.findall(r"([\d.]+)% coverage, \d+/\d+ lines", text))
    if cov:
        c["coverage_pct"] = float(cov[-1])
    if not c:
        diags = re.findall(r"^[^\s:][^:\n]*:\d+(?::\d+)?:\s|^\S+\(\d+,\d+\): (?:error|warning)", text, re.M)
        if diags:
            c["diagnostics"] = len(diags)
    return c


def guard_git_dir(code: Path) -> Path | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(code), "rev-parse", "--absolute-git-dir"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def guard_default(code: Path, name: str) -> Path | None:
    """Inside .git/, so a snapshot can never be committed by accident and compare finds it by itself."""
    g = guard_git_dir(code)
    return g / "gradekit" / name if g else None


def guard_files(code: Path, sub: str) -> list[str]:
    """The code's files (tracked and new, not ignored), relative to the code folder, limited to SUB."""
    import subprocess
    base = code / sub if sub else code
    files = None
    if guard_git_dir(code):
        try:
            r = subprocess.run(["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z", "--full-name", "."],
                               capture_output=True, timeout=120)
            if r.returncode == 0:
                top = git_out(code, "rev-parse", "--show-toplevel")
                rel_code = Path(code).resolve().relative_to(Path(top).resolve()).as_posix() if top else "."
                files = []
                for f in r.stdout.decode("utf-8", "replace").split("\0"):
                    if not f:
                        continue
                    if rel_code not in ("", "."):
                        if not f.startswith(rel_code + "/"):
                            continue
                        f = f[len(rel_code) + 1:]
                    if (code / f).is_file():
                        files.append(f)
        except (OSError, subprocess.SubprocessError, ValueError):
            files = None
    if files is None:
        files = []
        for root, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in GUARD_SKIP_DIRS)
            for n in sorted(names):
                files.append((Path(root) / n).relative_to(code).as_posix())
    return sorted(files)


def guard_is_gate_file(rel: str) -> bool:
    import fnmatch
    if any(rel == d or rel.startswith(d + "/") or f"/{d}/" in f"/{rel}" for d in GUARD_GATE_DIRS):
        return True
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, pat) for pat in GUARD_GATE_FILES)


def guard_scan(code: Path, sub: str) -> tuple[dict, dict]:
    markers = {k: {"total": 0, "files": {}} for k in GUARD_MARKERS}
    gates = {}
    for rel in guard_files(code, sub):
        p = code / rel
        try:
            if p.stat().st_size > 2_000_000:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if guard_is_gate_file(rel):
            gates[rel] = hashlib.sha256(data).hexdigest()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        for key, rx in GUARD_MARKER_RE.items():
            n = sum(1 for line in text.splitlines() if rx.search(line))
            if n:
                markers[key]["files"][rel] = n
                markers[key]["total"] += n
    return markers, gates


def guard_detect(code: Path) -> list[dict]:
    """A small fallback when no checks were given: the usual test and lint entry points the repo declares."""
    out = []

    def has(*names):
        return any((code / n).exists() for n in names)

    pyproject = (code / "pyproject.toml").read_text(encoding="utf-8", errors="replace") if has("pyproject.toml") else ""
    if has("pytest.ini", "conftest.py", "tox.ini") or "[tool.pytest" in pyproject or (has("tests", "test") and (pyproject or has("setup.py", "setup.cfg"))):
        out.append({"name": "tests", "command": ("python" if os.name == "nt" else "python3") + " -m pytest -q"})
    if has("ruff.toml", ".ruff.toml") or "[tool.ruff" in pyproject:
        out.append({"name": "lint", "command": "ruff check ."})
    if has("package.json"):
        try:
            scripts = (json.loads((code / "package.json").read_text(encoding="utf-8")) or {}).get("scripts") or {}
        except (json.JSONDecodeError, OSError):
            scripts = {}
        for script, name in (("test", "tests"), ("lint", "lint"), ("typecheck", "types"), ("build", "build")):
            if script in scripts and "no test specified" not in str(scripts[script]):
                out.append({"name": name, "command": "npm test --silent" if script == "test" else f"npm run --silent {script}"})
    if has("go.mod"):
        out += [{"name": "tests", "command": "go test ./..."}, {"name": "lint", "command": "go vet ./..."}]
    if has("Cargo.toml"):
        out += [{"name": "tests", "command": "cargo test"}, {"name": "build", "command": "cargo build"}]
    return out


def guard_plan(args, code: Path) -> tuple[list[dict], list[str]]:
    """The checks to run, named, with where each one came from."""
    checks, notes = [], []
    for spec in args.check or []:
        name, sep, cmd = spec.partition("=")
        if not sep or not name.strip() or not cmd.strip():
            die(f"--check takes NAME=COMMAND, e.g. tests=\"pytest -q\"; got '{spec}'")
        checks.append({"name": name.strip(), "command": cmd.strip(), "from": "--check"})
    if args.from_report:
        rep = load_report(args.from_report)
        skipped, installs, trimmed, not_plain = [], [], [], []
        for entry in rep.get("commands_run") or []:
            raw = str(entry.get("command") or "").strip()
            cmd = guard_trim_note(raw)
            if cmd != raw:
                trimmed.append(raw[len(cmd):].strip())
            kind = guard_kind(cmd) if cmd else None
            if kind and GUARD_INSTALL_RE.search(cmd):
                installs.append(cmd)
            elif kind and guard_plain_kind(cmd):
                checks.append({"name": guard_plain_kind(cmd), "command": cmd, "from": "report"})
            elif kind:
                not_plain.append(cmd)
            elif cmd:
                skipped.append(cmd)
        if trimmed:
            notes.append(f"dropped the grader's notes after {len(trimmed)} command(s), which aren't part of the command: {'; '.join(trimmed[:3])}")
        if installs:
            notes.append(f"left out {len(installs)} command(s) that install packages (the guard never installs anything): "
                         f"{'; '.join(installs[:3])}")
        if not_plain:
            notes.append(f"left out {len(not_plain)} command(s) that aren't one plain check command (shell syntax, quotes, a URL, a path "
                         f"outside the checkout, or a program other than the check tool), because a report mustn't choose what runs "
                         f"here: {'; '.join(not_plain[:3])}{' …' if len(not_plain) > 3 else ''}. To run one, give it with --check NAME=COMMAND")
        if skipped:
            notes.append(f"left out {len(skipped)} command(s) from the report that aren't tests, lint, types, coverage, build "
                         f"or audit: {'; '.join(skipped[:5])}{' …' if len(skipped) > 5 else ''}")
    if not checks:
        checks = [{**c, "from": "detected"} for c in guard_detect(code / (args.path or ""))]
        if checks:
            notes.append("no checks given, so these were detected from the repo; give --check NAME=COMMAND "
                         "(or --from-report) to choose them")
    seen, plan, used = set(), [], {}
    for c in checks:
        if c["command"] in seen:
            continue
        seen.add(c["command"])
        base = re.sub(r"[^\w.-]+", "-", c["name"]).strip("-") or "check"
        used[base] = used.get(base, 0) + 1
        plan.append({**c, "name": base if used[base] == 1 else f"{base}-{used[base]}", "kind": guard_kind(c["command"])})
    if not plan:
        die("no checks to run: give --check NAME=COMMAND (repeatable), e.g. --check tests=\"pytest -q\" --check lint=\"ruff check .\", "
            "or --from-report REPORT to use the commands the grader ran")
    return plan, notes


def guard_run(command: str, cwd: Path, timeout: int) -> dict:
    import subprocess
    import time
    env = dict(os.environ, CI=os.environ.get("CI", "true"), NO_COLOR="1", FORCE_COLOR="0", TERM="dumb", PYTHONDONTWRITEBYTECODE="1")
    t0 = time.monotonic()
    timed_out, code, output = False, None, ""
    try:
        r = subprocess.run(command, shell=True, cwd=str(cwd), env=env, capture_output=True, timeout=timeout)
        code, output = r.returncode, (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = ((exc.stdout or b"") + b"\n" + (exc.stderr or b"")).decode("utf-8", "replace")
    except OSError as exc:
        output = str(exc)
    output = ANSI_RE.sub("", output)
    lines = [ln for ln in output.rstrip().splitlines()]
    return {"exit_code": code, "timed_out": timed_out, "seconds": round(time.monotonic() - t0, 1),
            "counts": guard_counts(output), "output_tail": "\n".join(lines[-GUARD_TAIL_LINES:])[-6000:],
            "output_sha256": hashlib.sha256(output.encode()).hexdigest()}


def guard_take(code: Path, plan: list[dict], sub: str, timeout: int, say=print) -> dict:
    import datetime
    import platform
    cwd = code / sub if sub else code
    head = git_out(code, "rev-parse", "HEAD", check=False) if guard_git_dir(code) else ""
    dirty = bool(git_out(code, "status", "--porcelain", check=False)) if head else None
    checks = []
    for c in plan:
        say(f"  running {c['name']}: {c['command']}")
        res = guard_run(c["command"], cwd, timeout)
        checks.append({"name": c["name"], "kind": c.get("kind"), "command": c["command"], "from": c.get("from"), **res})
    markers, gates = guard_scan(code, sub)
    return {"guard_version": GUARD_VERSION, "taken_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code": {"commit": head or None, "dirty": dirty, "path": sub or None},
            "environment": {"python": platform.python_version(), "platform": platform.platform(terse=True)},
            "checks": checks, "markers": markers, "gate_files": gates}


def guard_state(res: dict | None) -> str:
    if res is None:
        return "not run"
    if res.get("timed_out"):
        return "timed out"
    counts = res.get("counts") or {}
    parts = [guard_count_text(k, counts[k]) for k in GUARD_COUNT_ORDER if k in counts]
    ex = res.get("exit_code")
    status = "ok" if ex == 0 else ("could not start" if ex is None else f"exit {ex}")
    return f"{', '.join(parts)} ({status})" if parts else status


def guard_check_line(res: dict) -> str:
    return f"{res['name']}: {guard_state(res)}"


def guard_diff(before: dict, after: dict, explain: dict, coverage_tolerance: float = 0.1) -> dict:
    items = []

    def item(key, kind, status, detail, b=None, a=None):
        items.append({"key": key, "kind": kind, "status": status, "detail": detail, "before": b, "after": a})

    after_by = {c["name"]: c for c in after.get("checks") or []}
    for b in before.get("checks") or []:
        name = b["name"]
        a = after_by.get(name)
        if a is None or a.get("command") != b.get("command"):
            item(name, "check", "regressed", f"{name} wasn't run after with the same command; compare must run every check the snapshot ran",
                 b.get("command"), (a or {}).get("command"))
            continue
        changed = False
        if b.get("timed_out") != a.get("timed_out"):
            changed = True
            item(f"{name}.exit", "check", "regressed" if a.get("timed_out") else "improved",
                 f"{name} {'now times out' if a.get('timed_out') else 'no longer times out'}", guard_state(b), guard_state(a))
        elif (b.get("exit_code") == 0) != (a.get("exit_code") == 0):
            changed = True
            item(f"{name}.exit", "check", "regressed" if b.get("exit_code") == 0 else "improved",
                 f"{name} {'now fails' if b.get('exit_code') == 0 else 'now passes'} (exit {b.get('exit_code')} → {a.get('exit_code')})",
                 b.get("exit_code"), a.get("exit_code"))
        bc, ac = dict(b.get("counts") or {}), dict(a.get("counts") or {})
        for k in GUARD_COUNT_ORDER:
            if k not in bc and k not in ac:
                continue
            if k not in GUARD_SCORES:   # a tool that printed a summary leaves out the zeros ("41 passed": no failures)
                for have, other in ((bc, ac), (ac, bc)):
                    if k in other and k not in have and have and GUARD_FAMILY.get(k) & set(have):
                        have[k] = 0
            if k not in bc or k not in ac:
                if k in bc and a.get("exit_code") != 0:
                    continue   # a crash that prints no summary is already the exit-code change
                changed = True
                item(f"{name}.{k}", "check", "changed", f"{name}: {GUARD_LABEL[k]} reported {'only after' if k in ac else 'only before'}",
                     bc.get(k), ac.get(k))
                continue
            bv, av = bc[k], ac[k]
            if bv == av or (k == "coverage_pct" and abs(av - bv) < coverage_tolerance):
                continue
            changed = True
            worse = (av < bv) if k in GUARD_HIGHER else (av > bv)
            item(f"{name}.{k}", "check", "regressed" if worse else "improved",
                 f"{name}: {guard_count_text(k, bv)} → {guard_count_text(k, av)}", bv, av)
        if not changed:
            item(name, "check", "same", f"{name}: {guard_state(a)}", guard_state(b), guard_state(a))
    for name, a in after_by.items():
        if name not in {b["name"] for b in before.get("checks") or []}:
            item(name, "check", "changed", f"{name} is new (not in the snapshot), so it isn't compared", None, guard_state(a))
    for key in GUARD_MARKERS:
        bm = (before.get("markers") or {}).get(key) or {"total": 0, "files": {}}
        am = (after.get("markers") or {}).get(key) or {"total": 0, "files": {}}
        label = key.replace("_", " ")
        if am["total"] == bm["total"]:
            item(key, "marker", "same", f"{label}: {am['total']}", bm["total"], am["total"])
            continue
        rose = sorted(f for f, n in am["files"].items() if n > bm["files"].get(f, 0))
        where = f" (more in {', '.join(rose[:5])}{' …' if len(rose) > 5 else ''})" if rose else ""
        item(key, "marker", "regressed" if am["total"] > bm["total"] else "improved",
             f"{label}: {bm['total']} → {am['total']}{where if am['total'] > bm['total'] else ''}", bm["total"], am["total"])
    bg, ag = before.get("gate_files") or {}, after.get("gate_files") or {}
    for f in sorted(set(bg) | set(ag)):
        if bg.get(f) != ag.get(f):
            how = "added" if f not in bg else "removed" if f not in ag else "changed"
            item(f"gate:{f}", "gate", "review", f"{f} {how}: check it adds checks and weakens none", None, how)
    used = set()
    for it in items:
        if it["status"] != "regressed":
            continue
        for k in (it["key"], it["key"].split(".")[0]):
            if k in explain:
                it["status"], it["explanation"] = "explained", explain[k]
                used.add(k)
                break
    regressions = [it["key"] for it in items if it["status"] == "regressed"]
    return {"verdict": "FAIL" if regressions else "PASS", "regressions": regressions,
            "explained": [{"key": it["key"], "reason": it["explanation"]} for it in items if it["status"] == "explained"],
            "improved": [it["key"] for it in items if it["status"] == "improved"],
            "review": [it["key"][5:] for it in items if it["status"] == "review"],
            "unused_explanations": sorted(set(explain) - used), "items": items}


def guard_text(diff: dict, before: dict, after: dict, commits: int | None) -> str:
    bc, ac = (before.get("code") or {}), (after.get("code") or {})
    span = f"{(bc.get('commit') or 'no git')[:10]} → {(ac.get('commit') or 'no git')[:10]}"
    if commits is not None:
        span += f" ({commits} commit{'s' if commits != 1 else ''}{', plus uncommitted changes' if ac.get('dirty') else ''})"
    lines = [f"guard: {len(before.get('checks') or [])} check(s), {span}"]
    mark = {"regressed": "REGRESSED", "improved": "better", "same": "same", "changed": "note", "review": "review", "explained": "explained"}
    for it in diff["items"]:
        lines.append(f"  [{mark[it['status']]}] {it['detail']}" + (f" (explained: {it['explanation']})" if it.get("explanation") else ""))
    for k in diff["unused_explanations"]:
        lines.append(f"  note: --explain {k} matched nothing that got worse")
    if diff["regressions"]:
        lines.append(f"verdict: FAIL, {len(diff['regressions'])} regression(s): {', '.join(diff['regressions'])}. "
                     "Fix or revert, or if one is deliberate, say why with --explain KEY=\"why\"")
    else:
        lines.append("verdict: PASS, nothing got worse" + (f" ({len(diff['explained'])} explained)" if diff["explained"] else ""))
    return "\n".join(lines)


def cmd_guard_snapshot(args) -> int:
    code = Path(args.code).resolve()
    if not code.is_dir():
        die(f"code folder not found: {args.code}")
    if args.path and not (code / args.path).is_dir():
        die(f"--path {args.path}: no such folder in {code}")
    plan, notes = guard_plan(args, code)
    out = Path(args.out) if args.out else guard_default(code, "guard-before.json")
    if args.list:
        emit(args, {"checks": plan, "out": str(out) if out else None, "notes": notes},
             "\n".join([f"{c['name']}: {c['command']} (from {c['from']})" for c in plan] + [f"note: {n}" for n in notes]))
        return 0
    if out is None:
        die(f"{code} isn't a git checkout, so there's no safe default place for the snapshot: give --out FILE (outside the code)")
    for n in notes:
        print(f"note: {n}")
    snap = guard_take(code, plan, args.path or "", args.timeout)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, snap)
    lines = [guard_check_line(c) for c in snap["checks"]]
    for c in snap["checks"]:
        if c["exit_code"] in (126, 127) or c["exit_code"] is None:
            lines.append(f"warning: {c['name']} couldn't run (exit {c['exit_code']}); fix the command, or the baseline is meaningless")
    lines.append("markers: " + ", ".join(f"{k.replace('_', ' ')} {v['total']}" for k, v in snap["markers"].items())
                 + f"; {len(snap['gate_files'])} gate file(s) fingerprinted")
    lines.append(f"wrote {out}" + ("" if args.out else " (inside .git, so it's never committed)"))
    if snap["code"]["dirty"]:
        lines.append("note: the working tree has uncommitted changes; the snapshot includes them")
    emit(args, {"snapshot": str(out), "checks": [{k: c[k] for k in ("name", "command", "exit_code", "timed_out", "counts")} for c in snap["checks"]],
                "markers": {k: v["total"] for k, v in snap["markers"].items()}, "gate_files": len(snap["gate_files"]), "notes": notes},
         "\n".join(lines))
    return 0


def cmd_guard_compare(args) -> int:
    code = Path(args.code).resolve()
    before_path = Path(args.before) if args.before else guard_default(code, "guard-before.json")
    if before_path is None:
        die("give --before FILE: the snapshot `guard snapshot --out` wrote")
    if not before_path.is_file():
        die(f"no snapshot at {before_path}: run `gradekit guard snapshot` before changing anything")
    before = load_json(before_path)
    if before.get("guard_version") != GUARD_VERSION:
        die(f"{before_path} isn't a guard snapshot (version {before.get('guard_version')!r})")
    explain = {}
    for spec in args.explain or []:
        key, sep, why = spec.partition("=")
        if not sep or not why.strip():
            die(f"--explain takes KEY=REASON, e.g. tests.passed=\"removed the tests of the deleted export helper\"; got '{spec}'")
        explain[key.strip()] = why.strip()
    if args.after:
        after = load_json(args.after)
    else:
        if not code.is_dir():
            die(f"code folder not found: {args.code}")
        sub = (before.get("code") or {}).get("path") or ""
        plan = [{k: c.get(k) for k in ("name", "kind", "command", "from")} for c in before.get("checks") or []]
        after = guard_take(code, plan, sub, args.timeout)
    diff = guard_diff(before, after, explain, args.coverage_tolerance)
    commits = None
    b_commit, a_commit = (before.get("code") or {}).get("commit"), (after.get("code") or {}).get("commit")
    if b_commit and a_commit and code.is_dir() and guard_git_dir(code):
        n = git_out(code, "rev-list", "--count", f"{b_commit}..{a_commit}", check=False)
        commits = int(n) if n.isdigit() else None
    result = {**diff, "commits": commits, "before": before, "after": after}
    out = Path(args.out) if args.out else guard_default(code, "guard-compare.json")
    text = guard_text(diff, before, after, commits)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, result)
        text += f"\nwrote {out} (for `render log --guard`)"
    emit(args, {k: v for k, v in result.items() if k not in ("before", "after")} | {"written": str(out) if out else None}, text)
    return 2 if diff["regressions"] else 0


def render_guard(cmp: dict) -> list[str]:
    before, after = cmp.get("before") or {}, cmp.get("after") or {}
    a_by = {c["name"]: c for c in after.get("checks") or []}
    bc, ac = before.get("code") or {}, after.get("code") or {}
    span = f"`{(bc.get('commit') or '?')[:7]}` → `{(ac.get('commit') or '?')[:7]}`"
    out = ["**Guard** (the code's own checks, run before and after with the same commands)", "",
           f"Verdict: **{cmp.get('verdict', '?')}**, {span}" + (f", {cmp['commits']} commit(s)" if cmp.get("commits") is not None else "")
           + (" plus uncommitted changes" if ac.get("dirty") else "") + ".", "",
           "| Check | Command | Before | After | Result |", "|---|---|---|---|---|"]
    status_of = {}
    for it in cmp.get("items") or []:
        if it["kind"] == "check":
            name = it["key"].split(".")[0]
            rank = {"regressed": 4, "explained": 3, "improved": 2, "changed": 1, "same": 0}
            if rank.get(it["status"], 0) >= rank.get(status_of.get(name, "same"), 0):
                status_of[name] = it["status"]
    word = {"regressed": "**worse**", "explained": "worse, explained", "improved": "better", "changed": "changed", "same": "same"}
    for b in before.get("checks") or []:
        a = a_by.get(b["name"])
        cmd = b["command"].replace("|", "\\|")
        out.append(f"| {b['name']} | `{cmd}` | {guard_state(b)} | {guard_state(a)} | {word[status_of.get(b['name'], 'same')]} |")
    mk = []
    for key in GUARD_MARKERS:
        bt = ((before.get("markers") or {}).get(key) or {}).get("total", 0)
        at = ((after.get("markers") or {}).get(key) or {}).get("total", 0)
        mk.append(f"{key.replace('_', ' ')} {bt} → {at}")
    out += ["", "Markers in the code: " + "; ".join(mk) + "."]
    if cmp.get("review"):
        out += ["", "Gate files changed, to review (a change may add checks, never weaken one): " + ", ".join(f"`{f}`" for f in cmp["review"]) + "."]
    if cmp.get("explained"):
        out += ["", "Explained:"] + [f"- `{e['key']}`: {e['reason']}" for e in cmp["explained"]]
    if cmp.get("regressions"):
        out += ["", f"**Not explained:** {', '.join(f'`{k}`' for k in cmp['regressions'])}."]
    return out


# =========================================================================== commands
# How the command line reads this module's commands. cli.build_parser adds them in order.


def add_guard(sub):
    p = sub.add_parser("guard", help="improvers: run the code's checks before changing it, then prove nothing got worse")
    gsub = p.add_subparsers(dest="guard_cmd", required=True, metavar="STEP")
    q = gsub.add_parser("snapshot", help="before any change: run the checks and record the results (in .git/, never committed)")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--check", action="append", metavar="NAME=COMMAND",
                   help='a check to run, e.g. tests="pytest -q" (repeatable; run from the code folder, or --path)')
    q.add_argument("--from-report", metavar="REPORT", help="also use the tests, lint, type-check, coverage, build and audit commands the grader ran")
    q.add_argument("--path", metavar="SUBDIR", help="only this part of the code (the project's `path`): checks run there, and only it is scanned")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write it (default: .git/gradekit/guard-before.json)")
    q.add_argument("--list", action="store_true", help="show the checks it would run, and run nothing")
    q.set_defaults(fn=cmd_guard_snapshot)
    q = gsub.add_parser("compare", help="after changing: run the same checks again; exit 2 if anything got worse")
    q.add_argument("code", nargs="?", default=".", help="the code checkout (default: here)")
    q.add_argument("--before", metavar="FILE", help="the snapshot (default: .git/gradekit/guard-before.json)")
    q.add_argument("--after", metavar="FILE", help="compare with this snapshot instead of running the checks now")
    q.add_argument("--explain", action="append", metavar="KEY=REASON",
                   help='a deliberate change, e.g. tests.passed="removed the tests of the deleted export helper" (repeatable)')
    q.add_argument("--coverage-tolerance", type=float, default=0.1, metavar="POINTS", help="coverage may move this much (default 0.1)")
    q.add_argument("--timeout", type=int, default=GUARD_TIMEOUT, metavar="SEC", help=f"per check (default {GUARD_TIMEOUT})")
    q.add_argument("--out", metavar="FILE", help="where to write the result (default: .git/gradekit/guard-compare.json)")
    q.set_defaults(fn=cmd_guard_compare)
