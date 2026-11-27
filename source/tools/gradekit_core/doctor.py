"""doctor: preflight checks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from .common import (
    DECISIONS_FILE, DEFAULTS_PATH, DISPOSITIONS_FILE, emit, GradekitError, load_catalog, load_json, load_toml, major,
    pin_problem, SCHEMA_PATH, SUITE_DIR, suite_pin,
)
from .config import load_config, project_dir_from_args, report_folders
from .zones import zone_for_path


# A preflight: everything a run will need, checked before an hour of grading rather than after.

def _check(name, status, detail, fix=None):
    return {"check": name, "status": status, "detail": detail, **({"fix": fix} if fix else {})}


def _run(cmd, cwd=None, timeout=30):
    import subprocess
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return None, "not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)


CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".kts", ".rb", ".php",
                 ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".m", ".mm", ".sh", ".lua", ".ex", ".exs",
                 ".erl", ".hs", ".ml", ".clj", ".dart", ".vue", ".svelte", ".sql", ".r", ".jl", ".zig", ".pl"}
HOT_SHARE_WARN = 0.5
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv", "__pycache__", ".tox"}


def is_test_path(rel: str) -> bool:
    parts = rel.lower().split("/")
    name = parts[-1]
    return (any(p in ("test", "tests", "spec", "specs", "__tests__", "testing") for p in parts[:-1])
            or name.startswith("test_") or re.search(r"(_test|_spec|\.test|\.spec)\.[a-z]+$", name) is not None)


def hot_share(repo: Path, cfg: dict) -> dict | None:
    """How much of the code (by lines, tests left out) the hot zones cover: {share, files}."""
    total, hot, files = 0, 0, []
    for f in sorted(repo.rglob("*")):
        rel = f.relative_to(repo).as_posix()
        if (f.suffix.lower() not in CODE_SUFFIXES or not f.is_file() or SKIP_DIRS.intersection(rel.split("/")[:-1])
                or is_test_path(rel)):
            continue
        try:
            n = sum(1 for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
        except OSError:
            continue
        total += n
        if zone_for_path(rel, cfg)[1] == "hot":
            hot += n
            files.append(rel)
    return {"share": hot / total, "files": files, "lines": total} if total else None


def doctor_checks(args) -> list[dict]:
    import shutil
    out = []
    v = sys.version_info
    out.append(_check("python", "ok" if v >= (3, 11) else "fail", f"Python {v.major}.{v.minor}.{v.micro}",
                      None if v >= (3, 11) else "gradekit needs Python 3.11 or later (it uses tomllib)"))
    try:
        catalog = load_catalog()
        load_json(SCHEMA_PATH)
        load_toml(DEFAULTS_PATH)
        out.append(_check("kit", "ok", f"suite {catalog['suite_version']} at {SUITE_DIR}"))
    except Exception as exc:   # noqa: BLE001 - any failure here means a broken kit
        out.append(_check("kit", "fail", f"can't load the kit at {SUITE_DIR}: {exc}", "download the kit again"))
        return out
    tmp = Path(tempfile.gettempdir())
    try:
        with tempfile.NamedTemporaryFile(dir=tmp, prefix="gradekit-doctor-") as fh:
            fh.write(b"ok")
        out.append(_check("temp", "ok", f"can write to {tmp}"))
    except OSError as exc:
        out.append(_check("temp", "fail", f"can't write to {tmp}: {exc}", "set TMPDIR to a writable folder"))

    if args.site:
        out += doctor_site(args.site, catalog)

    pdir = project_dir_from_args(args)
    if pdir or getattr(args, "config", None):
        try:
            cfg = load_config(args, quiet=True)
            warn = cfg.get("warnings", [])
            out.append(_check("config", "warn" if warn else "ok",
                              f"{cfg['hash']} · preset {cfg['preset']}" + (f" · {len(warn)} warning(s): {'; '.join(warn)}" if warn else "")))
            pin, kit = suite_pin(cfg), major(catalog["suite_version"])
            if pin is None:
                out.append(_check("suite pin", "warn", "project.toml doesn't pin a suite version",
                                  f"the project's owner should add `suite = \"{kit}\"` under [project] (graders don't change it), "
                                  "so a new major version can't change the rules mid-cycle"))
            else:
                out.append(_check("suite pin", "fail" if pin_problem(cfg) else "ok",
                                  pin_problem(cfg) or f"pinned to {pin}; this kit is {catalog['suite_version']}"))
        except GradekitError as exc:
            out.append(_check("config", "fail", str(exc), "fix project.toml; `gradekit resolve` shows the details"))
            cfg = None
        if pdir:
            for fname in (DECISIONS_FILE, DISPOSITIONS_FILE):
                f = pdir / fname
                if f.exists():
                    try:
                        load_json(f, want=(dict, list))
                    except GradekitError as exc:
                        out.append(_check(fname, "fail", str(exc), f"fix the JSON in {f}"))
            reports = pdir / "reports"
            try:
                reports.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=reports, prefix=".gradekit-doctor-"):
                    pass
                out.append(_check("project folder", "ok", f"can write to {reports}"))
            except OSError as exc:
                out.append(_check("project folder", "fail", f"can't write to {reports}: {exc}", "check the folder's permissions"))
            found = report_folders(pdir)
            out.append(_check("previous report", "ok", f"{found[-1].name} (start with `gradekit carry`)") if found
                       else _check("previous report", "ok", "none: this is the first report (start with `gradekit report new`)"))

    if args.repo:
        repo = Path(args.repo)
        if repo.suffix == ".zip" and repo.is_file():
            out.append(_check("code repo", "ok", f"zip {repo}"))
        elif repo.is_dir():
            n = sum(1 for _ in repo.rglob("*") if ".git" not in _.parts)
            rc, head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]) if shutil.which("git") else (None, "")
            out.append(_check("code repo", "ok", f"{repo} · {n} files" + (f" · commit {head[:12]}" if rc == 0 else " · not a git checkout")))
            hot = hot_share(repo, cfg) if (pdir or getattr(args, "config", None)) and cfg else None
            if hot and hot["share"] > HOT_SHARE_WARN:
                out.append(_check("hot zones", "warn",
                                  f"hot zones cover {round(hot['share'] * 100)}% of the code's lines ({', '.join(hot['files'][:3])}"
                                  f"{' …' if len(hot['files']) > 3 else ''}). A zone that covers everything can't say where problems "
                                  "cost more, and L3 allows no major findings in it",
                                  "for the project's owner: keep hot zones to the code where a bug costs more (money, access, "
                                  "important data) in project.toml [[zones]]. A grader just notes it under limitations"))
        else:
            out.append(_check("code repo", "fail", f"not found: {repo}", "pass the code checkout (or a zip of it) with --repo"))

    if args.delivery == "pr":
        out += doctor_git(args, pdir)
    return out


def doctor_site(site: str, catalog: dict) -> list[dict]:
    import urllib.request
    url = site.rstrip("/") + "/manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            man = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:   # noqa: BLE001 - any network failure is the finding
        return [_check("suite website", "fail", f"can't fetch {url}: {exc}",
                       "check the address, and that this sandbox may reach it (network allowlist or proxy)")]
    out = []
    ver = man.get("version")
    out.append(_check("suite website", "ok" if ver == catalog["suite_version"] else "warn",
                      f"{site} serves {ver}; this kit is {catalog['suite_version']}",
                      None if ver == catalog["suite_version"] else "use the kit the website serves (its download link), so prompts and tools match"))
    if ver == catalog["suite_version"]:
        changed = []
        for f in man.get("files", []):
            rel = str(f.get("path", ""))
            if rel.startswith("suite/"):
                local = SUITE_DIR / rel[len("suite/"):]
                if local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() != f.get("sha256"):
                    changed.append(rel[len("suite/"):])
        out.append(_check("kit files", "warn" if changed else "ok",
                          f"{len(changed)} differ from the website's copy: {', '.join(changed[:5])}" if changed else "match the website's copy",
                          "download the kit again if you didn't change these on purpose" if changed else None))
    return out


def doctor_git(args, pdir) -> list[dict]:
    import shutil
    out = []
    if not shutil.which("git"):
        return [_check("git", "fail", "not installed", "pr delivery needs git; or use --delivery save or return")]
    root = pdir or Path(args.grading_repo or ".")
    rc, top = _run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if rc != 0:
        return [_check("grading repo", "fail", f"{root} is not in a git checkout",
                       "clone the grading repo, or use --delivery save or return")]
    out.append(_check("grading repo", "ok", top))
    name = _run(["git", "-C", top, "config", "user.name"])[1]
    email = _run(["git", "-C", top, "config", "user.email"])[1]
    out.append(_check("git identity", "ok" if name and email else "fail", f"{name or '?'} <{email or '?'}>",
                      None if name and email else "git config user.name … && git config user.email …"))
    rc, url = _run(["git", "-C", top, "remote", "get-url", args.remote])
    if rc != 0:
        out.append(_check("remote", "fail", f"no remote '{args.remote}'", f"git remote add {args.remote} URL, or pass --remote"))
        return out
    rc, msg = _run(["git", "-C", top, "ls-remote", "--symref", args.remote, "HEAD"], timeout=60)
    if rc != 0:
        out.append(_check("remote read", "fail", f"can't read {url}: {msg.splitlines()[-1] if msg else ''}",
                          "check the address and the credentials this sandbox uses"))
        return out
    head = re.search(r"ref: refs/heads/(\S+)\s+HEAD", msg)
    out.append(_check("remote read", "ok", f"{url} (default branch {head.group(1) if head else 'unknown'})"))
    probe = f"refs/heads/gradekit-doctor-{os.getpid()}"
    rc, msg = _run(["git", "-C", top, "push", "--dry-run", "--quiet", args.remote, f"HEAD:{probe}"], timeout=60)
    out.append(_check("remote push", "ok" if rc == 0 else "fail",
                      "push allowed (dry run)" if rc == 0 else f"push refused (dry run): {msg.splitlines()[-1] if msg else ''}",
                      None if rc == 0 else "the grader needs permission to push branches to the grading repo"))
    if args.open:
        tool = {"github": "gh", "gitlab": "glab"}[args.open]
        rc, msg = _run([tool, "auth", "status"])
        out.append(_check(tool, "ok" if rc == 0 else "fail",
                          "signed in" if rc == 0 else (msg.splitlines()[-1].strip(" -") if msg else "not signed in"),
                          None if rc == 0 else f"{tool} auth login, or open the pull request by hand (drop --open)"))
    return out


def cmd_doctor(args) -> int:
    checks = doctor_checks(args)
    mark = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
    lines = []
    for c in checks:
        lines.append(f"{mark[c['status']]}  {c['check']:<16} {c['detail']}")
        if c.get("fix"):
            lines.append(f"      {'':<16} → {c['fix']}")
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    lines.append(f"\n{'ready' if not fails else 'not ready'}: {len(fails)} problem(s), {len(warns)} warning(s)")
    emit(args, {"ready": not fails, "checks": checks}, "\n".join(lines))
    return 1 if fails else 0
