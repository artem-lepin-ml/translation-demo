#!/usr/bin/env bash
# Idempotent update script for the Palimpsest demo's OWNER-OPERATED server
# (72.56.109.228, gse-translation.ru). Run this ON THAT SERVER, as the user
# that owns the `grader-net` docker network and the repo checkout — it is not
# meant for CI or for any other host.
#
# What it does, in order (safe to re-run — every step is idempotent):
#   1. git pull the target branch (default: dev-demo) — skipped when
#      SKIP_GIT=1 (the live /opt/gse-demo/app is a plain rsynced tree with
#      no .git; flow: build locally, rsync the tree over, then run this
#      script with SKIP_GIT=1 SKIP_NPM=1 — see deploy/README.md)
#   2. npm build the frontend — skipped when SKIP_NPM=1 (the live host has
#      no node/npm; frontend/dist must be built locally and rsynced in —
#      the script fails loudly if it is missing)
#   3. back up demo.db
#   4. docker build the gse-demo image and rebuild/restart ONLY that
#      container — gse-viewer and any other container on grader-net are
#      never touched. The container is started with --env-file "$ENV_FILE"
#      (default /opt/gse-demo/env, root-owned mode 600 on the live host —
#      this is how it carries DEMO_ADMIN_TOKEN across a rebuild), plus an
#      explicit -e OPENROUTER_API_KEY override when that var is set in this
#      script's own environment
#   5. run the additive schema migration (palimpsest.webapp.migrate) against
#      the live DB before the new container starts serving
#   6. disable the retired Cultural Adaptation criterion on PROD DATA
#      (UPDATE, never DELETE — score/issue history is irreproducible)
#   7. force temperature=0 on the demo model rows via the live API (judge
#      determinism for the recorded demo)
#
# Caddy: no config change needed — gse-demo keeps the same container name,
# port (8000) and grader-net membership, so the existing Caddy site block
# (gse-translation.ru -> gse-demo:8000) keeps routing correctly across a
# rebuild. This script does not touch Caddy.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/translation-demo}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-dev-demo}"
SKIP_GIT="${SKIP_GIT:-0}"                           # 1 = skip git pull (tree deployed by rsync, no .git)
SKIP_NPM="${SKIP_NPM:-0}"                           # 1 = skip npm build (no node on host; frontend/dist rsynced in)
DATA_DIR="${DATA_DIR:-/opt/gse-demo/data}"          # host dir mounted at /data in the container — verified against the live gse-demo mount on 2026-07-06
CONTAINER_NAME="${CONTAINER_NAME:-gse-demo}"
IMAGE_NAME="${IMAGE_NAME:-gse-demo}"
NETWORK_NAME="${NETWORK_NAME:-grader-net}"
API_PORT="${API_PORT:-8000}"
ENV_FILE="${ENV_FILE:-/opt/gse-demo/env}"           # root-owned, mode 600 on the live host — carries DEMO_ADMIN_TOKEN + OPENROUTER_API_KEY
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"

log() { printf '\n[update-server] %s\n' "$1"; }

cd "$REPO_DIR"

if [ "$SKIP_GIT" != "1" ]; then
    log "1/7 git pull origin $DEPLOY_BRANCH"
    git fetch origin "$DEPLOY_BRANCH"
    git checkout "$DEPLOY_BRANCH"
    git pull --ff-only origin "$DEPLOY_BRANCH"
else
    log "1/7 skipped (SKIP_GIT=1 — tree deployed by rsync)"
fi

if [ "$SKIP_NPM" != "1" ]; then
    log "2/7 npm build (frontend/dist)"
    (cd frontend && npm ci && npm run build)
else
    log "2/7 skipped (SKIP_NPM=1 — using prebuilt frontend/dist)"
    if [ ! -d "$REPO_DIR/frontend/dist" ]; then
        log "ERROR: frontend/dist missing — build locally before rsync"
        exit 1
    fi
fi

log "3/7 backup demo.db"
if [ -f "$DATA_DIR/demo.db" ]; then
    cp "$DATA_DIR/demo.db" "$DATA_DIR/demo.db.bak-$(date +%s)"
else
    echo "  (no existing demo.db at $DATA_DIR — first deploy, nothing to back up)"
fi

log "4/7 docker build $IMAGE_NAME"
docker build -t "$IMAGE_NAME" .

log "5/7 migrate the DB (one-shot container, before the new server starts)"
docker run --rm \
    -v "$DATA_DIR:/data" \
    -e PALIMPSEST_DB=/data/demo.db \
    "$IMAGE_NAME" \
    python -m palimpsest.webapp.migrate

log "restart ONLY $CONTAINER_NAME (gse-viewer / other grader-net containers untouched)"
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

ENV_ARGS=()
if [ -r "$ENV_FILE" ]; then
    ENV_ARGS+=(--env-file "$ENV_FILE")
elif [ -f "$ENV_FILE" ]; then
    log "WARNING: $ENV_FILE exists but is not readable by $(whoami) — env vars from it (e.g. DEMO_ADMIN_TOKEN) will be MISSING from the container. Run this script as a user that can read the file (it is root-owned mode 600 on the live host)."
fi
if [ -n "$OPENROUTER_API_KEY" ]; then
    ENV_ARGS+=(-e "OPENROUTER_API_KEY=$OPENROUTER_API_KEY")
fi

docker run -d --name "$CONTAINER_NAME" \
    --network "$NETWORK_NAME" \
    -v "$DATA_DIR:/data" \
    "${ENV_ARGS[@]}" \
    "$IMAGE_NAME"

log "waiting for $CONTAINER_NAME to answer on :$API_PORT"
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER_NAME" python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:$API_PORT/api/health', timeout=2)" \
        >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

log "6/7 disable the retired Cultural Adaptation criterion (UPDATE, never DELETE)"
python3 - "$DATA_DIR/demo.db" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
conn.execute("UPDATE criterion SET enabled=0 WHERE id='cultural'")
conn.commit()
print(f"  criterion 'cultural' rows updated: {conn.total_changes}")
conn.close()
PY

log "7/7 force temperature=0 on the demo model rows via the live API"
MODELS=(
    "anthropic/claude-haiku-4.5"
    "anthropic/claude-sonnet-5"
    "google/gemini-3.5-flash"
    "openai/gpt-5.4-mini"
    "qwen/qwen3.6-plus"
)
for name in "${MODELS[@]}"; do
    docker exec "$CONTAINER_NAME" python -c "
import json
import urllib.request

name = '$name'
api = 'http://localhost:$API_PORT'
with urllib.request.urlopen(f'{api}/api/models') as r:
    rows = json.load(r)
row = next((m for m in rows if m['name'] == name), None)
if row is None:
    print(f'  skip {name} — not present in the model registry')
else:
    params = dict(row['params'])
    params['temperature'] = 0
    body = json.dumps({'baseUrl': row['baseUrl'], 'params': params}).encode()
    req = urllib.request.Request(
        f'{api}/api/models/{name}', data=body, method='PUT',
        headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req)
    print(f'  {name}: temperature forced to 0')
"
done

log "done — $CONTAINER_NAME is running $DEPLOY_BRANCH with the migrated DB"
