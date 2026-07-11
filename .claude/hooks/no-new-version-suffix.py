#!/usr/bin/env python3
"""PreToolUse advisory guard for the no-new-vN-suffix convention (spec C9,
docs/superpowers/specs/2026-07-10-deversioning-cleanup.md).

On a `git commit` Bash call, inspects the STAGED DIFF (not the tool_input
itself) for two patterns under owned dirs (src/, scripts/, data/,
frontend/src/, configs/):
  (a) newly-added file paths matching `_v[0-9]`/`V[0-9]`.
  (b) newly-added definition lines `^(def|class|[A-Z0-9_]+ *=).*_v[0-9]`.
Skips prose, dotted decimals (`\\d\\.\\d`), `api/v1`, `rev-`, `wave-`, and
anything matching an entry in .claude/allowlist-versioned.txt.

ADVISORY ONLY: never emits a permissionDecision, never blocks the commit —
prints a warning to stderr and always exits 0. The flip to a blocking hook is
an owner decision (J-GUARD), not made by this script.

FAIL-OPEN: any exception / parse error / missing input -> exit 0, no output.
Never block the session on a hook bug.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

OWNED_DIRS = ("src/", "scripts/", "data/", "frontend/src/", "configs/")

# item 3(a): new file path matches _v<digit> or V<digit>.
FILE_TOKEN_RE = re.compile(r"_v[0-9]|V[0-9]")
# item 3(b): a newly-added def/class/CONST= line whose text also carries a
# _v<digit> suffix.
DEF_LINE_RE = re.compile(r"^\s*(def|class|[A-Z0-9_]+\s*=).*_v[0-9]")

SKIP_RES = (
    re.compile(r"\d\.\d"),  # dotted decimals (model names, semver)
    re.compile(r"api/v1"),
    re.compile(r"rev-"),
    re.compile(r"wave-"),
)


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _load_allowlist() -> list[str]:
    path = os.path.join(_project_dir(), ".claude", "allowlist-versioned.txt")
    entries: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                entries.append(line)
    except Exception:
        pass
    return entries


def _skip(text: str, allowlist: list[str]) -> bool:
    if any(p.search(text) for p in SKIP_RES):
        return True
    return any(entry in text for entry in allowlist)


def _under_owned_dir(path: str) -> bool:
    return any(path.startswith(d) for d in OWNED_DIRS)


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_project_dir(),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.stdout
    except Exception:
        return ""


def _is_git_commit(command: str) -> bool:
    return bool(re.match(r"git\s+commit(\s|$)", command.lstrip()))


def _check_staged_paths(allowlist: list[str]) -> list[str]:
    warnings = []
    out = _run_git(["diff", "--cached", "--name-only", "--diff-filter=A"])
    for path in out.splitlines():
        path = path.strip()
        if not path or not _under_owned_dir(path):
            continue
        if _skip(path, allowlist):
            continue
        if FILE_TOKEN_RE.search(os.path.basename(path)):
            warnings.append(f"new file path looks version-suffixed: {path}")
    return warnings


def _check_staged_defs(allowlist: list[str]) -> list[str]:
    warnings = []
    out = _run_git(["diff", "--cached", "-U0"])
    current_file = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            # "+++ b/src/palimpsest/foo.py" (or "+++ /dev/null" on delete)
            current_file = line[6:] if line.startswith("+++ b/") else None
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if current_file is None or not _under_owned_dir(current_file):
            continue
        content = line[1:]
        if _skip(content, allowlist):
            continue
        if DEF_LINE_RE.match(content):
            warnings.append(f"{current_file}: new vN-suffixed definition: {content.strip()}")
    return warnings


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

    if data.get("tool_name") != "Bash":
        return
    tool_input = data.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = tool_input.get("command") or ""
    if not isinstance(command, str) or not _is_git_commit(command):
        return

    allowlist = _load_allowlist()
    warnings = _check_staged_paths(allowlist) + _check_staged_defs(allowlist)
    if not warnings:
        return

    print(
        "no-new-version-suffix (advisory, C9): possible new vN suffix on an "
        "owned artifact in the staged diff — see CLAUDE.md § Conventions "
        "§ Code and .claude/allowlist-versioned.txt. Advisory only, commit proceeds.",
        file=sys.stderr,
    )
    for w in warnings:
        print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Absolute last-resort fail-open.
        pass
    sys.exit(0)
