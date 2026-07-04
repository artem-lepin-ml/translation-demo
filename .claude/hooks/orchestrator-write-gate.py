#!/usr/bin/env python3
"""PreToolUse write-gate for orchestration mode (Phase-1 workflow hardening).

When `.claude/.orchestration-active` exists, the MAIN THREAD must not make direct
edits or non-read-only Bash calls — work is dispatched to named subagents via Task.
Subagent calls (identified by `agent_id` or `agent_type` in the PreToolUse stdin)
are always allowed. When the flag file is absent the hook is a no-op.

Matchers: Edit | Write | NotebookEdit | Bash.
NOTE: `MultiEdit` is intentionally omitted — that tool no longer exists in current
Claude Code (Edit covers multi-replace).

FAIL-OPEN: any exception / parse error / missing input -> exit 0 with no output.
Never block the session on a hook bug.
"""
from __future__ import annotations

import json
import os
import sys

# Read-only Bash allowlist: a command is allowed iff, after stripping leading
# whitespace, it equals one of these entries or starts with "<entry> ". `git`
# needs its subcommand pinned so `git push` etc. do not slip through.
READONLY_BASH_ALLOWLIST = [
    "git status",
    "git log",
    "git diff",
    "ls",
    "cat",
    "grep",
    "find",
    "rg",
]

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}

DENY_REASON = (
    "Orchestration mode: dispatch this via Task to a named agent. "
    "Direct edits are blocked."
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


def _bash_is_readonly(command: str) -> bool:
    cmd = command.lstrip()
    for entry in READONLY_BASH_ALLOWLIST:
        if cmd == entry or cmd.startswith(entry + " "):
            return True
    return False


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

    flag = os.path.join(_project_dir(), ".claude", ".orchestration-active")
    if not os.path.exists(flag):
        return  # orchestration off -> allow everything

    # Subagent calls carry agent_id and/or agent_type; main thread has NEITHER.
    if data.get("agent_id") is not None or data.get("agent_type") is not None:
        return  # subagent -> always allow

    tool_name = data.get("tool_name")
    if tool_name in WRITE_TOOLS:
        _deny()
        return

    if tool_name == "Bash":
        command = ""
        tool_input = data.get("tool_input")
        if isinstance(tool_input, dict):
            command = tool_input.get("command") or ""
        if isinstance(command, str) and _bash_is_readonly(command):
            return  # read-only command -> allow
        _deny()
        return

    # Any other tool under the matcher (shouldn't happen) -> allow.
    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Absolute last-resort fail-open.
        pass
    sys.exit(0)
