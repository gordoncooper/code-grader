"""Zones (hot, normal, cold), from a project's paths, and the severity the rules use."""
from __future__ import annotations

import re

from .common import HEAT, repo_relative


def glob_to_regex(pattern: str) -> re.Pattern:
    p = repo_relative(pattern)
    if p.endswith("/"):
        p += "**"
    out, i = "", 0
    while i < len(p):
        if p.startswith("**/", i):
            out += r"(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += r".*"
            i += 2
        elif p[i] == "*":
            out += r"[^/]*"
            i += 1
        elif p[i] == "?":
            out += r"[^/]"
            i += 1
        else:
            out += re.escape(p[i])
            i += 1
    return re.compile(rf"^{out}$")


def zone_for_path(path: str, cfg: dict) -> tuple[str | None, str]:
    path = repo_relative(path)
    for z in cfg["zones"]["list"]:
        for pat in z.get("paths", []):
            if glob_to_regex(pat).match(path):
                return z.get("name"), z.get("criticality")
    return None, cfg["zones"]["default"]


def finding_zone(finding: dict, cfg: dict) -> tuple[str | None, str]:
    """The hottest zone among the files a finding cites (code evidence + `paths`)."""
    files = [ev.get("file") for ev in finding.get("evidence", []) if ev.get("type") == "code" and ev.get("file")]
    files += list(finding.get("paths", []) or [])
    if not files:
        return None, cfg["zones"]["default"]
    return max((zone_for_path(f, cfg) for f in files), key=lambda z: HEAT[z[1]])


def effective_severity(finding: dict, criticality: str, cfg: dict) -> str:
    """The severity the rules use: the grader's, judged where the code runs. Zones don't shift it (since scoring 5.0)."""
    return finding.get("severity", "minor")


def analyze_findings(report: dict, cfg: dict) -> dict:
    out = {}
    for f in report.get("findings", []):
        zname, crit = finding_zone(f, cfg)
        out[f.get("id")] = {"zone": zname, "criticality": crit, "severity": f.get("severity"),
                            "effective_severity": effective_severity(f, crit, cfg),
                            "status": f.get("status"), "benchmark_id": f.get("benchmark_id")}
    return out
