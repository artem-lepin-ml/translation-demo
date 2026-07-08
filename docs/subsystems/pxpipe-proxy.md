# pxpipe proxy — token-saving compression for Fable calls

Up-link: [docs/README.md](../README.md).

## What it is

[pxpipe](https://github.com/teamchong/pxpipe) is a local HTTP proxy that sits
in front of the Anthropic API. It renders bulky context (system prompt, tool
docs, old history) as dense PNGs before forwarding a request, which cuts
input tokens on the model that reads it. It listens on
`127.0.0.1:47821`, intercepts `POST /v1/messages`, and forwards everything
else — including auth headers — unchanged to the real upstream.

It is vendored into this repo at [.claude/pxpipe/](../../.claude/pxpipe/); see
[VENDORED.md](../../.claude/pxpipe/VENDORED.md) for the exact version,
checksum and security posture.

**Why:** it only compresses requests to `claude-fable-5` (see "Fable-only
guarantee" below), so it saves tokens specifically on Fable — the model used
for orchestration, brainstorming and final aggregation in this project's
workflow (see the model-routing table in [CLAUDE.md](../../CLAUDE.md)).

## In-repo pieces (already wired, no action needed for these)

- **MCP supervisor** — `.claude/pxpipe/mcp-supervisor.mjs`, registered in
  [.mcp.json](../../.mcp.json) as the `pxpipe` server. It starts pxpipe on
  session start and keeps it alive for the session (a 10s health-check +
  respawn loop), then shuts it down when the session ends.
- **SessionStart readiness gate** — `.claude/pxpipe/ensure-pxpipe.mjs`,
  wired as a second `SessionStart` hook in
  [.claude/settings.json](../../.claude/settings.json). It idempotently
  starts pxpipe (or confirms it's already up) before the session's first API
  call, so the MCP supervisor and the hook never double-start it.

Both pieces call the same launch logic and default `PXPIPE_MODELS` to
`claude-fable-5` only.

## How to activate it in a cloud session (the one manual step)

The in-repo pieces start and keep pxpipe alive automatically, but they do
**not** point Claude Code's traffic at it — that requires an environment
variable, which only the owner can set from the cloud session's own
environment config (out of scope for anything in this repo, by design: no
`ANTHROPIC_BASE_URL` is set anywhere in `.claude/`).

In claude.ai/code, open the environment's **"Configure your environment"**
env config and add two variables:

```
ANTHROPIC_BASE_URL=http://127.0.0.1:47821
PXPIPE_MODELS=claude-fable-5
```

`ANTHROPIC_BASE_URL` redirects Claude Code's API calls through the local
proxy. `PXPIPE_MODELS` (redundant with the in-repo default, but explicit)
keeps the Fable-only gate visible in the env config itself.

## Important caveat — cloud routing is not yet confirmed

It is **not confirmed** that a claude.ai/code cloud session actually honors
`ANTHROPIC_BASE_URL`. The container sets
`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1`, and Anthropic's docs describe cloud
sessions calling the API from Anthropic-managed infrastructure — which may
bypass any locally-configured base URL entirely.

**On the first session after activating it, verify pxpipe is actually seeing
traffic** before relying on it for token savings (see below). If it stays
idle, the env var had no effect — this is harmless: traffic simply flows
normally through the standard path, with no compression and no savings.

## How to verify it works

1. **Dashboard.** From within the session:
   ```
   curl -s http://127.0.0.1:47821/ | head -c 200
   ```
   Should return the start of an HTML page (the pxpipe dashboard). This only
   confirms the proxy is *running*, not that traffic is flowing through it.

2. **Events log.** After a Fable turn or two:
   ```
   tail -f /tmp/pxpipe/events.jsonl
   ```
   Each compressed request appends one JSON line with a `reason` field
   describing what was imaged and the token delta. If this file stays empty
   after Fable activity, the cloud session is not routing through the proxy.

3. **Stats API.**
   ```
   curl -s http://127.0.0.1:47821/api/stats.json
   ```
   Reports aggregate savings if any requests have passed through.

## How to disable it

Any one of these fully disables compression without touching the in-repo
files:

- Set `PXPIPE_MODELS=off` in the env config.
- Remove `ANTHROPIC_BASE_URL` from the env config (Claude Code talks to the
  real API directly again).
- Set `PXPIPE_DISABLE=1` in the env config.

With none of `ANTHROPIC_BASE_URL`/`PXPIPE_MODELS` set, the MCP
supervisor and SessionStart hook still start pxpipe in the background (it's
harmless and loopback-only), but nothing routes through it, so it just idles.

## Fable-only guarantee

`PXPIPE_MODELS=claude-fable-5` is the default baked into both
`ensure-pxpipe.mjs` and `mcp-supervisor.mjs` — narrower than pxpipe's own
built-in default (`claude-fable-5,gpt-5.6`). Any request for a model whose
base name is not in `PXPIPE_MODELS` passes through byte-identical: Opus,
Sonnet, Haiku and every subagent call in this project's model-routing table
are never imaged, only Fable orchestration/brainstorm/aggregation turns are.

## Install it in another repository

A cloud session clones the repo fresh, so the `.claude/` wiring must live in
every repo where you want pxpipe. Two paths.

### Fast path — copy from this repo

1. Copy the whole proxy directory: `cp -r <this-repo>/.claude/pxpipe
   <target-repo>/.claude/` (≈14 MB, includes the vendored bundle + both
   scripts + `VENDORED.md`).
2. In `<target-repo>/.mcp.json`, add to `mcpServers`:
   `"pxpipe": { "command": "node", "args": [".claude/pxpipe/mcp-supervisor.mjs"] }`.
3. In `<target-repo>/.claude/settings.json`, append a second `SessionStart`
   entry whose command is
   `node "$CLAUDE_PROJECT_DIR/.claude/pxpipe/ensure-pxpipe.mjs"`.
4. Commit those three paths (the cloud only sees committed config).
5. Activate via the two env vars — see
   [How to activate it in a cloud session](#how-to-activate-it-in-a-cloud-session-the-one-manual-step).

### From scratch — re-vendor the bundle

Same as the fast path, but re-fetch the runtime instead of copying `upstream/`:

```bash
mkdir -p .claude/pxpipe/upstream
npm pack pxpipe-proxy@0.8.0
tar -xzf pxpipe-proxy-0.8.0.tgz
cp -r package/dist package/bin package/package.json package/LICENSE package/README.md .claude/pxpipe/upstream/
node .claude/pxpipe/upstream/dist/node.js --help   # prints usage → the bundle is standalone
```

Tarball sha256: `ba3499d9ab3e4b6bbd9aeabce93be9beed46c084e6f50885c99f79792cf72686`.
Then copy `ensure-pxpipe.mjs` + `mcp-supervisor.mjs` from this repo's
`.claude/pxpipe/` (≈40 and ≈90 lines, no dependencies) and do steps 2–5 above.

> **Environment scoping.** `ANTHROPIC_BASE_URL` in the env config applies to
> **every** session of that environment. If you open a repo *without* pxpipe in
> the same environment, the redirect still points at `:47821`, no proxy comes
> up, and API calls fail with connection-refused. Keep these two env vars in an
> environment used only for pxpipe-enabled repos, or set up a dedicated one.

## See also

- [.claude/pxpipe/VENDORED.md](../../.claude/pxpipe/VENDORED.md) — exact
  version, checksum, what's vendored, and the full security-risk mitigation
  list.
- [docs/known_issues.md](../known_issues.md) — the cloud-routing-unverified
  and 4xx-body-on-disk entries.
