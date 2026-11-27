"""The gradekit engine: one module per area. Each imports only from the modules before it in MODULES (mcp and web
import cli inside the functions that need it). tools/gradekit.py loads this package and re-exports every name."""
from __future__ import annotations

MODULES = ("common", "config", "zones", "records", "schema", "rollup", "publishing", "validate", "evidence", "compare", "settings", "orders", "authoring", "carry", "doctor", "guard", "render", "deliver", "disputes", "rubric", "calibration", "index", "ci", "mcp", "web", "cli")

from . import common, config, zones, records, schema, rollup, publishing, validate, evidence, compare, settings, orders, authoring, carry, doctor, guard, render, deliver, disputes, rubric, calibration, index, ci, mcp, web, cli  # noqa: E402,F401  (in dependency order)
