# Deploy — owner server update script

**This directory is for the owner's own server (`72.56.109.228`, `gse-translation.ru`) only.** It is not part of CI and is not run by any agent automatically — the owner runs it by hand (or via a trigger they set up themselves) after merging a PR into `dev-demo`.

## What it does

[`update-server.sh`](update-server.sh) brings the running `gse-demo` container up to date with `dev-demo` after a merge:

1. `git pull` the target branch (default `dev-demo`) — skipped with `SKIP_GIT=1` (the live `/opt/gse-demo/app` is a plain rsynced tree with no `.git`).
2. `npm run build` the frontend — skipped with `SKIP_NPM=1` (the live host has no node/npm); when skipped, the script fails loudly if `frontend/dist` is missing instead of deploying a stale build.
3. Back up `demo.db` (`demo.db.bak-<unix-ts>`) before touching anything.
4. `docker build` the image and restart **only** the `gse-demo` container — `gse-viewer` and any other container on `grader-net` are left alone. The container is started with `--restart unless-stopped` (matching every other container on the host — `caddy`, `gse-viewer`, `bioproverka-web` — so a host reboot brings it back automatically; see [docs/known_issues.md](../docs/known_issues.md) for the 2026-08-18→2026-08-26 outage this fixes) and `--env-file "$ENV_FILE"` (default `/opt/gse-demo/env`, root-owned mode 600 on the live host), so it keeps `DEMO_ADMIN_TOKEN` and anything else the owner keeps in that file across a rebuild; an explicit `-e OPENROUTER_API_KEY=...` is added on top when that var is set, overriding the file's copy per docker semantics.
5. Run the additive schema migration (`python -m palimpsest.webapp.migrate`) against the live DB, via a one-shot container, before the new server starts serving requests.
6. Smoke-test the frontend's boot-critical GET endpoints inside the new container — `/api/documents`, `/api/criteria`, `/api/models`, `/api/grounding-config`, `/api/translator-config` — each must answer `200`; any other status names the failing endpoint and aborts the deploy (`exit 1`) before it reaches prod (this is the gate that would have caught the `grounding_config` migration gap — see [docs/known_issues.md](../docs/known_issues.md)).
7. Disable the retired `cultural` (Cultural Adaptation) criterion on prod data — `UPDATE criterion SET enabled=0`, never `DELETE` (score/issue history referencing it is irreproducible — see the repo-root invariants).
8. Force `temperature: 0` on the demo OpenRouter model rows (paper registry) via the live API (judge determinism for the recorded demo), preserving every other param and the existing API key.

Every step is idempotent — re-running the script after a partial failure is safe (git pull is a no-op if already up to date, the migration is additive-only, the criterion UPDATE is a no-op if already disabled, and the temperature PUT is a no-op if already 0).

## Caddy

No Caddy configuration change is needed. The container keeps its name (`gse-demo`), port (`8000`) and `grader-net` membership across the rebuild, so the existing site block (`gse-translation.ru -> gse-demo:8000`) keeps routing correctly.

## Usage

**Verified rollout flow** (matches the live host: `/opt/gse-demo/app` is a plain rsynced tree with no `.git`, and the server has no node/npm — verified over SSH on 2026-07-06). Build locally, rsync the tree, run the script with steps 1–2 skipped:

```bash
# 1. Locally: build the frontend
(cd frontend && npm ci && npm run build)

# 2. Locally: rsync the tree to the server (data/ and node_modules never travel;
#    .env is excluded because it holds real API keys and must never reach the server tree)
rsync -a --delete --exclude .git --exclude .env --exclude .venv --exclude node_modules --exclude data \
    ./ BioAI-grader:/opt/gse-demo/app/

# 3. Run the update script on the server with git/npm steps skipped
ssh BioAI-grader 'REPO_DIR=/opt/gse-demo/app DATA_DIR=/opt/gse-demo/data SKIP_GIT=1 SKIP_NPM=1 bash -s' \
    < deploy/update-server.sh
```

**Alternative: git-pull flow** — for a host that has a git checkout plus node/npm:

```bash
# On the server, as the user that owns the grader-net docker network:
cd ~/translation-demo   # or set REPO_DIR
OPENROUTER_API_KEY=<key> ./deploy/update-server.sh
```

Environment variables (all optional, sane defaults for the current deployment):

| Variable | Default | Meaning |
|---|---|---|
| `REPO_DIR` | `$HOME/translation-demo` | Checkout to pull/build from |
| `DEPLOY_BRANCH` | `dev-demo` | Branch to deploy (git-pull flow only) |
| `SKIP_GIT` | `0` | `1` = skip step 1 (git pull) — for the rsync-deployed tree without a `.git` |
| `SKIP_NPM` | `0` | `1` = skip step 2 (npm build) — for hosts without node/npm; requires a prebuilt `frontend/dist` in the tree |
| `DATA_DIR` | `/opt/gse-demo/data` | Host dir mounted at `/data` in the container (holds `demo.db`, `budget_calls.jsonl`) — verified against the live `gse-demo` bind mount on 2026-07-06 |
| `CONTAINER_NAME` | `gse-demo` | Container to rebuild/restart |
| `IMAGE_NAME` | `gse-demo` | Docker image tag |
| `NETWORK_NAME` | `grader-net` | Docker network the container joins |
| `API_PORT` | `8000` | Port the app listens on inside the container |
| `ENV_FILE` | `/opt/gse-demo/env` | Root-owned, mode 600 file passed to the container via `--env-file`; carries `DEMO_ADMIN_TOKEN` and `OPENROUTER_API_KEY` on the live host. If it exists but isn't readable by the user running the script, the script warns loudly instead of silently dropping those vars. |
| `OPENROUTER_API_KEY` | *(empty)* | When set, added as an explicit `-e OPENROUTER_API_KEY=...` on top of `--env-file`, overriding the file's copy |

`DATA_DIR` and the `--env-file`/`ENV_FILE` behavior above were verified against a live shell on `72.56.109.228` (container `gse-demo`) on 2026-07-06. The remaining defaults still come from the deployment notes in [docs/subsystems/webapp.md](../docs/subsystems/webapp.md) ("Production container" section).
