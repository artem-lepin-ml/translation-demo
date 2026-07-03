# `.claude/` — in-repo Claude Code config

Everything Claude Code needs lives **in this repo**, so cloud sessions (claude.ai/code)
work with no dependency on a machine-local `~/.claude`. The repository is the single
source of config in the cloud.

## Layout

| Path | What it is |
|---|---|
| `process.md` | The development process (8-step Scenario A/B, model routing, report template). `@`-imported from the root `CLAUDE.md`. Ex-global `~/.claude/CLAUDE.md`, repathed. |
| `rules/invariants.md` | Hard invariants that never expire (prediction preservation, `data/raw` immutability, LLM-via-client, English-only UI, commit rules). Portable home for what auto-memory used to hold — auto-memory does **not** rehydrate in cloud. |
| `rules/working-style.md` | Durable owner preferences (Russian owner-facing / English thinking, report palette, naming, PR style). |
| `agents/` | Project subagents: `docs-keeper`, `doc-syncer`, `e2e-tester`, `pr-writer`. |
| `skills/` | User skills this repo uses: `verify-spec` (+ `aspects-catalog.md`), `verify-pr`, `graphify`, `looper`, `playwright-cli`. |
| `commands/` | Slash commands (`looper`). |
| `hooks/` | Portable SessionStart hooks (`graphify-freshness.mjs`). |
| `settings.json` | Enabled plugins, marketplace, SessionStart hook wiring (via `$CLAUDE_PROJECT_DIR`). |
| `cloud-setup.sh` | Reference **Environment → Setup script** for claude.ai/code (deps baked into the snapshot). |
| `migrate-config.sh` | The reusable tool that produced this directory — see below. |

The root `CLAUDE.md` `@`-imports `process.md` and the two `rules/*` files, then adds only
repo-specific conventions. `.mcp.json` (repo root) declares the standalone MCP servers
(playwright, chrome-devtools).

## Reusing this in another repo

`migrate-config.sh` pulls a global `~/.claude` into a repo-local `.claude/` and repaths the
mechanical parts. It is **idempotent** and safe to re-run.

```bash
cd <other-repo-root>
bash /path/to/this/.claude/migrate-config.sh   # or copy the script in first
```

1. **Tune the arrays** at the top of the script (`SKILLS`, `AGENTS`, `COMMANDS`, `HOOKS`,
   `PLUGINS_MINIMAL`) to what that repo actually uses.
2. It copies skills (with their assets), agents (never clobbering a project agent of the
   same name), commands, hooks, and the global `CLAUDE.md` → `.claude/process.md`; then
   **repaths** every hardcoded `~/.claude/...` → `.claude/...` (the crux — cloud has no
   `$HOME/.claude`).
3. It writes `settings.cloud.json` and `.mcp.json` skeletons and prints a **manual
   checklist**: merge `settings.cloud.json` into `settings.json` (drop absolute
   `/Users/...` permission entries and any local-path marketplace — both dead in cloud),
   `@`-import `process.md` from the root `CLAUDE.md`, distil auto-memory into `rules/*.md`,
   and set up the cloud Environment (network + keys + setup script).
4. Sanity check before committing: `grep -rn '~/.claude\|\$HOME/.claude\|/Users/' .claude/`
   must come back empty.

## Cloud environment (set in the claude.ai UI, not in the repo)

- **Network:** Custom allowlist — extends Trusted (package registries + GitHub). Add only
  `openrouter.ai` and `api.openai.com`.
- **Env vars** (no quotes — quotes become part of the value): `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`.
- **Setup script:** paste `cloud-setup.sh` (bakes `uv sync` + `npm ci` + Playwright into
  the filesystem snapshot).
