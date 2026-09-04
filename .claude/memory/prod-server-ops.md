---
name: prod-server-ops
description: Prod server access & deploy facts for the Palimpsest demo (gse-translation.ru)
metadata: 
  node_type: memory
  type: project
  originSessionId: 885fa765-6e1c-44ca-879b-c279775013c1
---

Prod for the demo is reachable from the owner's machine via `ssh BioAI-grader` **as root** (host ams-1-vm-zw7m, 72.56.109.228, gse-translation.ru). Cloud sessions CANNOT reach it (HTTPS-only egress) — deploys run only from local sessions or by the owner.

- Container `gse-demo` on docker network `grader-net`, port 8000, behind Caddy. Server has docker + git but **no node/npm and no repo checkout** — `/opt/gse-demo/app` is a plain rsynced tree; env lives in root-owned `/opt/gse-demo/env` (holds `DEMO_ADMIN_TOKEN` + `OPENROUTER_API_KEY`); data at `/opt/gse-demo/data`.
- Canonical rollout (documented in repo `deploy/README.md` since PR #6, 2026-07-06): local frontend build → rsync (excluding `.git`, `.env`, `.venv`, `node_modules`, `data`) → `ssh BioAI-grader 'REPO_DIR=/opt/gse-demo/app DATA_DIR=/opt/gse-demo/data SKIP_GIT=1 SKIP_NPM=1 bash -s' < deploy/update-server.sh`.
- Prod DB is live history: never reseed, never DELETE score/issue rows. Script backs up demo.db + runs additive migration; it also leaves `app.bak-*` tree backups in `/opt/gse-demo/`.
- Prod has a real OpenRouter key → live LLM paths (translate, live /evaluate) work there, unlike local no-key demo defaults.
- `/api/health` alone is NOT a deploy gate: 2026-07-06 the app deployed "healthy" but didn't render (missing `grounding_config` table → boot-critical 500; incident in repo `docs/known_issues.md`). Since PR #8 the deploy script ends with a 5-endpoint boot-critical smoke battery — script exit 0 is the real gate. After any deploy, still load the site in a browser.
- Local `.env` (gitignored) holds FRONTIER_API_KEY, OPENROUTER_API_KEY, OPENROUTER_BASE_URL — as of 2026-07-06.
