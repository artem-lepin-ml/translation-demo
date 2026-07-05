#!/usr/bin/env python3
"""SessionStart context pointer (Phase-1 workflow hardening).

If current-state docs exist, inject an `additionalContext` note listing their PATHS
ONLY (never their contents) so the session reads them before continuing.

If none of the candidate files exist -> exit 0 with no output.
FAIL-OPEN: any exception -> exit 0 silently.
"""
from __future__ import annotations

import json
import os
import sys

CANDIDATES = [
    "docs/superpowers/STATE.md",
    "docs/superpowers/CONTEXT.md",
    ".claude/session-context/STATE.md",
    ".claude/session-context/CONTEXT.md",
]


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def main() -> None:
    # Drain stdin if present so the pipe never blocks; we don't need its content.
    try:
        sys.stdin.read()
    except Exception:
        pass

    project = _project_dir()
    present = [rel for rel in CANDIDATES if os.path.exists(os.path.join(project, rel))]
    if not present:
        return

    text = (
        "Current-state docs present: "
        + ", ".join(present)
        + ". Read them before continuing."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": text,
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
