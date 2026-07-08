# BOUQUET multi-judge re-scoring — summary

Generated 2026-07-08T22:03:43.186783+00:00 by `scripts/bouquet_judge_rerun.py stats`.

Per (judge × system × criterion): mean score, tie-rate (share of scores in {9,10}), paragraph-level Spearman rho vs vendored MetricX-ref / MetricX-QE / COMET (`n` = paired non-null paragraphs).

| Judge | System | Criterion | N | Mean | Tie% 9-10 | ρ MetricX-ref | ρ MetricX-QE | ρ COMET |
|---|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | Translate Gemma | accuracy | 5 | 9.800 | 100.0% | -0.7071 (n=5) | -0.7071 (n=5) | +0.7071 (n=5) |
| deepseek-v4-flash | Translate Gemma | fluency | 5 | 9.800 | 100.0% | -0.7071 (n=5) | -0.7071 (n=5) | +0.7071 (n=5) |
| deepseek-v4-flash | Translate Gemma | style | 5 | 9.200 | 80.0% | +0.1054 (n=5) | +0.1054 (n=5) | +0.6325 (n=5) |
