# Deploy — owner server update script

**This directory is for the owner's own server (`72.56.109.228`, `gse-translation.ru`) only.** It is not part of CI and is not run by any agent automatically — the owner runs it by hand (or via a trigger they set up themselves) after merging a PR into `dev-demo`.

## What it does

[`update-server.sh`](update-server.sh) brings the running `gse-demo` container up to date with `dev-demo` after a merge:

1. `git pull` the target branch (default `dev-demo`).
2. `npm run build` the frontend.
3. Back up `demo.db` (`demo.db.bak-<unix-ts>`) before touching anything.
4. `docker build` the image and restart **only** the `gse-demo` container — `gse-viewer` and any other container on `grader-net` are left alone.
5. Run the additive schema migration (`python -m palimpsest.webapp.migrate`) against the live DB, via a one-shot container, before the new server starts serving requests.
6. Disable the retired `cultural` (Cultural Adaptation) criterion on prod data — `UPDATE criterion SET enabled=0`, never `DELETE` (score/issue history referencing it is irreproducible — see the repo-root invariants).
7. Force `temperature: 0` on the 5 demo OpenRouter model rows via the live API (judge determinism for the recorded demo), preserving every other param and the existing API key.

Every step is idempotent — re-running the script after a partial failure is safe (git pull is a no-op if already up to date, the migration is additive-only, the criterion UPDATE is a no-op if already disabled, and the temperature PUT is a no-op if already 0).

## Caddy

No Caddy configuration change is needed. The container keeps its name (`gse-demo`), port (`8000`) and `grader-net` membership across the rebuild, so the existing site block (`gse-translation.ru -> gse-demo:8000`) keeps routing correctly.

## Usage

```bash
# On the server, as the user that owns the grader-net docker network:
cd ~/translation-demo   # or set REPO_DIR
OPENROUTER_API_KEY=<key> ./deploy/update-server.sh
```

Environment variables (all optional, sane defaults for the current deployment):

| Variable | Default | Meaning |
|---|---|---|
| `REPO_DIR` | `$HOME/translation-demo` | Checkout to pull/build from |
| `DEPLOY_BRANCH` | `dev-demo` | Branch to deploy |
| `DATA_DIR` | `/srv/gse-demo/data` | Host dir mounted at `/data` in the container (holds `demo.db`, `budget_calls.jsonl`) |
| `CONTAINER_NAME` | `gse-demo` | Container to rebuild/restart |
| `IMAGE_NAME` | `gse-demo` | Docker image tag |
| `NETWORK_NAME` | `grader-net` | Docker network the container joins |
| `API_PORT` | `8000` | Port the app listens on inside the container |
| `OPENROUTER_API_KEY` | *(empty)* | Passed through to the new container |

Adjust the defaults to match the actual host paths if they differ — this script was written from the deployment notes in [docs/subsystems/webapp.md](../docs/subsystems/webapp.md) ("Production container" section), not verified against a live shell on `72.56.109.228` in this PR.
