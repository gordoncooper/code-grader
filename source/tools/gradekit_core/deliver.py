"""deliver: hand back a finished report."""
from __future__ import annotations

import argparse
import re
import tempfile
from pathlib import Path

from .common import die, emit, EXIT_INCOMPLETE, git_out, load_catalog, load_report, write_json
from .config import component_reports, project_dir_for_report, PUBLISHING_DEFAULTS
from .rollup import apply_rollup
from .publishing import private_path, publish_problems, redact_report
from .validate import validate_report
from .evidence import record_citations_checked, verify_evidence
from .authoring import authoring_config, normalize_report, repo_reader, report_todo
from .render import render_report_md, render_report_pr


# Hands a finished report back in one of the grader's three deliveries (pr, save, return). The
# preparation is the same for all: finished, redacted if the grading repo is public, safe to
# publish, report.md rendered. For pr, the git steps are printed, or run with --run. Pushing and
# opening the pull request are separate opt-ins, because those depend on where the repo is hosted.

def default_branch(root, remote: str) -> str:
    ref = git_out(root, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD", check=False)
    if ref:
        return ref
    for cand in (f"{remote}/main", f"{remote}/master", "main", "master"):
        if git_out(root, "rev-parse", "--verify", "--quiet", cand, check=False):
            return cand
    die("can't tell the grading repo's default branch; pass --base BRANCH")


def prepare_delivery(args, report: dict, cfg: dict) -> dict:
    """Everything every delivery needs. Returns the file paths, or dies with what's left to do."""
    normalize_report(report, cfg)
    errors, _ = validate_report(report, cfg, load_catalog())
    todo = report_todo(report, project_dir_for_report(args.report))
    checked = verify_evidence(report, repo_reader(args.repo), 2) if args.repo else None
    if checked:
        errors += [f"citation: {f}" for f in checked["failures"]]
    if errors or todo:
        args._exit = 1 if errors else EXIT_INCOMPLETE
        raise DeliveryBlocked(errors, todo)
    if checked:
        record_citations_checked(report, checked)
    apply_rollup(report, cfg)   # always: a stored rollup can be older than the last score change
    write_json(args.report, report)
    files = {"report": args.report, "private": None}
    public = bool((cfg.get("publishing") or PUBLISHING_DEFAULTS).get("public"))
    if public and not (report.get("publishing") or {}).get("redacted"):
        pub, leaks = redact_report(report)
        if leaks:
            args._exit = 1
            raise DeliveryBlocked([f"leak: {x}" for x in leaks], [])
        priv = private_path(args.report)
        write_json(priv, report)
        write_json(args.report, pub)
        report = pub
    if Path(private_path(args.report)).exists():
        files["private"] = private_path(args.report)
    if public:
        problems = publish_problems(report)
        if problems:
            args._exit = 1
            raise DeliveryBlocked([f"publish: {p}" for p in problems], [])
    md = re.sub(r"\.json$", "", args.report) + ".md"
    Path(md).write_text(render_report_md(report, cfg), encoding="utf-8")
    files["markdown"] = md
    files["components"] = prepare_components(Path(args.report).parent, public, args)
    files["report_obj"] = report
    return files


def prepare_components(folder: Path, public: bool, args) -> list[str]:
    """A monorepo report's components/NAME.json: each finished, redacted when public, with its report.md."""
    done = []
    for cp in component_reports(folder):
        r = load_report(cp)
        ns = argparse.Namespace(report=str(cp), config=None, project=None, project_dir=None, component=None, grading_repo=None)
        ccfg = authoring_config(ns, r)
        errors, _ = validate_report(r, ccfg, load_catalog())
        todo = report_todo(r, project_dir_for_report(cp))
        if errors or todo:
            args._exit = 1 if errors else EXIT_INCOMPLETE
            raise DeliveryBlocked([f"components/{cp.name}: {e}" for e in errors], [f"components/{cp.name}: {x}" for x in todo])
        if public and not (r.get("publishing") or {}).get("redacted"):
            pub, leaks = redact_report(r)
            if leaks:
                args._exit = 1
                raise DeliveryBlocked([f"components/{cp.name}: leak: {x}" for x in leaks], [])
            write_json(private_path(str(cp)), r)
            write_json(cp, pub)
            r = pub
        cp.with_suffix(".md").write_text(render_report_md(r, ccfg), encoding="utf-8")
        done.append(str(cp))
    return done


class DeliveryBlocked(Exception):
    def __init__(self, errors, todo):
        super().__init__("report not ready")
        self.errors, self.todo = errors, todo


def cmd_deliver(args) -> int:
    report = load_report(args.report)
    cfg = authoring_config(args, report)
    if (args.push or args.open) and not args.run:
        die("--push and --open need --run")
    if args.open and not args.push:
        die("--open needs --push (the branch must be on the host first)")
    try:
        files = prepare_delivery(args, report, cfg)
    except DeliveryBlocked as b:
        lines = [f"ERROR: {e}" for e in b.errors] + [f"todo:  {t}" for t in b.todo]
        lines.append(f"\nnot delivered: {len(b.errors)} error(s), {len(b.todo)} to do (`gradekit report check` lists the same)")
        emit(args, {"delivered": False, "errors": b.errors, "todo": b.todo}, "\n".join(lines))
        return args._exit
    report = files.pop("report_obj")
    folder = Path(args.report).resolve().parent
    if folder.name == "runs":
        die("deliver the consensus report.json, not one run (see `gradekit stability`)")
    pr = render_report_pr(report, cfg, args.site, args.grading_repo_url, args.branch, folder.name)
    result = {"delivered": False, "delivery": args.delivery, "files": files, "title": pr["title"]}
    lines = [f"ready: {files['report']}" + (f" (public copy; full report in {files['private']})" if files["private"] else ""),
             f"wrote {files['markdown']}"]
    private_note = (f"keep {files['private']} private: never commit it or paste it into a pull request; "
                    f"hand it to whoever fixes the code") if files["private"] else None

    if args.delivery == "return":
        blocks = [("report.json", Path(files["report"]).read_text(encoding="utf-8"), "json"),
                  ("report.md", Path(files["markdown"]).read_text(encoding="utf-8"), "markdown")]
        if files["private"]:
            blocks.append(("report.private.json (private: don't commit)", Path(files["private"]).read_text(encoding="utf-8"), "json"))
        result.update(delivered=True, blocks=[{"name": n, "content": c} for n, c, _ in blocks])
        lines.append("\nReturn these in your final message, each in its own fenced block:")
        for name, content, lang in blocks:
            lines += ["", f"**{name}**", f"````{lang}", content.rstrip("\n"), "````"]
        emit(args, result, "\n".join(lines))
        return 0

    if args.delivery == "save":
        result["delivered"] = True
        result["folder"] = str(folder)
        lines.append(f"saved in {folder}")
        if private_note:
            lines.append(private_note)
        emit(args, result, "\n".join(lines))
        return 0

    # ---- pr
    root = Path(git_out(folder, "rev-parse", "--show-toplevel"))
    rel = folder.relative_to(root.resolve()).as_posix()
    base = args.base or default_branch(root, args.remote)
    branch = pr["branch"]
    base_name = base.split("/", 1)[1] if base.startswith(args.remote + "/") else base
    if branch in (base, base_name):
        die("refusing to deliver onto the default branch; reports go through a pull request")
    body_file = Path(args.body_file) if args.body_file else Path(tempfile.gettempdir()) / f"gradekit-{branch.replace('/', '_')}.md"
    body_file.write_text(pr["body"], encoding="utf-8")
    msg = f"{pr['title']}\n\n{(report.get('summary') or '').strip()}".strip()
    only = [rel, f":(exclude){rel}/**/*.private.json", f":(exclude){rel}/*.private.json"]   # never the private report
    steps = [["git", "-C", str(root), "switch", "-c", branch, base],
             ["git", "-C", str(root), "add", "--", *only],
             ["git", "-C", str(root), "commit", "-m", msg, "--", *only]]
    if args.push:
        steps.append(["git", "-C", str(root), "push", "-u", args.remote, branch])
    if args.open == "github":
        steps.append(["gh", "pr", "create", "--base", base_name, "--head", branch,
                      "--title", pr["title"], "--body-file", str(body_file)])
    elif args.open == "gitlab":
        steps.append(["glab", "mr", "create", "--source-branch", branch, "--target-branch", base_name,
                      "--title", pr["title"], "--description", pr["body"], "--yes"])
    result.update(branch=branch, base=base_name, body_file=str(body_file), commands=[shell_join(s) for s in steps])
    if not args.run:
        lines += ["", f"pull request: {pr['title']}", f"branch {branch} from {base}; body in {body_file}", "",
                  "run these (or `gradekit deliver … --run`), then open a pull request from that branch with that title and body:"]
        lines += [f"  {shell_join(s)}" for s in steps]
        if private_note:
            lines += ["", private_note]
        emit(args, result, "\n".join(lines))
        return 0

    import subprocess
    current = git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current == branch:
        steps = steps[1:]          # already on the report branch (a re-run)
    elif git_out(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        die(f"branch {branch} already exists; switch to it, or delete it, and run again")
    url = None
    for s in steps:
        r = subprocess.run(s, capture_output=True, text=True, cwd=str(root), timeout=300)
        if r.returncode != 0:
            msg_ = (r.stderr or r.stdout).strip()
            if s[3:5] == ["commit", "-m"] and re.search(r"nothing (added )?to commit", r.stdout + r.stderr):
                continue
            if "user.email" in msg_ or "Author identity unknown" in msg_:
                msg_ += "\n(set the committer: git config user.name … and git config user.email …)"
            die(f"`{shell_join(s)}` failed:\n{msg_}")
        found = re.findall(r"https?://\S+", r.stdout)
        if s[0] in ("gh", "glab") and found:
            url = found[-1]
    staged = git_out(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    leaked = [f for f in staged if f.endswith(".private.json")]
    if leaked:
        die(f"a private report was committed ({', '.join(leaked)}): undo with `git reset --soft HEAD~1` before pushing")
    result.update(delivered=True, commit=git_out(root, "rev-parse", "HEAD"), pushed=bool(args.push), url=url)
    lines += ["", f"pull request title: {pr['title']}", f"committed {rel} on {branch}" + (f" and pushed to {args.remote}" if args.push else "")]
    if url:
        lines.append(f"pull request: {url}")
    elif args.push:
        lines.append(f"open a pull request from {branch} into {base_name} with that title and the body in {body_file}")
    else:
        lines.append(f"next: push {branch} and open a pull request into {base_name} with that title and the body in {body_file}")
    if private_note:
        lines.append(private_note)
    emit(args, result, "\n".join(lines))
    return 0


def shell_join(parts) -> str:
    import shlex
    return " ".join(shlex.quote(str(p)) for p in parts)
