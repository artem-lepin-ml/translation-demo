#!/usr/bin/env bash
# migrate-claude-config.sh — pull global ~/.claude config into THIS repo's .claude/
# so cloud sessions (claude.ai/code) see it. Repo = single source of config in cloud.
#
# REUSABLE: run from the root of ANY repo you want to migrate. Idempotent (re-runnable).
# It copies + repaths the mechanical parts and prints a checklist of manual decisions.
#
#   cd <repo-root> && bash migrate-claude-config.sh
#
# Tune the SKILLS / AGENTS / COMMANDS / PLUGINS arrays below per repo.
set -euo pipefail

SRC="${CLAUDE_HOME:-$HOME/.claude}"
DST=".claude"

# ── what to bring in (edit per repo) ─────────────────────────────────────────
SKILLS=(verify-spec verify-pr looper playwright-cli)   # user skills this repo uses
AGENTS=(e2e-tester docs-keeper)                                  # user agents (project ones already in repo win)
COMMANDS=(looper)                                               # user slash-commands
HOOKS=()                                                        # portable SessionStart hooks (repo-relative logic only)
PLUGINS_MINIMAL=(superpowers feature-dev code-simplifier)       # + github is official/built-in

echo "→ SRC=$SRC   DST=$(pwd)/$DST"
[ -d "$SRC" ] || { echo "!! $SRC not found — run on the machine that has your global config"; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "!! run from inside a git repo"; exit 1; }

mkdir -p "$DST"/{skills,agents,commands,rules,hooks}

# ── 1. skills (with their own assets, e.g. verify-spec/aspects-catalog.md) ────
for s in "${SKILLS[@]}"; do
  if [ -d "$SRC/skills/$s" ]; then cp -R "$SRC/skills/$s" "$DST/skills/"; echo "  skill  ✓ $s"; fi
done

# ── 2. agents (do NOT clobber a project agent of the same name) ───────────────
for a in "${AGENTS[@]}"; do
  if [ -f "$SRC/agents/$a.md" ] && [ ! -f "$DST/agents/$a.md" ]; then
    cp "$SRC/agents/$a.md" "$DST/agents/"; echo "  agent  ✓ $a"
  elif [ -f "$DST/agents/$a.md" ]; then echo "  agent  = $a (project version kept)"; fi
done

# ── 3. commands ───────────────────────────────────────────────────────────────
for c in "${COMMANDS[@]}"; do
  if [ -f "$SRC/commands/$c.md" ]; then cp "$SRC/commands/$c.md" "$DST/commands/"; echo "  cmd    ✓ $c"; fi
done

# ── 4. portable hooks ─────────────────────────────────────────────────────────
for h in "${HOOKS[@]}"; do
  if [ -f "$SRC/hooks/$h" ]; then cp "$SRC/hooks/$h" "$DST/hooks/"; echo "  hook   ✓ $h"; fi
done

# ── 5. global CLAUDE.md → staged for inline merge into repo-root CLAUDE.md ─────
# NOTE (2026-07-04): the methodology now lives INLINE in the repo-root CLAUDE.md, not in a
# separate @-imported process doc — that @-import proved unreliable in cloud sessions. We
# stage the global CLAUDE.md beside the config; you merge it into the root CLAUDE.md by hand
# (see the checklist below), and we no longer emit a separate process doc.
if [ -f "$SRC/CLAUDE.md" ]; then
  cp "$SRC/CLAUDE.md" "$DST/global-CLAUDE.incoming.md"; echo "  proc   ✓ CLAUDE.md → .claude/global-CLAUDE.incoming.md (merge into root CLAUDE.md by hand)"
fi

# ── 6. REPATH hardcoded ~/.claude refs → repo-relative (the crux) ─────────────
# in-place, portable sed (works on BSD/macOS + GNU)
repath() { # $1 = file
  [ -f "$1" ] || return 0
  perl -0pi -e 's{~/\.claude/skills/verify-spec/aspects-catalog\.md}{.claude/skills/verify-spec/aspects-catalog.md}g;
                s{\$HOME/\.claude/skills/looper}{.claude/skills/looper}g;
                s{~/\.claude/skills/}{.claude/skills/}g;
                s{~/\.claude/agents/}{.claude/agents/}g;' "$1"
}
find "$DST/skills" "$DST/commands" -type f -name '*.md' -print0 2>/dev/null | while IFS= read -r -d '' f; do repath "$f"; done
repath "$DST/global-CLAUDE.incoming.md"
echo "  repath ✓ ~/.claude → .claude in skills/commands + staged global CLAUDE.md"

# ── 7. settings.json skeleton (MERGE by hand if one already exists) ───────────
cat > "$DST/settings.cloud.json" <<'JSON'
{
  "enabledPlugins": {
    "superpowers@superpowers-dev": true,
    "github@claude-plugins-official": true,
    "feature-dev@claude-plugins-official": true,
    "code-simplifier@claude-plugins-official": true
  },
  "extraKnownMarketplaces": {
    "superpowers-dev": { "source": { "source": "git", "url": "https://github.com/obra/superpowers.git" } }
  }
}
JSON
echo "  settings ✓ wrote .claude/settings.cloud.json (MERGE into .claude/settings.json — do not blind-overwrite)"

# ── 8. .mcp.json for standalone (non-plugin) MCP servers ──────────────────────
if [ ! -f ".mcp.json" ]; then
  cat > ".mcp.json" <<'JSON'
{
  "mcpServers": {
    "playwright":       { "command": "npx", "args": ["-y", "@playwright/mcp@latest", "--isolated"] },
    "chrome-devtools":  { "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"] }
  }
}
JSON
  echo "  mcp    ✓ wrote .mcp.json (playwright, chrome-devtools)"
else echo "  mcp    = .mcp.json exists — merge servers by hand"; fi

echo ""
echo "════════ MANUAL STEPS (per repo) ════════"
cat <<'TXT'
 [ ] settings.json: merge .claude/settings.cloud.json into .claude/settings.json.
     DROP machine-specific permission entries (absolute /Users/... paths, other-project git -C).
     DROP any local-path marketplace (source.path under /Users/...) — dead in cloud.
 [ ] CLAUDE.md (repo root): merge the staged .claude/global-CLAUDE.incoming.md INLINE into
     the root CLAUDE.md (methodology + process). Do NOT @-import a separate process doc —
     that import proved unreliable in cloud sessions (2026-07-04). Then delete the
     global/project-split prose that no longer applies (it described ~/.claude vs repo; now
     everything is in-repo).
 [ ] .claude/rules/: extract durable invariants from your auto-memory into small md files
     (one rule per file). Auto-memory (~/.claude/projects/<repo-hash>/memory/) is
     machine-path-bound and does NOT rehydrate in cloud — rules/ is the portable home.
 [ ] Environment (claude.ai UI, not the repo): Network=Custom + your API domains;
     env vars for API keys (no quotes); setup script (uv sync + npm ci + tail verify).
 [ ] Verify nothing else hardcodes ~/.claude:  grep -rn '~/.claude\|\$HOME/.claude\|/Users/' .claude/
 [ ] Commit .claude/ (+ .mcp.json + CLAUDE.md) to the branch that becomes the mirror.
TXT
echo "Done. Review .claude/ then commit."
