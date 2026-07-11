# Opus-4.8 CloseRouter provider sweep — raw artifacts

Raw evidence for the provider sweep summarized in
[docs/reports/ml-engineer-grounding-run-opus48.md](../../reports/ml-engineer-grounding-run-opus48.md)
("Provider sweep" section) — the narrative, the full matrix, and the decision
outcome (Opus dropped from Table C, 2026-07-09) live there; this directory is
raw reproducibility material only, per the project's single-source-of-truth
convention.

`raw/`:
- `opus48_providers.json` — snapshot of CloseRouter's `/providers` catalog
  entry for `anthropic/claude-opus-4.8` (pricing, `success_rate_24h`,
  `supports_reasoning_effort` per provider).
- `provider_sweep.py` / `provider_sweep_results.json` — round 1: one call per
  catalog-listed provider (`reasoning_effort="high"`, `temperature=0`),
  follow-up `thinking`-form call when the catalog claimed reasoning support
  and the first call returned zero reasoning tokens, plus two negative
  controls (`provider-3`, `provider-6`).
- `provider_sweep_round2.py` / `provider_sweep_round2_results.json` — round
  2: `provider-2`/`provider-10` retested with `temperature` omitted (ruling
  out a real Anthropic thinking/temperature conflict seen in round 1); one
  retry each for the two transiently-failing providers (`provider-5`,
  `provider-8`).

No API keys or secrets in any of these files (verified before commit).
