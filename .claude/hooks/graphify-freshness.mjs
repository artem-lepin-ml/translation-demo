#!/usr/bin/env node
// SessionStart hook: remind to build/refresh the graphify knowledge graph.
// Any error → silent exit (never break a session).
// Covers two layouts: (a) CWD is inside a git repo; (b) CWD is a parent folder
// of project repos (e.g. ~/Projects/Startup) — scan first-level subdirs.
import { execSync } from 'node:child_process';
import { existsSync, statSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const K_COMMITS = 20;
const DENYLIST = []; // absolute repo-root paths to never remind about
const MAX_SUBDIR_REPORTS = 3; // cap the parent-folder summary

const sh = (cmd) => execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
const inject = (text) => process.stdout.write(JSON.stringify({
  hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: text },
}));

// Returns: null (skip silently) | {kind:'missing'} | {kind:'stale', commits:N}
function graphStatus(root) {
  if (DENYLIST.includes(root)) return null;
  // worktree → the graph lives in the main repo; stay silent
  const gitDir = sh(`git -C "${root}" rev-parse --git-dir`);
  const commonDir = sh(`git -C "${root}" rev-parse --git-common-dir`);
  if (gitDir !== commonDir) return null;
  const graph = join(root, 'graphify-out', 'graph.json');
  if (!existsSync(graph)) return { kind: 'missing' };
  const mtime = Math.floor(statSync(graph).mtimeMs / 1000);
  const newer = parseInt(sh(`git -C "${root}" rev-list --count --since=${mtime} HEAD`), 10);
  if (Number.isFinite(newer) && newer > K_COMMITS) return { kind: 'stale', commits: newer };
  return null;
}

try {
  let root = null;
  try { root = sh('git rev-parse --show-toplevel'); } catch { /* not inside a repo */ }

  if (root) {
    const st = graphStatus(root);
    if (st?.kind === 'missing') {
      inject(`В проекте ${root} нет графа знаний graphify. Построй его фоновым агентом на модели sonnet (жёсткий кап — не opus/fable) через Skill: /graphify ${root} — не блокируя основную работу.`);
    } else if (st?.kind === 'stale') {
      try { sh('pgrep -f graphify'); process.exit(0); } catch { /* not running — ok */ }
      inject(`Граф знаний graphify устарел: ${st.commits} коммитов после последней сборки. Запусти фоновым агентом на модели sonnet (жёсткий кап — не opus/fable) /graphify ${root} --update.`);
    }
    process.exit(0);
  }

  // CWD is not a repo → scan first-level subdirs for git repos (parent-folder layout)
  const cwd = process.cwd();
  const findings = [];
  for (const name of readdirSync(cwd)) {
    if (name.startsWith('.') || findings.length >= MAX_SUBDIR_REPORTS) continue;
    const dir = join(cwd, name);
    try {
      if (!statSync(dir).isDirectory() || !existsSync(join(dir, '.git'))) continue;
      const st = graphStatus(dir);
      if (st?.kind === 'missing') findings.push(`${name} — графа нет → /graphify ${dir}`);
      else if (st?.kind === 'stale') findings.push(`${name} — граф устарел на ${st.commits} коммитов → /graphify ${dir} --update`);
    } catch { /* skip dir */ }
  }
  if (findings.length) {
    try { sh('pgrep -f graphify'); process.exit(0); } catch { /* not running — ok */ }
    inject(`Графы знаний graphify в проектах этой папки требуют внимания (построй фоновым агентом на модели sonnet — жёсткий кап, не opus/fable — не блокируя работу): ${findings.join('; ')}`);
  }
} catch { /* silent */ }
process.exit(0);
