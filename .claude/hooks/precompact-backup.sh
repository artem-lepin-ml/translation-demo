#!/bin/sh
# PreCompact transcript backup (Phase-1 workflow hardening).
#
# Reads `transcript_path` from the PreCompact stdin JSON and copies the transcript
# into .claude/session-context/backups/<timestamp>.jsonl so the pre-compaction
# conversation is recoverable. The backups dir is gitignored (P5.4).
#
# FAIL-OPEN: any missing input / parse error / copy failure -> exit 0 silently.
# A backup hook must never brick a compaction.

set +e

INPUT="$(cat 2>/dev/null)"
[ -z "$INPUT" ] && exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Parse transcript_path via python3 (present per platform facts); fall back to jq.
TRANSCRIPT=""
if command -v python3 >/dev/null 2>&1; then
    TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c 'import sys, json
try:
    print(json.load(sys.stdin).get("transcript_path", "") or "")
except Exception:
    pass' 2>/dev/null)"
elif command -v jq >/dev/null 2>&1; then
    TRANSCRIPT="$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)"
fi

[ -z "$TRANSCRIPT" ] && exit 0
[ -f "$TRANSCRIPT" ] || exit 0

BACKUP_DIR="$PROJECT_DIR/.claude/session-context/backups"
mkdir -p "$BACKUP_DIR" 2>/dev/null || exit 0

DEST="$BACKUP_DIR/$(date +%Y%m%dT%H%M%S).jsonl"
cp "$TRANSCRIPT" "$DEST" 2>/dev/null || exit 0

exit 0
