#!/usr/bin/env node
// Minimal stdio JSON-RPC 2.0 MCP server whose sole purpose is to keep the
// vendored pxpipe proxy alive for the whole Claude Code session.
//
// Zero tools are exposed (tools/list -> {tools: []}) — this server is
// invisible in the UI. It exists only because MCP servers persist for the
// life of a session in a way a SessionStart-hook-spawned background process
// may not.
//
// No third-party imports. Framing: newline-delimited JSON, one JSON object
// per line, on stdin/stdout — stdout carries ONLY JSON-RPC; all diagnostics
// go to STATE_DIR/supervisor.log.

import { appendFileSync, mkdirSync, readFileSync } from 'node:fs';
import readline from 'node:readline';
import { ensureUp, STATE_DIR, PORT } from './ensure-pxpipe.mjs';

mkdirSync(STATE_DIR, { recursive: true });

function log(msg) {
  try {
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    appendFileSync(`${STATE_DIR}/supervisor.log`, line);
  } catch {
    // logging must never crash the supervisor
  }
}

function send(obj) {
  try {
    process.stdout.write(`${JSON.stringify(obj)}\n`);
  } catch (err) {
    log(`send failed: ${err && err.message ? err.message : err}`);
  }
}

async function monitorTick() {
  try {
    const result = await ensureUp();
    if (result.alreadyRunning) {
      // healthy, nothing to do
      return;
    }
    if (result.started) {
      log(`respawned pxpipe on :${PORT} (pid ${result.pid}, models=${result.models})`);
    } else if (result.timedOut) {
      log(`respawn attempt did not become healthy within 15s (pid ${result.pid})`);
    } else if (result.error) {
      log(`respawn attempt failed: ${result.error}`);
    }
  } catch (err) {
    log(`monitor tick error: ${err && err.message ? err.message : err}`);
  }
}

function killPxpipe() {
  try {
    const pidPath = `${STATE_DIR}/pxpipe.pid`;
    const pidStr = readFileSync(pidPath, 'utf8').trim();
    const pid = Number(pidStr);
    if (Number.isInteger(pid) && pid > 0) {
      try {
        process.kill(pid, 'SIGTERM');
        log(`sent SIGTERM to pxpipe pid ${pid}`);
      } catch (err) {
        log(`kill pid ${pid} failed (best-effort): ${err && err.message ? err.message : err}`);
      }
    }
  } catch (err) {
    log(`could not read pidfile (best-effort): ${err && err.message ? err.message : err}`);
  }
}

let shuttingDown = false;
function shutdown(reason) {
  if (shuttingDown) return;
  shuttingDown = true;
  log(`shutting down (${reason})`);
  killPxpipe();
  clearInterval(monitorInterval);
  process.exit(0);
}

// --- MCP JSON-RPC handling -------------------------------------------------

function handleMessage(msg) {
  let req;
  try {
    req = JSON.parse(msg);
  } catch (err) {
    log(`parse error, ignoring line: ${err && err.message ? err.message : err}`);
    return;
  }

  if (!req || typeof req !== 'object' || Array.isArray(req)) {
    log('ignoring non-object JSON-RPC message');
    return;
  }

  const { id, method } = req;
  const isNotification = id === undefined;

  try {
    switch (method) {
      case 'initialize': {
        const clientProtocolVersion =
          req.params && req.params.protocolVersion ? req.params.protocolVersion : '2024-11-05';
        send({
          jsonrpc: '2.0',
          id,
          result: {
            protocolVersion: clientProtocolVersion,
            capabilities: {},
            serverInfo: { name: 'pxpipe-supervisor', version: '0.8.0' },
          },
        });
        break;
      }
      case 'notifications/initialized': {
        // no response expected
        break;
      }
      case 'tools/list': {
        send({ jsonrpc: '2.0', id, result: { tools: [] } });
        break;
      }
      case 'ping': {
        send({ jsonrpc: '2.0', id, result: {} });
        break;
      }
      default: {
        if (!isNotification) {
          send({
            jsonrpc: '2.0',
            id,
            error: { code: -32601, message: `Method not found: ${method}` },
          });
        } else {
          log(`ignoring unknown notification: ${method}`);
        }
      }
    }
  } catch (err) {
    log(`handler error for method ${method}: ${err && err.message ? err.message : err}`);
    if (!isNotification) {
      try {
        send({ jsonrpc: '2.0', id, error: { code: -32603, message: 'Internal error' } });
      } catch {
        // give up silently, never crash
      }
    }
  }
}

// --- startup ----------------------------------------------------------------

log('pxpipe-supervisor starting');

ensureUp()
  .then((result) => {
    if (result.alreadyRunning) {
      log(`startup: pxpipe already running on :${PORT}`);
    } else if (result.started) {
      log(`startup: pxpipe started on :${PORT} (pid ${result.pid}, models=${result.models})`);
    } else {
      log(`startup: pxpipe did not become healthy (${JSON.stringify(result)})`);
    }
  })
  .catch((err) => {
    log(`startup ensureUp threw: ${err && err.message ? err.message : err}`);
  });

const monitorInterval = setInterval(() => {
  monitorTick();
}, 10000);
// Don't let the monitor interval alone keep the process alive past stdin close.
monitorInterval.unref?.();

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on('line', (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  handleMessage(trimmed);
});
rl.on('close', () => shutdown('stdin closed'));

process.stdin.on('end', () => shutdown('stdin end'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('uncaughtException', (err) => {
  log(`uncaughtException: ${err && err.stack ? err.stack : err}`);
});
process.on('unhandledRejection', (err) => {
  log(`unhandledRejection: ${err && err.stack ? err.stack : err}`);
});
