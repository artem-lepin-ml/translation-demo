#!/usr/bin/env python3
"""PreToolUse approval gate for the experiment-runner agent (Spec P3.B).

When the calling agent is `experiment-runner` and it tries to run `Bash`, DENY
until an approval file exists. The active experiment slug is read from
`docs/experiments/ACTIVE` (a one-line file); execution is unlocked only once the
owner has created `docs/experiments/<slug>/APPROVED`.

- agent_type != "experiment-runner" -> allow (no-op).
- tool_name != "Bash"                -> allow (no-op).
- ACTIVE missing / APPROVED absent   -> deny with the gate reason.

Deny schema matches the other PreToolUse hooks: print the hookSpecificOutput
JSON and exit 0. Allow = exit 0 with no output.

FAIL-OPEN: any exception / parse error / missing input -> exit 0, no output.
Never block the session on a hook bug.
"""
from __future__ import annotations

import json
import os
import sys

DENY_REASON = (
    "experiment-runner: Bash execution is gated. Write TASK.md/BUDGET.md/PLAN.md, "
    "then the owner must create docs/experiments/<slug>/APPROVED before execution."
)


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _deny() -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DENY_REASON,
                }
            },
            separators=(",", ":"),
        )
    )


def _approved() -> bool:
    exp_dir = os.path.join(_project_dir(), "docs", "experiments")
    active_path = os.path.join(exp_dir, "ACTIVE")
    try:
        with open(active_path, encoding="utf-8") as fh:
            slug = fh.read().strip()
    except Exception:
        return False
    if not slug or slug.startswith("#"):
        return False
    return os.path.exists(os.path.join(exp_dir, slug, "APPROVED"))


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

    if data.get("agent_type") != "experiment-runner":
        return  # not our agent -> allow
    if data.get("tool_name") != "Bash":
        return  # only Bash is gated -> allow

    if not _approved():
        _deny()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Absolute last-resort fail-open.
        pass
    sys.exit(0)
