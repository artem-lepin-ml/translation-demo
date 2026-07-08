#!/usr/bin/env bash
# Smoke test: real CloseRouter calls on N paragraphs of local/qwen_par_by_par.
# Exercises scoring + derived artefacts end-to-end on real LLM responses.
# Output: tests/.scoring_smoke/evaluation/ (gitignored, off the real pilot tree).
#
# Resume: load_existing_ids skips paragraphs already on disk; re-run safely.
# To start fresh: rm -rf tests/.scoring_smoke/evaluation/
#
# Tune: MAX_PARAGRAPHS=20 MAX_CONCURRENCY=2 bash scripts/03_scoring_smoke.sh
set -euo pipefail

CONFIG=configs/scoring/smoke.yaml
N="${MAX_PARAGRAPHS:-10}"
CONC="${MAX_CONCURRENCY:-4}"
LOG=tests/.scoring_smoke/smoke.log

mkdir -p "$(dirname "$LOG")"
echo "[smoke] $(date +%H:%M:%S) config=$CONFIG n=$N concurrency=$CONC"

uv run python scripts/03_translation_scoring.py \
  --config "$CONFIG" \
  --max-paragraphs "$N" \
  --max-concurrency "$CONC" \
  >>"$LOG" 2> >(tee -a "$LOG" >&2)

echo "[smoke] $(date +%H:%M:%S) done. Output: tests/.scoring_smoke/evaluation/"
