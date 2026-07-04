#!/usr/bin/env python3
"""PreToolUse activity marker for subagents (Phase-1 workflow hardening).

Fires on ALL tools. When a subagent call is seen (`agent_id` present), record the
first-activity time by creating `.claude/.subagent-markers/<agent_id>` iff absent.
The marker's mtime is the earliest tool call of the run; SubagentStop later checks
that a fresh report (mtime >= marker mtime) exists, so a stale pre-existing report
cannot satisfy the requirement. Only create when absent — never bump the mtime.

This hook NEVER denies: it always exits 0 with no output.
FAIL-OPEN: any exception / parse error / missing input -> exit 0 silently.
"""
from __future__ import annotations

import json
import os
import sys


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


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

    agent_id = data.get("agent_id")
    if not agent_id or not isinstance(agent_id, str):
        return  # main thread or malformed -> nothing to mark

    markers_dir = os.path.join(_project_dir(), ".claude", ".subagent-markers")
    try:
        os.makedirs(markers_dir, exist_ok=True)
        marker = os.path.join(markers_dir, agent_id)
        if not os.path.exists(marker):
            # Create empty marker; its mtime = first-activity time.
            with open(marker, "w"):
                pass
    except Exception:
        return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
