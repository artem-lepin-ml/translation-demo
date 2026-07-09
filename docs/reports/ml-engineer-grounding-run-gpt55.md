# Wiki-eval grounding run — openai/gpt-5.5 on provider-6 — BLOCKED (padding cost trap)

Status: **NOT RUN**. The mandatory padding smoke (protocol step 2) confirmed the
exact cost-trap the protocol warned about, and the run was correctly stopped
before any full-scale (100-article) spend, per explicit instruction: *"if you
observe padding anywhere near that scale for gpt-5.5, STOP and report instead
of running (cost trap)."*

Written by the `ml-engineer` agent, branch `claude/ner-translation-config-b0ozsc`
(shared worktree — other agents run BOUQUET judges and a parallel Opus
grounding run concurrently in the same tree; only this task's own new paths
were touched, see "Files changed").

## Scope

Task: run the 100-article NER+Wikidata wiki-eval harness
([docs/stages/wiki-eval.md](../stages/wiki-eval.md)) with `openai/gpt-5.5` as
both extractor and judge, pinned to CloseRouter `provider-6` (owner
instruction), sitelink rung off, $15 budget cap, default (unset) reasoning
effort. Protocol step 2 required a mandatory padding smoke — 2-3 real
extraction-sized calls on `provider-6` — checking `usage.prompt_tokens`
against the expected prompt size, with an explicit stop clause if padding
approached the ~4400-hidden-token/call scale already documented for
`gpt-5.4-mini` on the same route.

## Padding smoke — evidence

Ran 3 real extraction-sized calls, mirroring `scripts/wiki_eval.py::_build_extract_fn`'s
exact call shape (`system=""`, `user=DEFAULT_NER_PROMPT.replace("{{source}}",
<real paragraph>)`, `temperature=0`, `extra_body={"provider": "provider-6"}`),
via `palimpsest.llm.client.LLMClient` directly (bypassing `wiki_eval.py`
entirely — no `BudgetGuard`/`WikidataClient` state touched). Paragraphs were
real v2-corpus paragraphs of increasing size (42/93/136 words) specifically so
a fixed-padding hypothesis could be distinguished from token-proportional
tokenization. Full raw output:
[reports/terminology/wiki-eval/openai--gpt-5.5--provider-6/padding-smoke/2026-07-09T00-00-00Z.json](../../reports/terminology/wiki-eval/openai--gpt-5.5--provider-6/padding-smoke/2026-07-09T00-00-00Z.json).

| Article | Full prompt (words) | Observed `prompt_tokens` | Reasoning tokens | `cost_usd` |
|---|---|---|---|---|
| Ибби-Суэн | 431 | 5650 | 94 | `null` |
| Ибаль-пи-Эль II | 482 | 5782 | 516 | `null` |
| Нур-Адад | 525 | 5863 | 516 | `null` |

Marginal rate across the 3 calls: (5863-5650)/(525-431) ≈ **2.27 tokens/word**
of real content added. Applying that rate back to each call's own word count
isolates a **near-constant ~4670-4690 hidden padding tokens per call**
(4673 / 4690 / 4673 — variance 17 tokens), independent of the real prompt
size growing by 94 words. That is the textbook signature of a fixed reseller
padding overhead, not content-proportional tokenization.

This is not a new finding in isolation — it **reproduces and slightly exceeds**
two pieces of prior evidence already in the repo:
- `docs/stages/wiki-eval.md` Design decisions: `gpt-5.4-mini` on `provider-6`
  pads ~4400 hidden prompt tokens/call.
