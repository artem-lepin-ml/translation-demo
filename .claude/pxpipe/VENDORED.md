# Vendored: pxpipe proxy

- **Upstream:** [github.com/teamchong/pxpipe](https://github.com/teamchong/pxpipe)
- **Package:** `pxpipe-proxy@0.8.0`
- **Tarball sha256:** `ba3499d9ab3e4b6bbd9aeabce93be9beed46c084e6f50885c99f79792cf72686`
- **Vendored:** 2026-07-08, as a prebuilt self-contained bundle (no build step,
  no runtime `node_modules`). `dist/node.js` is an esbuild bundle with its one
  runtime dependency (`gpt-tokenizer`) inlined.
- **Version drift:** this package is 15 commits behind upstream's git HEAD.
  The `/v1/messages` routing behavior relevant to this integration is
  identical between the two — the commits ahead only touch the OpenAI-path
  handling, an `export` command fix, and a cosmetic `--version` string, none
  of which this integration uses.

## What's here

- `upstream/dist/` — the built proxy (`node.js` entry point, `core/*.js`,
  `dashboard/*.js`).
- `upstream/bin/` — the `pxpipe` CLI shim (not used directly; we invoke
  `upstream/dist/node.js` straight from [ensure-pxpipe.mjs](ensure-pxpipe.mjs)).
- `upstream/package.json`, `upstream/LICENSE`, `upstream/README.md` — as
  packed by npm, unmodified.
- `ensure-pxpipe.mjs` — idempotent launcher + readiness gate (also exports
  `ensureUp()` for reuse).
- `mcp-supervisor.mjs` — a zero-tool MCP server that keeps pxpipe alive for
  the session and cleans it up on shutdown.

**Do not edit vendored files under `upstream/`.** If a fix or upgrade is
needed, re-vendor from a fresh npm pack of `pxpipe-proxy` and update this
file's version/sha256/date.

## Security posture

- **No third-party egress.** pxpipe only talks to the configured upstream
  (`ANTHROPIC_UPSTREAM`, default `https://api.anthropic.com`) — it does not
  phone home or fetch anything else over the network.
- **No install/postinstall scripts.** The vendored bundle is copied files
  only; nothing runs `npm install` against it, so no supply-chain script
  execution happens at vendor time or at runtime.
- **No `eval`/`exec`-with-shell.** The proxy is a plain HTTP request/response
  pipeline; it does not shell out or evaluate untrusted strings.
- **Single runtime dependency, bundled.** `gpt-tokenizer` is inlined into
  `dist/node.js` at build time — there is no live `node_modules` resolution
  to tamper with.

### Risks and how we mitigate them

1. **On any 4xx response, pxpipe persists the full request body to disk**
   (`PXPIPE_LOG`'s directory) for debugging. We relocate `PXPIPE_LOG` to
   `/tmp/pxpipe/events.jsonl` (ephemeral, outside the repo) instead of the
   upstream default `~/.pxpipe/events.jsonl`, so captured bodies never land
   in a git-tracked location and don't survive past the container's life.
2. **The built-in dashboard is unauthenticated.** We bind `HOST=127.0.0.1`
   unconditionally (loopback only) — the dashboard is never reachable
   off-host.
3. **Imaging bulky context to PNG is a lossy transform for exact strings**
   (it trades some read fidelity for token savings). We gate it to
   `PXPIPE_MODELS=claude-fable-5` only — Fable is pxpipe's strongest reader
   of rendered pages — and every other model (Opus, Sonnet, Haiku, all
   subagents) passes through byte-identical, uncompressed.
4. **Rendered pages carry banners instructing the model to treat the image
   as authoritative context.** This is inherent to how pxpipe works (it's
   the mechanism the token savings come from), not a bug — the owner has
   reviewed and accepted this behavior for the Fable-only path.

See [docs/subsystems/pxpipe-proxy.md](../../docs/subsystems/pxpipe-proxy.md)
for the owner-facing activation and verification runbook.
