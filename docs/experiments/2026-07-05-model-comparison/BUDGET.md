# BUDGET — 2026-07-05-model-comparison

Hard limits. The loop stops when a cap is hit or the stop criterion is reached.

- **Max solution paths:** 4 (one per model; +1 route-substitution retry per model on deterministic failure).
- **Max retries per path:** 1 full re-run per model (only on infrastructure failure, never on "bad metrics").
- **Compute cap (wall-clock):** runs in background; hard stop 12 h after Ф3 launch
  (raised from 6 h after ticket 002's smoke measured ~14 min/article sequential grounding;
  ticket 002b adds article-level parallelism to bring a full run to ~3-5 h).
- **Token/money ceiling:** **$60 total** (owner, 2026-07-05); per-run `--max-usd 12`; triage ≤ $2.
- **Stop-criterion metric:** metrics.json produced for all 4 models (or documented drop-out) — then Ф4 report.
