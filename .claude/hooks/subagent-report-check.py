#!/usr/bin/env python3
"""SubagentStop report-check (Phase-1 workflow hardening).

A NAMED project agent (one that has a `.claude/agents/<agent_type>.md` file) must
leave a fresh report at `docs/reports/<agent_type>-*.md` before finishing. Generic /
built-in agents (claude, Explore, general-purpose, Plan, plugin agents) have no such
file and are exempt — this auto-adapts as the project agent roster grows.

Anti-stale: pairs with `subagent-activity-marker.py`, which stamps
`.claude/.subagent-markers/<agent_id>` at first tool activity. A report only counts
if its mtime >= the marker mtime, so a stale pre-existing report cannot pass.

Edge case — missing marker: if the subagent made no tool calls there is no marker,
so staleness cannot be proven. To avoid false-blocking we ALLOW in that case.

BLOCK output: {"decision":"block","reason":"..."} and exit 0.
ALLOW: exit 0 with no output.
FAIL-OPEN: any exception / parse error / missing input -> exit 0 silently (allow).
"""
from __future__ import annotations

import glob
import json
import os
import sys


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _block(agent_type: str) -> None:
    reason = (
        f"No report found. Write docs/reports/{agent_type}-<task-slug>.md per the "
        "reporting schema (Scope; Files changed; Decisions & rationale; Open "
        "questions; NOT done) before finishing."
    )
    print(json.dumps({"decision": "block", "reason": reason}, separators=(",", ":")))


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw or not raw.strip():
        return
    try:
        data = json.loads(raw)
    except Exception:
        return
    if not isinstance(data, dict):
        return

    agent_type = data.get("agent_type")
    agent_id = data.get("agent_id")
    if not agent_type or not isinstance(agent_type, str):
        return  # cannot identify agent -> allow

    project = _project_dir()

    # Exempt any agent that is not a named project agent.
    agent_def = os.path.join(project, ".claude", "agents", f"{agent_type}.md")
    if not os.path.exists(agent_def):
        return  # generic / built-in / plugin agent -> exempt

    # Without a marker we cannot prove freshness; allow to avoid false-block.
    if not agent_id or not isinstance(agent_id, str):
        return
    marker = os.path.join(project, ".claude", ".subagent-markers", agent_id)
    if not os.path.exists(marker):
        return
    try:
        marker_mtime = os.path.getmtime(marker)
    except Exception:
        return

    reports = glob.glob(
        os.path.join(project, "docs", "reports", f"{agent_type}-*.md")
    )
    for path in reports:
        try:
            if os.path.getmtime(path) >= marker_mtime:
                return  # fresh report exists -> allow
        except Exception:
            continue

    _block(agent_type)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
