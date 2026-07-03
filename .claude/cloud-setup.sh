#!/usr/bin/env bash
# Reference environment setup script for claude.ai/code.
# Paste this into the environment's Setup script field (UI). It bakes deps into the
# filesystem snapshot, so sessions start with everything installed.
#
# Network: Custom allowlist (extends Trusted, which already has package registries +
# GitHub). Add only: openrouter.ai, api.openai.com.
# Env vars: OPENROUTER_API_KEY, OPENAI_API_KEY (no quotes — quotes become part of the value).
set -euo pipefail

# backend (uv/node/pytest preinstalled in the cloud image)
uv sync || { uv venv .venv --python 3.13 && uv pip install -e ".[dev]"; }

# frontend
( cd frontend && npm ci )

# browser for playwright MCP/CLI (needs Playwright CDN in allowlist, or run first pass on Full)
npx playwright install --with-deps chromium || true

# honest tail check → a failed setup script does NOT fail the session, so signal in logs
python -c "import palimpsest" && test -d frontend/node_modules \
  || { echo "!! SETUP INCOMPLETE — palimpsest import or node_modules missing" >&2; exit 1; }
echo "setup ok"
