# Overnight mission state — 2026-07-09 (post-compact continuation anchor)

Owner is asleep. Autonomous mode (Scenario B): drive ALL experiments to completion.
Morning deliverables: Table A (LLM-as-a-judge, BOUQUET) + Table C (NER+Wikidata grounding),
filled with every achievable row, plus an honest list of what failed and was dropped/replaced.
Owner fallback policy: if a model cannot run (dead route, rate limit), switch model or drop it,
then disclose honestly. Specifically: if gpt-5.5 will not work, put openai/gpt-5.4 in charge
as the OpenAI row (smoke padding+rate first), rename rows honestly.

## Live background agents at compact time
1. Judge gemini-3.1-flash-lite-think: full run in progress -> stats -> selective commit.
2. Judge gpt-5.5: provider-8 smoke -> resume (fallback auto + patient backoff). ~430/2376 done on auto.
3. Judge deepseek-v4-flash: PARKED at 19/2376 (gateway 503 no_available_provider), poller live,
   resume command in docs/reports/python-pro-judge-run-deepseek.md. If provider dead by morning:
   disclose as failed/partial.
4. Grounding gpt-5.5: provider-8 smoke -> full run (sitelink OFF, cap $15). provider-6 REJECTED
   (padding ~4.7k tokens/call, evidence commit d2bbf4f).
5. Clean P_label live computation (~4410 wbsearchentities calls) -> updates
   docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json -> commit.
6. Opus grounding agent closing out: commits --no-sitelink flag + provider-sweep JSON.
7. Table C tex maintenance: drop-Opus edit + pending rewrite to 2-metric main table.

## Decisions locked (do not re-litigate)
- Opus 4.8 DROPPED from Table C (owner decision: reasoning unreachable on ALL 7 CloseRouter
  providers; sweep matrix in docs/reports/ml-engineer-grounding-run-opus48.md). Opus stays in
  Table A as the no-thinking judge row (commit 6a90dec).
- Table C: 6 rows in canonical order Qwen3-4B-Instruct, Gemma-3-27B-it, Qwen3.6-27B,
  Gemini-3.1-Flash-Lite, DeepSeek-V4-Flash, GPT-5.5. Metrics: R_doc on the R_term tier +
  P_label, sitelink-clean. Full metric grid goes to appendix. Filled: gemini 0.7345
  [.724-.745] (5269/7174), deepseek 0.6574 [.646-.668] (4716/7174); P_label clean pending
  (orig 0.526/0.530).
- Table A: prompts v1_core3 (= v1 accuracy/fluency/style verbatim); runner
  scripts/bouquet_judge_rerun.py + configs/bouquet_judges.yaml; stats per judge in
  reports/bouquet/judges/&lt;slug&gt;/stats.json. Done rows: flash-lite no-reasoning (ced45c3,
  sensitivity), opus no-thinking (6a90dec). Local 3 judges (qwen3-4b, gemma-3-27b-it,
  qwen3.6-27b, T=0) need the sr004 vLLM runbook — PREPARE IT OVERNIGHT (runs happen owner-side).
- Route lessons: provider-6 pads gpt-5.5 (~4.7k hidden tokens/call); provider-10 pads Opus
  4.7x + no reasoning + breaks JSON; auto is clean for both but rate-limits gpt-5.5 (~50/h).
- Hard rules: never delete LLM predictions (append-only everywhere); selective staging in the
  shared tree (multiple agents edit configs/bouquet_judges.yaml — use race-proof staging);
  no AI signatures anywhere; all owner-facing reporting in Russian.

## Overnight loop
- Hourly self check-ins via send_later (re-arm every hour): PR #13/#14 state, run progress
  (line counts in reports/bouquet/judges/*/scores.jsonl), tree cleanliness, stalled-agent nudges.
- On each agent finish: verify commit pushed, update the tex tables
  (docs/paper/sections/table-a-judges.tex cells, table-c-grounding.tex) via docs-keeper dispatches.
- ~03:00Z decision point: if gpt-5.5 unrecoverable on all clean routes for either run, execute
  the gpt-5.4 fallback (new slugs, fresh pilot gates, same protocol).
- Morning: assemble both filled tables + judge-comparison summary (means, Spearman vs
  MetricX-ref/QE/COMET, tie-rates, reasoning-on/off sensitivity pairs) + honest failure list,
  deliver in Russian in chat; per CLAUDE.md cloud rules use a Claude Artifact if the report is long.
- PRs: #13 collects everything (branch claude/ner-translation-config-b0ozsc); #14 awaits owner.