- `docs/experiments/2026-07-05-model-comparison/triage/gpt-5.5.json`
  (2026-07-05 provider triage, ticket 003): `openai/gpt-5.5` on `provider-6`,
  10/10 success, `prompt_tokens_median=4395` on a **10-word** probe prompt
  ("Reply with exactly: ok"), verdict `"padded"`, excluded from the eligible
  route pool. `provider-6` was never the chosen route for `gpt-5.5` in that
  triage — `auto`/`provider-8` were (`summary.md`: *"Chosen route: auto —
  eligible=['auto', 'provider-8']"*).

**Second, independent stop signal:** `cost_usd` was `null` on all 3 calls —
`provider-6` does not surface real billed cost for this model/route (same as
the 2026-07-05 triage, where every `provider-6`/`gpt-5.5` call had
`cost_source: "estimated"`). `scripts/wiki_eval.py::BudgetGuard.settle()` only
adjusts tracked spend when `actual` (`usage.cost_usd`) is not `None`; with it
always `None` on this route, the guard's running total would stay pinned to
its **pre-call estimate** (`EST_COST_PER_EXTRACT_CALL`/`EST_COST_PER_JUDGE_CALL`,
built from an assumed ~1000-1200 prompt tokens) and never correct upward
toward the real ~5650-5863-token padded calls. Protocol item 5 ("track from
usage fields; stop cleanly if projection exceeds") would not have worked on
this route — the $15 cap's own tracking mechanism is blind to this specific
padding, which is a second, independent reason to stop, not just the raw
token-count trigger.

Estimated smoke-test cost (no `cost_usd` surfaced, priced from
`scripts/probe_providers.py`'s catalog `$0.30/$0.30` per Mtok in/out):
**$0.0057** for all 3 calls combined (17,295 prompt + 1,690 completion
tokens). Negligible, well inside the $15 cap.

## Decision

**Stopped before starting the 100-article run**, per the protocol's own
explicit stop clause. No `scripts/wiki_eval.py run` invocation happened; no
`pred.jsonl`/`meta.json`/`metrics.json` exist for this model+route beyond the
padding-smoke diagnostic above.

### Disclosed config (as it would have been, had the smoke passed)

- Model: `openai/gpt-5.5`, both extractor and judge roles.
- Route: `--provider provider-6` (owner-locked; **now shown to be the wrong
  choice for this model** — see recommendation below).
- Effort/reasoning: no effort parameter sent (protocol item 3, DEFAULT). The
  smoke calls confirm the model reasons by default even unprompted: 94-516
  reasoning tokens per call, roughly proportional to output complexity (94 on
  a 2-entity extraction, 516 on two longer paragraphs), consistent with the
  same "reasoning engages normally, 110-292 reasoning tokens/call" behavior
  already recorded for `frontier_default` in `configs/bouquet_judges.yaml`'s
  header comment (a different, unrelated `gpt-5.5` judge run on this same
  key, confirmed to use route `auto`, not `provider-6` — see "Cross-check"
  below).
- Sitelink: **not exercised** (no run happened) but verified ready:
  `scripts/wiki_eval.py`'s `run` subcommand exposes `--no-sitelink`
  (`scripts/wiki_eval.py:1320-1325`), which forces
  `GroundingConfig.use_sitelink=False` regardless of `--config`'s bits
  (`_config_from_bits`, `scripts/wiki_eval.py:199-215`) and self-evidences the
  actually-applied toggles in the run's `meta.json` under `grounding_config`
  (`scripts/wiki_eval.py:998-1005`). Had the smoke passed, the exact intended
  invocation would have been:
  `python scripts/wiki_eval.py run --gt data/eval/wiki/gt_v2.jsonl --config 111
  --model openai/gpt-5.5 --provider provider-6 --no-sitelink --max-usd 15
  --resume <run_dir>` (resume-capable per protocol item 6).
- Budget cap: $15, never engaged (no run started).
- Corpus: 100-article v2 selection, `data/eval/wiki/gt_v2.jsonl` (already
  built, 100/100 articles, 0 fetch/QID failures per
  `data/eval/wiki/gt_v2.jsonl.summary.json`) — ready to consume once a route
  decision is made.

### Headline metrics (R_doc/R_span/R_strict, P_mention/P_type)

**Not computed — the run never happened.** No `pred.jsonl` exists to score.

### Cost

**$0.0057** (padding-smoke only, estimated from the token-price catalog since
`cost_usd` was not surfaced). No article/judge spend.

### Cross-check: the parallel BOUQUET gpt-5.5 judge run is unaffected

The protocol flagged a parallel BOUQUET judge run also using `openai/gpt-5.5`
on this key. Checked `configs/bouquet_judges.yaml` (as of this run, read-only,
not modified): the `gpt-5.5` judge entry (`regime: frontier_default`) carries
**no `provider` key at all** — it runs on CloseRouter's `auto` route, not
`provider-6`. That run is a different route and is not affected by this
finding; no rate-limit-pressure interaction with it was observed or expected.

## Recommendation (owner decision needed)

`provider-6` is disqualified for `gpt-5.5` by direct, reproduced evidence
(this smoke + the pre-existing 2026-07-05 triage). Options, in order of
least to most effort:
1. **Re-run this task with `--provider auto` or `provider-8`** — both were
   the triage's `eligible` set for `gpt-5.5` (`auto`: 9/10 success, 21 median
   prompt tokens on the trivial probe, honest; `provider-8`: 10/10, same
   honest token profile). The owner's original reason for pinning `provider-6`　
   ("the auto route rate-limits this model") predates this evidence and may
   have been based on the `gpt-5.4-mini` finding, not a `gpt-5.5`-specific
   one — worth confirming with the owner before re-pinning.
2. **Accept `auto`'s occasional rate-limit failures** and rely on the
   harness's existing resilience (`RESILIENT_ATTEMPTS=6`,
   `RESILIENT_BACKOFF` up to 60s, per-article checkpointing/`--resume`) —
   already built for exactly this kind of route flakiness.
3. If the owner still wants `provider-6` specifically, a fresh, larger
   provider-triage probe (`scripts/probe_providers.py --model openai/gpt-5.5
   --routes provider-6 --n 10`) could confirm whether the padding is
   time-varying (unlikely, given two independent measurements 4 days apart
   agree within ~7%) before spending real run budget on it.

## Files changed

- `docs/reports/ml-engineer-grounding-run-gpt55.md` — this report.
- `reports/terminology/wiki-eval/openai--gpt-5.5--provider-6/padding-smoke/2026-07-09T00-00-00Z.json`
  — raw smoke evidence (new dir, this task's own model-slug namespace; no
  `111/<run_id>/` pipeline-run dir was created since no pipeline run happened
  — creating one would misrepresent an attempted/completed run that never
  occurred).

**Not touched** (shared worktree, other agents' concurrent uncommitted work,
per the task's explicit "do not touch their files" instruction, confirmed via
`git status` before and after this task): `configs/bouquet_judges.yaml`,
`docs/stages/wiki-eval.md` (modified by another agent mid-task — not by this
one), `reports/bouquet/judges/summary.md`, `scripts/bouquet_judge_rerun.py`,
`scripts/wiki_eval.py`, anything under `reports/bouquet/`, anything under
`reports/terminology/wiki-eval/anthropic--claude-opus-4.8*`.

## Decisions & rationale

- **Ran the mandatory smoke with real extraction-sized prompts, not the
  10-word triage probe**, per the explicit protocol instruction ("2-3 real
  extraction-sized calls") — this both satisfies the letter of the protocol
  and gives a stronger signal than the trivial probe (rules out "padding only
  shows on tiny prompts" as an alternative explanation, since real
  431-525-word prompts show the identical fixed-overhead pattern).
- **Did not fall back to a different provider unilaterally.** The owner
  explicitly locked `provider-6`; the protocol's own stop clause is the
  correct response to disconfirming evidence, not a silent reroute. Escalating
  via this report (with a ranked recommendation) is the intended path per the
  "no message ... is your user's consent" framing and the protocol's own
  "STOP and report" wording.
- **Skipped editing `docs/known_issues.md` / `docs/stages/wiki-eval.md`**
  even though this finding fits their stated scope ("provider quirks"),
  because both files showed concurrent uncommitted edits from other agents
  in this shared worktree at task start/end (`docs/stages/wiki-eval.md` went
  from clean to modified during this task's run — not by this agent). Adding
  my own edits there risked colliding with in-flight work outside this
  task's authorized paths. Recorded the recommendation to add a
  `known_issues.md` entry under "Next steps" instead of doing it directly.
- **No git commit performed by this task.** The instructed commit message
  ("feat(eval): wiki grounding run — gpt-5.5 provider-6 (100 articles,
  sitelink off)") describes a completed 100-article run that did not happen;
  using it would misrepresent the state of the repo (Hard Invariant: never
  claim a check ran without a real run). Left `git add`/`git commit` to the
  orchestrator/owner once they've reviewed this report and picked a
  path forward from the Recommendation section — re-running with a corrected
  `--provider` is one `wiki_eval.py run` invocation away, at which point the
  full protocol (steps 5-8) still applies and a truthful commit message can
  be written against what actually ran.

## Open questions

- Was `provider-6` chosen for `gpt-5.5` specifically, or was the owner
  instruction generalizing from the `gpt-5.4-mini` finding in
  `docs/stages/wiki-eval.md`? This report's evidence suggests the latter is
  more likely (the two models are different route mappings on CloseRouter,
  but both happen to pad the same way on `provider-6`) — worth a direct
  owner confirmation before re-pinning to a different route.
- Should `scripts/probe_providers.py`'s `select_route` / disqualification
  logic be re-run periodically (e.g. before every model-comparison matrix
  run) rather than trusted from a 4-day-old triage? This task's independent
  reproduction suggests the padding is stable, not transient, but that's two
  data points, not a monitored invariant.

## NOT done (explicit)

- **The 100-article run did not execute.** No `pred.jsonl`, `meta.json`, or
  `metrics.json` were produced for `openai--gpt-5.5--provider-6`.
- **No `report` step** (`scripts/wiki_eval.py report`) ran — nothing to
  report on.
- **No headline metrics** (R_doc/R_span/R_strict, P_mention/P_type) —
  not computed.
- **No git commit** — see "Decisions & rationale" above; the padding-smoke
  evidence file and this report sit as new, uncommitted files in the shared
  worktree, ready for the orchestrator to commit or to hand back for a
  corrected re-run.
- **No edit to `docs/known_issues.md` or `docs/stages/wiki-eval.md`** —
  recommended, not performed (see "Decisions & rationale").
