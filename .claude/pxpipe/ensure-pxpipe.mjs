#!/usr/bin/env node
// Idempotent launcher + readiness gate for the vendored pxpipe proxy.
//
// Usage:
//   node ensure-pxpipe.mjs        # start pxpipe if not already running, wait for health
//
// Also exports `ensureUp()` so mcp-supervisor.mjs can reuse the exact same
// launch logic (startup + the 10s respawn monitor loop).
//
// Design constraints (see .claude/pxpipe/VENDORED.md for the full rationale):
//   - PXPIPE_MODELS defaults to 'claude-fable-5' only (Fable-only gate) — NOT
//     the upstream default, which also includes gpt-5.6.
//   - PXPIPE_LOG defaults under STATE_DIR (ephemeral /tmp), never the repo,
//     because pxpipe persists full 4xx request bodies to that path.
//   - HOST is always forced to 127.0.0.1 (loopback only, unauthenticated
//     dashboard must never be exposed).
//   - Must never throw uncaught and must never break the SessionStart hook:
//     pxpipe failing to start is non-fatal, traffic just isn't compressed.

import { spawn } from 'node:child_process';
import { mkdirSync, openSync, writeFileSync, closeSync, statSync, unlinkSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import http from 'node:http';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const PORT = process.env.PXPIPE_PORT || '47821';
export const STATE_DIR = process.env.PXPIPE_STATE_DIR || '/tmp/pxpipe';
export const ENTRY = path.resolve(HERE, 'upstream', 'dist', 'node.js');

function healthCheck(timeoutMs) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port: Number(PORT), path: '/', timeout: timeoutMs },
      (res) => {
        res.resume();
        resolve(true);
      },
    );
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
    req.on('error', () => resolve(false));
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function spawnPxpipe() {
  mkdirSync(STATE_DIR, { recursive: true });

  const logPath = path.join(STATE_DIR, 'proxy.log');
  const fd = openSync(logPath, 'a');

  const env = {
    ...process.env,
    HOST: '127.0.0.1',
    PORT,
    PXPIPE_MODELS: process.env.PXPIPE_MODELS || 'claude-fable-5',
    PXPIPE_LOG: process.env.PXPIPE_LOG || path.join(STATE_DIR, 'events.jsonl'),
  };

  const child = spawn(process.execPath, [ENTRY], {
    detached: true,
    stdio: ['ignore', fd, fd],
    env,
  });
  child.unref();

  try {
    writeFileSync(path.join(STATE_DIR, 'pxpipe.pid'), String(child.pid));
  } catch {
    // best-effort; a missing pidfile just means the supervisor can't clean up on shutdown
  }

  return { pid: child.pid, models: env.PXPIPE_MODELS };
}

/**
 * Ensure pxpipe is up: health-check first (idempotent — never double-start),
 * spawn detached if not, poll until healthy or timeout.
 *
 * Returns { started: boolean, alreadyRunning: boolean, pid?: number, models?: string }
 */
export async function ensureUp() {
  try {
    if (await healthCheck(1000)) {
      return { started: false, alreadyRunning: true };
    }

    mkdirSync(STATE_DIR, { recursive: true });
    const lockPath = path.join(STATE_DIR, 'spawn.lock');

    // Serialize concurrent launchers: the SessionStart hook and the MCP
    // supervisor both call ensureUp at session start. O_EXCL means exactly one
    // wins the lock and spawns; the others fall through to wait for health.
    let holdingLock = false;
    try {
      closeSync(openSync(lockPath, 'wx'));
      holdingLock = true;
    } catch {
      // Lock held by another launcher. Steal it only if it is stale (a crashed
      // launcher that never released) — a live spawn completes well under 20s.
      try {
        if (Date.now() - statSync(lockPath).mtimeMs > 20000) {
          unlinkSync(lockPath);
          closeSync(openSync(lockPath, 'wx'));
          holdingLock = true;
        }
      } catch {
        // could not steal; wait-only path below
      }
    }

    const releaseLock = () => {
      if (holdingLock) {
        try {
          unlinkSync(lockPath);
        } catch {
          // best-effort
        }
        holdingLock = false;
      }
    };

    let spawned;
    if (holdingLock) {
      // Double-checked: another launcher may have finished between our first
      // health check and acquiring the lock.
      if (await healthCheck(1000)) {
        releaseLock();
        return { started: false, alreadyRunning: true };
      }
      spawned = spawnPxpipe();
    }

    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      if (await healthCheck(1000)) {
        releaseLock();
        return spawned
          ? { started: true, alreadyRunning: false, pid: spawned.pid, models: spawned.models }
          : { started: false, alreadyRunning: true };
      }
      await sleep(300);
    }

    releaseLock();
    return {
      started: false,
      alreadyRunning: false,
      timedOut: true,
      pid: spawned && spawned.pid,
      models: spawned && spawned.models,
    };
  } catch (err) {
    return { started: false, alreadyRunning: false, error: String(err && err.message ? err.message : err) };
  }
}

async function main() {
  try {
    const result = await ensureUp();

    if (result.alreadyRunning) {
      console.log(`pxpipe: already running on :${PORT}`);
      process.exit(0);
    }

    if (result.started) {
      console.log(`pxpipe: started on :${PORT} (pid ${result.pid}, models=${result.models})`);
      process.exit(0);
    }

    if (result.timedOut) {
      console.error(`pxpipe: warning — did not become healthy on :${PORT} within 15s (pid ${result.pid}); continuing without it`);
      process.exit(0);
    }

    console.error(`pxpipe: warning — failed to start (${result.error || 'unknown error'}); continuing without it`);
    process.exit(0);
  } catch (err) {
    console.error(`pxpipe: warning — unexpected error (${err && err.message ? err.message : err}); continuing without it`);
    process.exit(0);
  }
}

// Only run when invoked directly (not when imported by mcp-supervisor.mjs)
const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  main();
}
