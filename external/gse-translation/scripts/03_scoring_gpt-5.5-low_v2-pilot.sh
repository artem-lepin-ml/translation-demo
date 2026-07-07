#!/usr/bin/env bash
# Focused scoring pass: gpt-5.5-low on the two pilot translations, v2 prompts
# (5 criteria; reworded v1 axes — consistency dropped before launch).
# Config: configs/scoring/gpt-5.5-low-v2-pilot.yaml. Resume-safe.

set -uo pipefail

CONFIG=configs/scoring/gpt-5.5-low-v2-pilot.yaml
RETRY_SLEEP_SECS=20
MAX_RETRIES=20
MAX_CONCURRENCY="${MAX_CONCURRENCY:-32}"

PROFILE="$(basename "$CONFIG" .yaml)"
LOG_FILE="data/pilot/evaluation/${PROFILE}.log"
mkdir -p "$(dirname "$LOG_FILE")"

attempt=1
while (( attempt <= MAX_RETRIES )); do
  echo "[${PROFILE}] $(date +%H:%M:%S) === attempt ${attempt}/${MAX_RETRIES}"
  uv run python scripts/03_translation_scoring.py \
    --config "$CONFIG" \
    --max-concurrency "$MAX_CONCURRENCY" \
    >>"$LOG_FILE" 2> >(tee -a "$LOG_FILE" >&2)
  rc=$?
  if (( rc == 0 )); then
    echo "[${PROFILE}] $(date +%H:%M:%S) done (exit 0)"
    exit 0
  fi
  echo "[${PROFILE}] crashed (exit ${rc}); sleep ${RETRY_SLEEP_SECS}s; retry $((attempt + 1))/${MAX_RETRIES} — see ${LOG_FILE}" >&2
  sleep "$RETRY_SLEEP_SECS"
  attempt=$((attempt + 1))
done

echo "[${PROFILE}] EXCEEDED ${MAX_RETRIES} retries" >&2
exit 1
