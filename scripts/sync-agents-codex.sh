#!/bin/sh
# Sync .claude/skills/ -> .agents/skills/, the Agent Skills standard location
# Codex (and other non-Claude agents) discover. .agents/skills/ is a
# generated mirror, never edited directly and never committed (gitignored) —
# re-run this script any time .claude/skills/ changes.
#
# POSIX sh, idempotent, no network.
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)
src="$repo_root/.claude/skills"
dst="$repo_root/.agents/skills"

if [ ! -d "$src" ]; then
    echo "!! source dir missing: $src" >&2
    exit 1
fi

# Clean refresh so removed/renamed skills don't linger in the mirror.
rm -rf "$dst"
mkdir -p "$dst"

if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$src/" "$dst/"
else
    mkdir -p "$dst" && cp -R "$src/." "$dst/"
fi

count=$(find "$dst" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
echo "synced $count skill dir(s): $src -> $dst"

echo "NOTE: the following vendored skills carry Claude-oriented SKILL.md"
echo "frontmatter (fields Codex ignores, e.g. allowed-tools/trigger, or"
echo "content written for Claude Code specifically). Not forked, just FYI:"
echo "  - .claude/skills/superpowers/* (all subskills: brainstorming,"
echo "    writing-plans, subagent-driven-development, using-git-worktrees,"
echo "    dispatching-parallel-agents, finishing-a-development-branch,"
echo "    systematic-debugging)"
echo "  - .claude/skills/report-gen"
echo "  - .claude/skills/looper"
echo "  - .claude/skills/verify-pr"
echo "  - .claude/skills/verify-spec"
