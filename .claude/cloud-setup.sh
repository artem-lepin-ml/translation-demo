# v1
# claude.ai/code Environment → Setup script for the Palimpsest demo.
# Bakes deps into the filesystem snapshot so sessions start ready.
# No `activate`: explicit .venv/bin/ + uv only.
#
# Network: Custom allowlist (extends Trusted). Add: openrouter.ai, api.openai.com.
# Env vars (no quotes — quotes become part of the value):
#   OPENAI_API_KEY   — the live key.
#   OPENROUTER_API_KEY is intentionally NOT set: seeded models then clean-cache-fallback.
#   A stale/dead OpenRouter key is worse than none (401 instead of cache-fallback).
set -euo pipefail

uv sync --extra dev                                     # .venv + runtime + dev extra (pytest, ruff)
( cd frontend && npm ci )                               # vitest, tsc, build deps
npx playwright install --with-deps chromium || true     # for later e2e; non-fatal if CDN blocked

# tail check via the venv interpreter (no activation)
.venv/bin/python -c "import palimpsest" || { echo "!! palimpsest import failed" >&2; exit 1; }
test -d frontend/node_modules || { echo "!! frontend node_modules missing" >&2; exit 1; }
echo "setup ok"
