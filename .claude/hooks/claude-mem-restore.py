#!/usr/bin/env python3
"""SessionStart best-effort claude-mem index refresh (spec P5.2).

Canonical memory is the git-committed text under `.claude/memory/*.jsonl`
(P5.1). claude-mem is an OPTIONAL runtime index on top of it -- nothing here
may be relied on, and every branch degrades to doing nothing without ever
touching the git-text memory.

Reality check (claude-mem v13.10.0, `--help` + CLI source): there is no
"import/rebuild index from files" subcommand. `search` only proxies to a
running worker's HTTP API, and every runtime subcommand (status/doctor/
search/start) refuses to run unless the plugin is registered under
`~/.claude` -- which conflicts with G1 (zero `~/.claude` deps) and is
intentionally NOT restored by cloud-setup.sh (see P5.2 notes there). So
"refresh" here is a truthful presence/reachability probe only, never a real
rebuild: if claude-mem happens to be installed+running anyway, note that
`claude-mem search` is available this session; otherwise no-op silently.

FAIL-OPEN: any exception, timeout, missing binary, or missing jsonl -> exit 0
silently. Must add negligible latency when claude-mem is absent (or when
there is nothing to index) -- no subprocess is spawned in either case.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def main() -> None:
    # Drain stdin so the pipe never blocks; we don't need its content.
    try:
        sys.stdin.read()
    except Exception:
        pass

    # Fast, no-subprocess check: binary absent -> negligible-latency no-op.
    if not shutil.which("claude-mem"):
        return

    project = _project_dir()
    jsonl_files = glob.glob(os.path.join(project, ".claude", "memory", "*.jsonl"))
    if not jsonl_files:
        return  # nothing to index -> no-op before ever spawning a subprocess

    # No claude-mem CLI command rebuilds an index from arbitrary jsonl; the
    # only thing we can safely and truthfully do is a timeout-guarded
    # reachability probe. `status` requires the plugin to be registered
    # under ~/.claude, so in the G1-compliant (zero ~/.claude deps) setup
    # this fails fast and we no-op.
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
        return  # not installed / worker down -> silent no-op

    text = (
        "claude-mem worker is reachable this session -- `claude-mem search "
        "<query>` may surface indexed observations. The canonical memory is "
        "still the committed text under .claude/memory/*.jsonl; treat "
        "claude-mem as an accelerator, not a source of truth."
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
