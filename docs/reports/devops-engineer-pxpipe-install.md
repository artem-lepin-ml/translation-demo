# pxpipe proxy installation — devops-engineer report

## Scope

Vendor the prebuilt `pxpipe-proxy@0.8.0` bundle into `.claude/pxpipe/`, wire
an idempotent launcher + a zero-tool MCP supervisor so a fresh claude.ai/code
cloud session auto-starts and keeps it alive, gate compression to
`claude-fable-5` only, and document the owner's one manual activation step
(setting `ANTHROPIC_BASE_URL` in the cloud env config — not done from
within the repo, per the task's explicit exclusion). No commit was made;
everything is left in the working tree per the task instructions.

## Files changed

Created:
- `.claude/pxpipe/upstream/` — vendored bundle (`dist/`, `bin/`,
  `package.json`, `LICENSE`, `README.md`), copied verbatim from the packed
  npm tarball, untouched.
- `.claude/pxpipe/ensure-pxpipe.mjs` — idempotent launcher + readiness gate;
  exports `ensureUp()`, `STATE_DIR`, `PORT`, `ENTRY` for reuse.
- `.claude/pxpipe/mcp-supervisor.mjs` — hand-rolled stdio JSON-RPC 2.0 MCP
  server (zero tools, invisible in UI), session-long keep-alive + cleanup.
- `.claude/pxpipe/VENDORED.md` — provenance, version/sha256, security
  posture (English).
- `docs/subsystems/pxpipe-proxy.md` — owner runbook (English).

Edited:
- `.mcp.json` — added the `pxpipe` MCP server entry; the three existing
  servers (`playwright`, `chrome-devtools`, `context7`) are unchanged.
- `.claude/settings.json` — appended a second `SessionStart` hook entry
  (`node .../ensure-pxpipe.mjs`); the existing `session-context-pointer.py`
  hook and every other hook block are unchanged.
- `docs/README.md` — added one index row for the new runbook.
- `docs/known_issues.md` — added an entry: cloud base-URL honoring
  unverified + the 4xx-body-on-disk mitigation.

## Decisions & rationale

- **`ENTRY` path fix.** The task's parenthetical suggested computing `ENTRY`
  as `../upstream/dist/node.js` relative to `ensure-pxpipe.mjs`. Given the
  actual layout (`ensure-pxpipe.mjs` and `upstream/` are siblings, both
  directly under `.claude/pxpipe/`), the correct relative path is
  `./upstream/dist/node.js` — one level up would point outside
  `.claude/pxpipe/` entirely and fail. Implemented as
  `path.resolve(HERE, 'upstream', 'dist', 'node.js')`; verified working by
  actually starting the proxy (see Run artifacts below).
- **`SessionStart` hook placement.** The task said "APPEND a second hook
  object in the same SessionStart array." I read the outer `SessionStart`
  array (currently one element) as the "SessionStart array," so I appended
  a second top-level `{ "hooks": [...] }` entry as a sibling of the existing
  one, matching the multi-entry pattern already used by `PreToolUse` in the
  same file, rather than nesting a second command inside the existing
  entry's inner `hooks` list. Both hook groups now run on every
  `SessionStart` event; JSON validated after the edit.
- **Supervisor shutdown is real, not a stub.** Per spec, `mcp-supervisor.mjs`
  kills the pxpipe child (via the pidfile) on stdin close/SIGTERM/SIGINT.
  Verified this live: piping two JSON-RPC lines into the supervisor closed
  its stdin at EOF, which triggered a real `SIGTERM` to the running pxpipe
  process — confirmed the port freed immediately after. This is intended
  MCP-client behavior (client closes stdin when the server is no longer
  needed) but is worth flagging since it means running the supervisor
  standalone for a quick test, as step 6 instructs, has the side effect of
  killing any pxpipe instance it manages once the pipe closes.
- **No `ANTHROPIC_BASE_URL` anywhere in-repo.** Confirmed by grep across
  every file touched — the only occurrences are inside the vendored,
  untouched `upstream/README.md`/`upstream/dist/node.js` (upstream's own
  usage examples) and in the new documentation's prose describing what the
  *owner* must set externally.
- **`gpt-tokenizer` dependency.** Confirmed `dist/node.js` bundles it inline
  (20 references found in the 8 MB bundle, `node .../node.js --help` runs
  with zero `node_modules`) — no `npm install` was run, per the task.

## Open questions

- Whether claude.ai/code cloud sessions actually honor a locally-set
  `ANTHROPIC_BASE_URL` is unverified (flagged in both the runbook and
  `known_issues.md`, per the task's explicit instruction) — this can only be
  confirmed by the owner setting the env var and checking
  `/tmp/pxpipe/events.jsonl` growth in a live cloud session.

## NOT done (explicit)

- **Not committed.** All changes are left in the working tree, as instructed
  ("Do NOT commit — leave everything in the working tree").
- **Not tested against real Claude Code traffic.** Step 6 explicitly scoped
  verification to exercising pxpipe directly (health, dashboard, MCP
  handshake) — not to redirecting Claude's own `/v1/messages` traffic through
  it, which is out of scope here and depends on the owner's env-config step.
- **No `npm install`/build step run** — the bundle is standalone, as
  instructed.
- **`external/` untouched**, confirmed via `git status --porcelain -- external/`.

## Run artifacts (Step 6 verification — actual output)

**1. Vendoring sanity check (`node .../dist/node.js --help`):** exited 0,
printed full usage text including `PXPIPE_MODELS ... default
claude-fable-5,gpt-5.6; off disables`.

**2. Fresh start:**
```
$ node .claude/pxpipe/ensure-pxpipe.mjs
pxpipe: started on :47821 (pid 28655, models=claude-fable-5)
```

**3. Idempotent second run:**
```
$ node .claude/pxpipe/ensure-pxpipe.mjs
pxpipe: already running on :47821
```
Process list showed exactly one `upstream/dist/node.js` process before and
after — no duplicate spawned.

**4. Dashboard:**
```
$ curl -s http://127.0.0.1:47821/ | head -c 200
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>pxpipe — live dashboard</title>
<link rel="icon" href="
```

**5. `/tmp/pxpipe/` state dir:**
```
$ ls -la /tmp/pxpipe/
proxy.log
pxpipe.pid
```
(`events.jsonl` appears only after the first tracked request — confirmed via
`/api/stats.json` returning `{"error":"no events file yet", ...}` before any
traffic, which is correct pxpipe behavior, not a bug.)

**6. `PXPIPE_MODELS` confirmed in the actual child process environment**
(via `/proc/<pid>/environ`, since the proxy has no dedicated introspection
endpoint for its own env):
```
$ tr '\0' '\n' < /proc/28655/environ | grep PXPIPE_MODELS
PXPIPE_MODELS=claude-fable-5
```
Also confirmed `HOST=127.0.0.1` and `PXPIPE_LOG=/tmp/pxpipe/events.jsonl` in
the same environ dump — loopback bind and ephemeral log path both verified,
not just asserted.

**7. MCP handshake simulation:**
```
$ printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | timeout 5 node .claude/pxpipe/mcp-supervisor.mjs
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"pxpipe-supervisor","version":"0.8.0"}}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}
```
Two valid JSON-RPC responses, nothing else on stdout.

**8. Shutdown + port-free confirmation:**
The MCP handshake test's stdin EOF triggered the supervisor's shutdown path,
which sent `SIGTERM` to the pxpipe pid from the pidfile. Confirmed via
`supervisor.log`:
```
[...] pxpipe-supervisor starting
[...] shutting down (stdin closed)
[...] sent SIGTERM to pxpipe pid 25690
```
And confirmed the port actually freed:
```
$ (exec 3<>/dev/tcp/127.0.0.1/47821)
bash: connect: Connection refused   # PORT FREE
```
Re-ran the full fresh-start → dashboard → idempotent-check → explicit `kill`
sequence a second time from a clean `/tmp/pxpipe` to get an uncontaminated
final trace (pid 28655): dashboard responded, `PXPIPE_MODELS=claude-fable-5`
confirmed in environ, explicit `kill $(cat /tmp/pxpipe/pxpipe.pid)` was sent,
and `pgrep -af "upstream/dist/node.js"` plus a raw `/dev/tcp` connect attempt
both confirmed the process was gone and the port was free.

**9. JSON validation:**
```
$ node -e "JSON.parse(require('fs').readFileSync('.mcp.json','utf8')); console.log('.mcp.json OK')"
.mcp.json OK
$ node -e "JSON.parse(require('fs').readFileSync('.claude/settings.json','utf8')); console.log('.claude/settings.json OK')"
.claude/settings.json OK
```

**10. Final `git status --porcelain`:**
```
 M .claude/settings.json
 M .mcp.json
 M docs/README.md
 M docs/known_issues.md
?? .claude/pxpipe/
?? docs/subsystems/pxpipe-proxy.md
```
Nothing staged or committed, as instructed.

## File tree — `.claude/pxpipe/`

```
.claude/pxpipe/
├── VENDORED.md
├── ensure-pxpipe.mjs
├── mcp-supervisor.mjs
└── upstream/
    ├── LICENSE
    ├── README.md
    ├── package.json
    ├── bin/
    │   └── cli.js
    └── dist/
        ├── node.js            (8.0 MB, bundled entry point)
        ├── node.d.ts
        ├── dashboard.js
        ├── dashboard.d.ts
        ├── sessions.js / .d.ts
        ├── stats.js / .d.ts
        ├── worker.js / .d.ts
        ├── core/               (17 .js + .d.ts pairs)
        └── dashboard/          (fragments/types/vendor .js + .d.ts)
```
Total `.claude/pxpipe/` size: 14 MB.
