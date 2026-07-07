# Deploying the Translation Comparison Viewer

Up-link: [docs/pipeline.md](pipeline.md) · viewer detail [viewer/README.md](../viewer/README.md).

This doc covers production deploy of the viewer behind an existing Caddy reverse proxy on a remote host, with a one-command path for re-syncing evaluation data later.

## Topology

```
gse-translation.ru ──TLS──► Caddy (already running on the host)
                              │
                              └─reverse_proxy─► gse-viewer:8000  (this project)
```

The host already runs a Caddy container that owns ports 80/443 and joins a Docker network (default name `grader-net`, overridable via `PROXY_NETWORK`). We attach the viewer container to the same network and add one vhost block to Caddy's config — no port conflicts, no duplicate certificates.

## Prerequisites

On the host:

- Docker + Compose v2.
- A running reverse-proxy container on a known docker network (see env var `PROXY_NETWORK` below). The proxy must be able to obtain Let's Encrypt certificates for `gse-translation.ru`.
- DNS A-record `gse-translation.ru → <host IP>` already pointing at the host.

On your laptop:

- `rsync`, `ssh`.
- An SSH alias for the host in `~/.ssh/config`. Replace `<ssh-alias>` in the commands below with that alias.
- `GSE_DEPLOY_HOST=<ssh-alias>` either in your shell rc or passed per-call.

## Layout on the host

```
/srv/gse-translation/
├── app/                          # rsync'd from this repo (no .git, no data/, no .worktrees/)
│   ├── deploy/
│   │   ├── docker-compose.yml    # joins the external proxy network
│   │   └── Caddyfile.snippet     # vhost block to graft into the host Caddyfile
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/                      # palimpsest package
│   └── viewer/                   # backend + Dockerfile + frontend sources
└── data/
    └── pilot/
        └── evaluation/           # rsync'd separately so data updates don't redeploy code
```

The container reads evaluation files from `/data/pilot/evaluation` inside the container, bind-mounted from `$DATA_ROOT/pilot/evaluation` on the host (default `/srv/gse-translation/data`).

## One-time setup

```bash
# 1. Set your SSH alias (or export in your rc).
export GSE_DEPLOY_HOST=<ssh-alias>

# 2. First push: code + data + build + start.
./scripts/deploy_sync.sh --all

# 3. Attach the viewer's vhost to the host Caddyfile and reload.
ssh "$GSE_DEPLOY_HOST" bash <<'EOF'
SNIPPET=/srv/gse-translation/app/deploy/Caddyfile.snippet
CADDYFILE=/etc/caddy/Caddyfile

# Idempotent: skip if already present.
if ! grep -q 'gse-translation.ru' "$CADDYFILE"; then
  printf '\n' >> "$CADDYFILE"
  cat "$SNIPPET" >> "$CADDYFILE"
fi

# Validate, then live-reload (no downtime for existing vhosts).
docker exec caddy caddy validate --config "$CADDYFILE" --adapter caddyfile
docker exec caddy caddy reload   --config "$CADDYFILE" --adapter caddyfile
EOF

# 4. Smoke test.
curl -sSf -I https://gse-translation.ru
```

Caddy obtains the Let's Encrypt certificate on the first request to the new hostname; that may take a few seconds.

## Re-syncing data (the common case)

```bash
GSE_DEPLOY_HOST=<ssh-alias> ./scripts/deploy_sync.sh
```

Default mode is `--data`: it `rsync`s only `data/pilot/evaluation/` and finishes in seconds when nothing changed. The container reads JSONL on every request, so no restart is needed for data updates.

## Re-deploying code

```bash
GSE_DEPLOY_HOST=<ssh-alias> ./scripts/deploy_sync.sh --code
```

This `rsync`s sources, then runs `docker compose up -d --build` on the host. The viewer container is rebuilt and replaced; existing vhosts on the host are untouched.

## Mode summary

| Mode      | rsync code | rsync data | rebuild + restart |
| --------- | :--------: | :--------: | :---------------: |
| `--data` (default) | — | ✓ | — |
| `--code` | ✓ | — | ✓ |
| `--all`  | ✓ | ✓ | ✓ |

## Operations

```bash
# Status, logs, restart, stop.
ssh "$GSE_DEPLOY_HOST" 'docker compose -f /srv/gse-translation/app/deploy/docker-compose.yml ps'
ssh "$GSE_DEPLOY_HOST" 'docker compose -f /srv/gse-translation/app/deploy/docker-compose.yml logs --tail=200 viewer'
ssh "$GSE_DEPLOY_HOST" 'docker compose -f /srv/gse-translation/app/deploy/docker-compose.yml restart viewer'
ssh "$GSE_DEPLOY_HOST" 'docker compose -f /srv/gse-translation/app/deploy/docker-compose.yml down'
```

## Overrides

```bash
# Different proxy network name:
PROXY_NETWORK=my-proxy-net ./scripts/deploy_sync.sh --code

# Different remote root:
GSE_DEPLOY_REMOTE_ROOT=/opt/gse-translation ./scripts/deploy_sync.sh --all
```

`PROXY_NETWORK` is consumed by `deploy/docker-compose.yml`; export it into the container's compose env on the remote side too if you change it.

## Roll-back

```bash
# Stop the viewer (proxy keeps serving other vhosts).
ssh "$GSE_DEPLOY_HOST" 'docker compose -f /srv/gse-translation/app/deploy/docker-compose.yml down'

# Drop the vhost from Caddy if you want the domain offline.
ssh "$GSE_DEPLOY_HOST" "sed -i.bak '/gse-translation\.ru {/,/^}/d' /etc/caddy/Caddyfile && \
  docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile"
```
