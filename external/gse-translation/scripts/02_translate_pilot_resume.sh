#!/usr/bin/env bash
# Resume the large-model pilot.
#
# Parallel execution: up to MAX_PARALLEL_MODELS different models in flight
# at the same time. Chunkings within one model stay serial (we never have
# two variants of the same model talking to the provider at once).
#
# Crash recovery: each individual run uses translation.md as the
# "finished" marker. If the marker exists before the script starts the run
# is skipped entirely (saves tokens on already-done work). Otherwise the
# python script is invoked; if it exits without writing translation.md
# (dropped API connection, killed process), the script sleeps 60s and
# re-invokes — up to MAX_RETRIES times. progress.jsonl on the python side
# skips already-translated chunks across retries. A run that hits the cap
# is logged and SKIPPED, the script moves on.
#
# A run that finishes with partial validation failures (translation.md
# present, python exit 1) is treated as done — see failure_debug/.
#
# Usage (from repo root):
#   bash scripts/02_translate_pilot_resume.sh

set -uo pipefail

RU_MD="data/pilot/pilot_original.md"
CHUNK_DIR="data/pilot/chunking/for_translation"
SYS_PROMPT_PAR="02_translate/system.md"
USER_PROMPT_PAR="02_translate/user.md"
SYS_PROMPT_CHUNK="02_translate/chunked_system.md"
USER_PROMPT_CHUNK="02_translate/chunked_user.md"

RETRY_SLEEP_SECS=20
MAX_RETRIES=20
MAX_PARALLEL_MODELS=3
# Per-run concurrency cap on the python side (asyncio.Semaphore in
# translate.py). MAX_PARALLEL_MODELS × MAX_CONCURRENCY ≈ requests
# in flight against the provider — keep small to dodge 429.
MAX_CONCURRENCY=5

# attempt_run: one (model, chunking) pair with retry-on-crash cap.
attempt_run() {
  local model_key="$1"
  local chunking_name="$2"
  local sys_prompt="$3"
  local user_prompt="$4"
  local bucket="$5"

  local run_name="${model_key}_${chunking_name}"
  local out_dir="data/pilot/translating/${bucket}/${run_name}"
  local marker="${out_dir}/translation.md"
  local prefix="[${run_name}]"

  if [[ -f "$marker" ]]; then
    echo "${prefix} skip — translation.md already exists"
    return 0
  fi

  mkdir -p "$out_dir"
  local log_file="${out_dir}/run.log"
  echo "${prefix} start"
  local attempt=1
  while (( attempt <= MAX_RETRIES )); do
    local rc=0
    uv run python scripts/02_translate.py \
      --model "$model_key" \
      --chunking "$CHUNK_DIR/${chunking_name}.json" \
      --run-name "$run_name" \
      --bucket "$bucket" \
      --system-prompt "$sys_prompt" \
      --user-prompt "$user_prompt" \
      --max-concurrency "$MAX_CONCURRENCY" \
      --ru-md "$RU_MD" >>"$log_file" 2>&1 || rc=$?
    if [[ -f "$marker" ]]; then
      echo "${prefix} done (attempt ${attempt}/${MAX_RETRIES}, exit ${rc})"
      return 0
    fi
    echo "${prefix} retry ${attempt}/${MAX_RETRIES} after ${RETRY_SLEEP_SECS}s (see ${log_file})" >&2
    sleep "$RETRY_SLEEP_SECS"
    attempt=$((attempt + 1))
  done
  echo "${prefix} EXCEEDED ${MAX_RETRIES} retries — SKIPPING" >&2
  return 1
}

# run_model_serial: take a model_key + bucket + list of "chunking:prompt_kind"
# tokens and run them one after another for this model.
#   prompt_kind ∈ {par, chunk}.
run_model_serial() {
  local model_key="$1"
  local bucket="$2"
  shift 2
  local spec chunking_name prompt_kind
  for spec in "$@"; do
    IFS=':' read -r chunking_name prompt_kind <<< "$spec"
    if [[ "$prompt_kind" == "par" ]]; then
      attempt_run "$model_key" "$chunking_name" "$SYS_PROMPT_PAR" "$USER_PROMPT_PAR" "$bucket" || true
    else
      attempt_run "$model_key" "$chunking_name" "$SYS_PROMPT_CHUNK" "$USER_PROMPT_CHUNK" "$bucket" || true
    fi
  done
}

# launch_model: dispatch run_model_serial in the background, blocking
# until a slot opens up in the model-level semaphore. macOS-bash-3.2
# compatible (no `wait -n`).
launch_model() {
  while (( $(jobs -rp | wc -l) >= MAX_PARALLEL_MODELS )); do
    sleep 5
    jobs > /dev/null  # reap finished jobs so the counter is accurate
  done
  run_model_serial "$@" &
}

ALL_CHUNKINGS=("par_by_par:par" "by_5_par:chunk" "by_10_par:chunk")
SMALL_CHUNKINGS=("par_by_par:par" "by_10_par:chunk")

# ============================================================
# All remaining runs, ordered fastest → slowest.
# Pre-check inside attempt_run skips any run whose translation.md
# already exists, so re-launching after partial completion is safe.
# ============================================================

# ---- Small bucket (flash-lite + gpt-5.4-mini variants) ----
# NOTE: the non-preview slug `google/gemini-3.1-flash-lite` returns
# 400 invalid_request from the provider (model not found/unavailable).
# The earlier `gemini-3.1-flash-lite-minimal` run used the same slug and
# succeeded — provider either deprecated or temporarily pulled it. Only
# `-preview` variants are exercised here; if the non-preview slug comes
# back, re-add the two commented launches.

# ---- Slowest: deepseek-v4-pro and qwen3.6-plus ----
# launch_model deepseek-v4-pro            large "${ALL_CHUNKINGS[@]}"

launch_model qwen3.6-plus               large "par_by_par:par"

# launch_model gemini-3.1-flash-lite-preview       small "${SMALL_CHUNKINGS[@]}"
# # launch_model gemini-3.1-flash-lite-low           small "${SMALL_CHUNKINGS[@]}"
# launch_model gemini-3.1-flash-lite-preview-low   small "${SMALL_CHUNKINGS[@]}"
# # launch_model gemini-3.1-flash-lite-high          small "${SMALL_CHUNKINGS[@]}"
# launch_model gemini-3.1-flash-lite-preview-high  small "${SMALL_CHUNKINGS[@]}"
# launch_model gpt-5.4-mini-high                   small "${SMALL_CHUNKINGS[@]}"

# # ---- Large bucket: low-effort + GLM (medium runtime) ----

# launch_model gpt-5.5-low                large "${ALL_CHUNKINGS[@]}"
# launch_model claude-sonnet-4.6-low      large "${ALL_CHUNKINGS[@]}"
# launch_model claude-opus-4.7-low        large "${ALL_CHUNKINGS[@]}"
# launch_model glm-5.1                    large "par_by_par:par"

# # ---- Large bucket: high-effort (slower) ----
# # launch_model gpt-5.4-high               large "${ALL_CHUNKINGS[@]}"
# # launch_model gpt-5.5-high               large "${ALL_CHUNKINGS[@]}"
# # launch_model claude-sonnet-4.6-high     large "${ALL_CHUNKINGS[@]}"
# # launch_model gemini-3.1-pro-high        large "${ALL_CHUNKINGS[@]}"
# # launch_model claude-opus-4.7-high       large "${ALL_CHUNKINGS[@]}"

wait
echo "=== Resume complete ==="
