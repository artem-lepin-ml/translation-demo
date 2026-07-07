#!/usr/bin/env bash
# Resume scoring for the pilot.
#
# One python invocation = one config = all (run x judge) pairs + factcheck.
# Python's run_scoring already runs judges + factcheck asyncronously and is
# idempotent (skips paragraph ids already present in *_scores.jsonl), so the
# only job of this shell wrapper is crash retries: API frequently drops the
# connection mid-run and we want to pick up where we left off.
#
# Crash recovery: python's exit code is the "done" marker. Exit 0 means
# run_scoring returned (all per-judge JSONLs written, merged_scores.jsonl
# rebuilt, scores.json updated). Non-zero exit means uncaught exception —
# sleep RETRY_SLEEP_SECS, retry up to MAX_RETRIES, then SKIP.
#
# Per-paragraph LLM errors do NOT crash python — they get a score=-1 row
# and the run continues. Only process-level crashes (network exhaustion,
# OOM, kill) trigger the shell-level retry.
#
# Configs are launched sequentially in priority order (P1 → P6) — all
# share the same judge profile, so parallel would only double-load the
# same provider quotas. Within one config, python's asyncio handles
# concurrency across runs × judges.
#
# Usage (from repo root):
#   bash scripts/03_scoring_resume.sh

set -uo pipefail

RETRY_SLEEP_SECS=20
MAX_RETRIES=20
MAX_CONCURRENCY="${MAX_CONCURRENCY:-4}"  # overrides yaml; lower to dodge 429.

# attempt_config: one yaml with retry-on-crash cap.
attempt_config() {
  local config_path="$1"
  local profile
  profile="$(basename "$config_path" .yaml)"
  local log_file="data/pilot/evaluation/${profile}.log"
  local prefix="[${profile}]"

  mkdir -p "$(dirname "$log_file")"

  local attempt=1
  while (( attempt <= MAX_RETRIES )); do
    echo "${prefix} $(date +%H:%M:%S) === attempt ${attempt}/${MAX_RETRIES}"
    local rc=0
    # stdout → log only (per-paragraph warnings, typer echos).
    # stderr → console + log (progress lines from run_scoring).
    uv run python scripts/03_translation_scoring.py \
      --config "$config_path" \
      --max-concurrency "$MAX_CONCURRENCY" \
      >>"$log_file" 2> >(tee -a "$log_file" >&2)
    rc=$?
    if (( rc == 0 )); then
      echo "${prefix} $(date +%H:%M:%S) done (exit 0)"
      return 0
    fi
    echo "${prefix} crashed (exit ${rc}); sleep ${RETRY_SLEEP_SECS}s; will retry $((attempt + 1))/${MAX_RETRIES} — see ${log_file}" >&2
    sleep "$RETRY_SLEEP_SECS"
    attempt=$((attempt + 1))
  done
  echo "${prefix} EXCEEDED ${MAX_RETRIES} retries — SKIPPING" >&2
  return 1
}

# ============================================================
# Priority-ordered scoring buckets for RQ1+RQ2 (large-low judge profile).
#
# All buckets share the same 3 judges (opus-low + gemini-pro-low + gpt-5.5-low)
# and the same factcheck judge (gpt-5.4-mini-low), so they MUST run sequentially
# — otherwise we double-load the same provider quotas. Within one bucket python's
# asyncio handles concurrency.
#
# Order = decreasing importance. Ctrl+C between buckets is safe — earlier
# scores.jsonl files stay on disk and resume picks up where it stopped.
# Comment out a line to skip that bucket on this pass.
#
# Bucket recap (see docs/experiments/2026-05-13-pilot-evaluation.md):
#   01-top-vs-baseline   — RQ2: large frontier -high par_by_par + Danil OSS (6 runs).
#   02-large-chunking    — RQ1: by_5_par, by_10_par for opus/gemini-pro/gpt-5.5 (6 runs).
#   03-small-anchor      — RQ2: small par_by_par per family (4 runs).
#   04-small-chunking    — RQ1: small by_10_par per family (4 runs).
#   05-family-and-alt    — RQ2: sonnet, gpt-5.4 within-family + deepseek/glm/qwen-plus (5 runs).
#   06-reasoning-low     — RQ2: -low reasoning par_by_par side-question (7 runs).
#
# Prereq for 01-top-vs-baseline: data/pilot/translating/local/qwen_edited_par_by_par/translation.md
# must exist (symlink to ../qwen_par_by_par/edited_translation.md). Created
# under spec docs/superpowers/specs/2026-05-13-pilot-evaluation-design.md § 3.
#
# large-low.yaml / small-low.yaml configs are kept for RQ3 correlation work,
# not part of main scoring.
# ============================================================

attempt_config configs/scoring/01-top-vs-baseline.yaml
attempt_config configs/scoring/02-large-chunking.yaml
attempt_config configs/scoring/03-small-anchor.yaml
attempt_config configs/scoring/04-small-chunking.yaml
attempt_config configs/scoring/05-family-and-alt.yaml
attempt_config configs/scoring/06-reasoning-low.yaml

echo "=== Scoring resume complete ==="
