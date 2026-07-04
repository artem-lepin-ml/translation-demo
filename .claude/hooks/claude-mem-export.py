#!/usr/bin/env python3
"""Stop best-effort claude-mem observations export (spec P5.2).

Canonical memory is the git-committed text under `.claude/memory/*.jsonl`
(P5.1). This hook would append this session's claude-mem observations to
`.claude/memory/observations-<session_id>.jsonl` IF claude-mem exposed a
clean way to fetch them.

Reality check (claude-mem v13.10.0, `--help` + CLI source): it doesn't.
There is no "dump this session's observations" subcommand; `search` only
returns free-text query hits from a running worker, not a session-scoped
export, and every runtime subcommand also refuses to run unless the plugin
is registered under `~/.claude` (see claude-mem-restore.py for the same
finding). So this hook only ever no-ops -- it NEVER fabricates a placeholder
line. It would only ever write a file if claude-mem actually handed back
real observation data through a clean command, which today it does not.

FAIL-OPEN: any exception, timeout, missing binary/session_id/worker -> exit
0, no file written, no output. Never a partial/corrupt jsonl line.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


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

    session_id = data.get("session_id")
    if not session_id or not isinstance(session_id, str):
        return  # can't safely name the output file -> no-op

    if not shutil.which("claude-mem"):
        return

    try:
        result = subprocess.run(
            ["claude-mem", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return
    if result.returncode != 0:
        return  # plugin/worker unavailable -> no-op, no file

    # claude-mem v13.10.0 has no per-session observation dump command
    # reachable from a clean CLI call, so there is nothing real to export.
    # Deliberately do not write a placeholder/note line -- only real
    # observations would ever be written here, and there is currently no
    # documented way to obtain them. Always a no-op today.
    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
