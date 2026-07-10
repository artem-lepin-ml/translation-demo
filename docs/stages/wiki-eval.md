# Stage — Wiki-eval (E1+E2 evaluation harness)

Up-link: [docs/pipeline.md](../pipeline.md). Design: [2026-07-03-wiki-eval-design.md](../superpowers/specs/2026-07-03-wiki-eval-design.md) (corpus/GT). Transport, prompts, gates and protocol-v3 rework: [2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md). Depends on the [terminology stage](terminology.md) (G6 `label_first` grounding, unmodified except its judge prompt split — see that doc).

## Purpose

Measure the terminology extraction (E1) + Wikidata grounding (E2, G6 `label_first`) pipeline against human hyperlink annotations on 100 full Russian Wikipedia ancient-history articles (selection v2: 10 thematic sections × 10). Reports **set-based document-level recall/precision** (protocol v3, below), split named/term, each with raw n + Wilson 95% CI. This is a standalone evaluation harness — it consumes the terminology stage's public contracts (`extract.NER_SYSTEM_PROMPT`/`extract.ner_user`, `grounding.LabelFirstGrounding`) but writes no code inside `grounding/`.

## Corpus (selection v2, 2026-07-05)

100 articles across **10 fixed thematic sections** of ancient history (10 per section): Sumer/Mesopotamia, Ancient Egypt, Assyria, Hittite kingdom, Phoenicia, Achaemenid Iran, Ancient India, Ancient China, Ancient Greece, Ancient Rome. Selection is deterministic and reproducible ([scripts/select_wiki_corpus.py](../../scripts/select_wiki_corpus.py), seed=42):

- **Candidate pool** — each section's Wikipedia category subtree (ns0 pages only).
- **Gate** — ≥30 unique main-namespace links in body paragraphs; earliest Wikidata date (P571/P580/P585/P569/P577) before 500 CE, undated pages kept; P31 blacklist {film, painting, museum, art museum}.
- **Binding** — an article reachable from several sections is bound to the first in fixed section order and used once.

Outputs: [data/eval/wiki/titles_v2.txt](../../data/eval/wiki/titles_v2.txt) (`title<TAB><section-slug>`; the slug becomes the GT record's `stratum` value) and [data/eval/wiki/selection_v2.json](../../data/eval/wiki/selection_v2.json) (full audit trail: pool sizes, gate drops, per-pick links/date/QID).

**Known residue (disclosed, kept):** ≈3/100 undated pages fall outside the intended period; retained rather than curated post hoc (owner decision 2026-07-05, avoids cherry-picking).

The canonical ground truth is [data/eval/wiki/gt.jsonl](../../data/eval/wiki/gt.jsonl) — 100 articles / 7 959 GT tuples (`build-gt --titles data/eval/wiki/titles_v2.txt`); see [2026-07-10-gt-canonicalization.md](../superpowers/specs/2026-07-10-gt-canonicalization.md) for the canonicalization that retired an earlier 20-article pilot file which used to live at this path.

## Prompts (2026-07-10 rework — system/user split, English)

Both roles now split a fixed **system** prompt (role, task definition, output contract) from a **data-only user** message — previously the extractor ran the whole prompt as user text against an empty system, and the judge's role definition lived in user too (spec Р5/Р7).

- **Extraction** — [`extract.py`](../../src/palimpsest/terminology/extract.py): `NER_SYSTEM_PROMPT` (fixed English system: role, extraction scope with `<categories>` as *scope-defining examples only*, `<do_not_extract>` rules, worked good/bad examples, output-format contract) + `ner_user(source) -> str` (user message: `<source>{source}</source>`, nothing else). Output schema is `{surface, lemma}` — **no `category` field** (2026-07-10 owner decision: category was never used deterministically downstream, only a cosmetic demo badge — see [terminology.md](terminology.md)). Read the prompt text in code, don't copy it into docs.
- **Judge** — [`grounding/label_first.py`](../../src/palimpsest/terminology/grounding/label_first.py): `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` (role + strict-JSON output contract) + `DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE` (data only: surface, lemma, sentence context, numbered candidates). `scripts/wiki_eval.py` imports `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` directly as `JUDGE_SYSTEM_PROMPT` — single source of truth stays in `label_first.py`, not duplicated in the eval script. A one-shot corrective re-ask (`JUDGE_REASK_SYSTEM_PROMPT`) restates the output contract on unparseable JSON, sharing the same underlying system text.
- **Judge context = the full sentence** containing the mention (`extract.sentence_context(source, start, end)`), not a character window. `_sentence_spans`/`_is_sentence_boundary` split on `.!?…` with RU-abbreviation/initials guards (е.g. «до н. э.», «в.», «вв.», «г.», «гг.», «др.», «т. д.», «т. п.», single-letter initials) so a mention near a sentence boundary gets its real sentence, not a truncated fragment. **`CONTEXT_PAD` (the old ±40-char window) no longer exists in code or docs.**

## Design decisions

- **Modules under `src/palimpsest/terminology/evaluation/`**, one responsibility each: `tokenize.py` (pinned E-D6 tokenizer, shared GT/prediction side), `wiki_gt.py` (Parsoid fetch, anchor→QID GT extraction, chronology filter; corpus selection lives in `scripts/select_wiki_corpus.py`), `predict.py` (eval-owned bridge: paragraph-chunked extractor calls with global-offset stitching → grounding pairing), `metrics.py` (protocol-v3 set-based aggregation — `matching.py` and mention-level M1/M2/M3 matching are **deleted**, see Protocol v3 below), `report.py` (pure offline HTML/JSON rendering of `metrics.aggregate_corpus_v3`'s output).
- **Tuple convention**: `(token_index, surface, qid, span_len)`, whole-article token index **reset per article** (article-local, not a running global offset — `metrics.aggregate_corpus_v3` groups by article title before deduping).
- **Real extraction entry point**: `extract.NER_SYSTEM_PROMPT`/`extract.ner_user(source)` → `extract.llm_surfaces(paragraph, extractor=callable) -> list[dict]` → `extract.mentions_from_surfaces(paragraph, surfaces) -> list[TermMention]`. `scripts/wiki_eval.py::_build_extract_fn` builds the injected `extractor` closure and hands `predict.predict_tuples` an `extract_fn(paragraph) -> list[TermMention]`.
- **Standard OpenRouter transport (spec Р2).** `DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"` — the earlier CloseRouter gateway (`WIKI_EVAL_PROVIDER`, `CLOSEROUTER_MODEL`/`CLOSEROUTER_PROVIDER` env vars, three-branch routing) is retired. Both the extractor and the judge always resolve through one shared `_resolve_route(model, provider, extra_body, base_url, temperature, top_p, top_k, max_tokens)` call — extraction and judge use the same model/provider/sampling within a run, unlike the retired design's per-role branches.
- **Vendor-recommended sampling per cloud model (spec Р3), `MODEL_PARAMS` in `wiki_eval.py`:**

  | model | temperature | top_p | top_k | provider pin | reasoning |
  |---|---|---|---|---|---|
  | `deepseek/deepseek-v4-flash` | 1.0 | 1.0 | — | Novita | `{"enabled": true}` |
  | `google/gemini-3.1-flash-lite` | 1.0 | — | — | Google AI Studio | `{"effort": "medium"}` (gemini needs the `effort` form — `{"enabled": true}` silently yields `reasoning_tokens=0`, probed live 2026-07-10) |
  | `google/gemma-4-31b-it` | 1.0 | 0.95 | 64 | WandB | `{"enabled": true}` |

  `max_tokens = 20000` for **both roles**, all three models (`DEFAULT_MAX_TOKENS`, spec Р3) — up from the old silent 4096 (extraction) / 512 (judge) caps. CLI overrides: `--temperature`/`--top-p`/`--top-k`/`--max-tokens`/`--model`/`--provider`/`--base-url` on `run`/`ablate`; an explicit value always wins over the `MODEL_PARAMS` default. `--provider auto` disables pinning and the served-by gate entirely. A provider pin change is a spec edit (spec Р14), not a silent code-side decision.
- **`--extra-body` merges PER-KEY over the computed defaults** (provider pin, reasoning shape, `top_k`, OpenRouter's `usage.include`) — it never replaces them wholesale, so an unrelated override key can't silently drop the provider pin (spec §4.1 finding 4). The effective post-merge `extra_body["provider"]["order"][0]` (if present) is what the per-call served-by gate checks against.
- **Per-call gates (spec Р13/Р14/Р15), `_gate_reply` in `wiki_eval.py`**, run on every completed extractor/judge/judge-reask call, in order:
  1. **Length overflow → `LengthOverflowError`** (a `FatalGroundingJudgeError` subclass): `finish_reason == "length"`, or empty `content` with `reasoning_tokens > 0` (the model spent its whole budget reasoning). **Never tolerated or silently retried** (spec Р15, reversing the earlier "length → transient retry" policy) — it halts the run loudly with model/role/article/paragraph/usage diagnostics; the checkpoint stays intact for `--resume`.
  2. **Reasoning didn't ignite → `CallGateError`**: `expect_reasoning=True` (a `reasoning` key was requested) but `reasoning_tokens == 0`.
  3. **Served provider ≠ pin → `CallGateError`**: the reply's `provider` field doesn't casefold-match the pin (when a pin and a provider are both present; `--provider auto` skips this gate).

  On the extraction side, `_parallel_extract_fn.safe_extract` re-raises any `FatalGroundingJudgeError` (enriched with `article`/`paragraph` via `exc.add_note`) instead of tolerating it as a transient failure. On the judge side, `LabelFirstGrounding.ground()` re-raises `FatalGroundingJudgeError` past its own catch-all instead of collapsing it to `judge_unavailable`. A fourth halt marker, **`BudgetExhaustedError`**, fires when `BudgetGuard.can_reserve()` returns `False` mid-call (the `$` cap or the judge-call ceiling was hit) — previously this degraded silently into `judge_unavailable`.
- **Per-call observability (spec Р8).** `CallLogger` appends one JSON line per completed call to `<run_dir>/calls.jsonl` — `ts`, `kind` (`extract`/`judge`/`judge_reask`), `model`, `provider`, `finish_reason`, `prompt_tokens`/`completion_tokens`/`reasoning_tokens`, `cost_usd`, `latency_ms`, `content_len` — written **before** `_gate_reply` runs, so a call that then trips a gate is still auditable, never silently dropped. `meta.json` gains a `generation_params` block: `model`, `base_url`, `provider_pin`, `temperature`, `top_p`, `top_k`, `max_tokens`, `reasoning`, and the full effective `extra_body` — the audit trail for exactly what was sent on the wire, not just the CLI flags given.
- **`parse_surfaces` no longer swallows malformed replies (spec §4.2 finding 1).** [`extract.py`](../../src/palimpsest/terminology/extract.py)'s `parse_surfaces` raises `ExtractionParseError` when no balanced JSON array can be recovered from the reply (malformed JSON, or valid JSON that isn't a list); an honest empty `[]` reply is not an error. `_parallel_extract_fn.safe_extract` catches `ExtractionParseError` specifically and tolerates it as zero mentions for that one paragraph — but counts it under its own `FailureTracker.record_parse_failure` counter (`n_extraction_parse_failures` + `parse_failed_paragraphs` in `meta.json`), never conflated with network-transient failures. Pilot gate: this must stay under 1% of paragraphs.
- **Parallel extraction / article-level parallelism / resilience retries / checkpointing / `--resume`** are unchanged by this rework — see the runner internals: `_parallel_extract_fn` (paragraph-level `ThreadPoolExecutor`, bounded by `DEFAULT_MAX_CONCURRENCY`), `--article-workers` (default 3, `_process_articles_parallel`), `RESILIENT_ATTEMPTS=6`/`RESILIENT_BACKOFF` via `_complete_with_slot` (slot released during backoff sleep), and per-article `Checkpointer` (`pred.partial.jsonl`/`progress.jsonl`, `--resume <run_dir>`).
- **`model_slug(model, provider)`**: `<model with every "/" -> "--">--<provider with spaces -> "-">` — e.g. `deepseek/deepseek-v4-flash` + `Novita` → `deepseek--deepseek-v4-flash--Novita`; `google/gemini-3.1-flash-lite` + `Google AI Studio` → `google--gemini-3.1-flash-lite--Google-AI-Studio`. Used as the run dir's top segment.
- **G6 sitelink rung creates evaluation circularity — eval runs use `--no-sitelink`.** The GT's own reference tuples come from Wikipedia hyperlink anchors resolved to Wikidata via the exact same RU-title→QID sitelink mapping that `GroundingConfig.use_sitelink` queries. `run --no-sitelink` forces `use_sitelink=False` regardless of `--config`'s bits (`_config_from_bits(bits, use_sitelink=False)`) — every real run in this doc uses it.

## Protocol v3 — set-based document-level metrics (spec Р9)

**v3 is the only protocol implemented** — mention-level M1/M2/M3 matching and the P1/P2/P3 precision variants (`matching.py`, label-justified precision, `--p3`) are **deleted**, not just superseded. Methodology prose SSOT: [docs/paper/sections/eval-metrics-terminology.tex](../paper/sections/eval-metrics-terminology.tex) — this doc and `metrics.py`'s docstring only restate the formalism for maintainers, they don't own it.

`metrics.aggregate_corpus_v3(articles: list[ArticleUnits], *, tier_assignment: dict[str, int]) -> dict` (`src/palimpsest/terminology/evaluation/metrics.py`):

- GT and prediction tuples are deduplicated to unique `(article, QID)` sets per article, then pooled into a corpus-level micro confusion: TP = gold ∩ pred, FN = gold \\ pred, FP = pred \\ gold — accumulated across all articles, never averaged per-article.
- **Tier filter (asymmetric by design):** gold QIDs whose tier (from `tier_assignment.json`) is non-zero (generic lexical classes — languages/scripts, taxa, materials, units) are dropped from the gold set before grouping, counted in `n_gold_mentions_dropped_by_tier`. Predictions get **no** tier filter — a generic-class prediction outside the filtered gold set still counts as FP, keeping `P_doc` a conservative lower bound rather than quietly forgiving predictions on the grounds gold was pruned.
- **Named/term split:** each gold unit is classified by `_classify` over its pooled anchor surfaces — named if any surface starts uppercase, term otherwise; mixed-case units are counted in `n_ambiguous_gold_units` but still classified named. FP units are classified by their own predicted surfaces (there is no gold class to fall back on).
- Output: `R_doc`/`P_doc` per class (`named`/`term`), each a single Wilson-CI `_cell` computed once from the pooled counts (`_cell`/`UNDERPOWERED_THRESHOLD=30`/`wilson_ci` are the shared per-cell primitives reused from the retired mention-level protocol — protocol-agnostic, still correct).
- **Tier data location:** [data/eval/wiki/tier_assignment.json](../../data/eval/wiki/tier_assignment.json) + [data/eval/wiki/tier_defs.json](../../data/eval/wiki/tier_defs.json) — moved next to the gold corpus (out of `docs/experiments/.../drafts/`, spec §4.5 item 13).
- Rendering: `report.render_html_v3(result, meta) -> str` (HTML fragment, project dark palette) — one row per class (gold_units/TP/FN/FP/R_doc/P_doc with CI).

## Interface

```
# scripts/wiki_eval.py (argparse subcommands)
wiki_eval.py build-gt --titles <file> [--out data/eval/wiki/gt.jsonl] [--cache data/eval/wiki/pages]
wiki_eval.py run --gt <gt.jsonl> [--cache <dir>] [--config <3-bit id>] [--max-usd 40]
                 [--model <id>] [--provider <route>] [--base-url <url>]
                 [--temperature <f>] [--top-p <f>] [--top-k <i>] [--max-tokens <i>]
                 [--extra-body <json>] [--max-judge-calls 900]
                 [--article-workers 3] [--llm-workers 4] [--no-sitelink]
                 [--dry-run] [--resume <run_dir>]
wiki_eval.py ablate --gt <gt.jsonl> [same route/sampling flags as run, minus --no-sitelink/--resume]
wiki_eval.py report --gt <gt.jsonl> --pred <run_dir> [--ablation] [--tier data/eval/wiki/tier_assignment.json]

# scripts/wiki_eval.py (helper functions)
model_slug(model: str, provider: str) -> str
```

`run`/`ablate` write `reports/terminology/wiki-eval/<model-slug>/<config>/<run_id ISO-UTC>/` containing `pred.jsonl` (predicted tuples + full per-mention records), `meta.json` (model/provider/spend-split/`generation_params`/wall-clock/counters, see Design decisions), and `calls.jsonl` (per-call observability, spec Р8). Transient while `run` is in flight: `pred.partial.jsonl`/`progress.jsonl` (checkpointing; `--resume <run_dir>` continues from them). `report` writes `metrics.json` (the `aggregate_corpus_v3` output + merged `meta`) and `report.html` next to the `pred.jsonl` it read.

Example (cloud, config 111, no-sitelink):
```
python scripts/wiki_eval.py run --gt data/eval/wiki/gt.jsonl --config 111 --no-sitelink \
  --model deepseek/deepseek-v4-flash --max-usd 12 --max-judge-calls 5000
python scripts/wiki_eval.py report --gt data/eval/wiki/gt.jsonl \
  --pred reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/<run_id>
```

## Subtleties

- **Paragraphs are re-derived from cached HTML, not from `gt.jsonl`'s flat `tokens[]`.** `run` re-reads the cached `<cache>/<title>.html`, re-flattens it (`tokenize.flatten`), and splits on `"\n"` — identical to what `wiki_gt.build_gt` did when it produced the tokens, so GT and prediction indices stay aligned. A `pred.jsonl` re-run after clearing the cache silently skips articles whose HTML is missing (title absent from output) rather than fail loud — a known gap.
- **`--dry-run` forecast is a rough upper-bound, not a simulation.** It estimates escalations as `n_pred_mentions // 3` judge calls — a deliberately coarse prior; the harness's real defense is the live `BudgetGuard` + `--max-judge-calls`, not forecast precision.
- **Coverage guard.** `_assert_pred_gt_coverage` fails loudly (`SystemExit`, naming the mismatch count and both paths) if any prediction title is absent from the loaded `--gt` corpus — closes the class of bug in the "RESOLVED 2026-07-10" `gt.jsonl` drift incident below.
- **Resilience retries (2026-07-05, qwen-run incident).** `_build_extract_fn`/`_build_judge` retry at `RESILIENT_ATTEMPTS=6`/`RESILIENT_BACKOFF=(1,3,9,20,40,60)` via `_complete_with_slot`, which holds the `llm_semaphore` slot only during each network attempt, releasing it during backoff sleep. If a call is still TRANSIENT-failing after that: extraction tolerates the paragraph as zero mentions (counted via `FailureTracker.record_failed_paragraph`); the judge closure lets the exception propagate into `LabelFirstGrounding.ground()`'s `judge_unavailable` catch-all (counted via `FailureTracker.record_failed_judge_call`). A `FatalGroundingJudgeError` (Р15 halt marker) is checked BEFORE the transient/deterministic split and is never tolerated this way — see Per-call gates above.
- **Per-article checkpointing + `--resume` (2026-07-06, container-restart incident).** `run`'s output dir is created at the START of the invocation; `Checkpointer` appends each completed article's records to `pred.partial.jsonl` and a progress line to `progress.jsonl` the instant that article's worker finishes. `run --resume <run_dir>` reuses that dir/`run_id`, skips already-done titles (never re-billed), seeds a fresh `BudgetGuard` from `progress.jsonl`'s last recorded spend, and merges old+new records replaying `gt.jsonl`'s article order.

## Status

Modules + CLI implemented; unit tests green. Corpus selection v2 committed (100 titles, 10 sections); canonical `gt.jsonl` = 100 articles / 7 959 GT tuples.

**Experiment v2 rework landed (2026-07-10, 4 commits on `claude/ner-translation-config-b0ozsc`)**: `421c99d` (English NER system/user prompt, `{surface, lemma}` schema, full-sentence judge context), `0d89242` (protocol-v3 set-based aggregator, retires the mention-level/sitelink-replay machinery), `275f8c7` (archived a leftover-resume run, see known_issues.md), `7e7ddfd` (standard-OpenRouter transport, vendor sampling, per-call gates, observability, `cmd_report` on protocol v3). Full spec: [2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md).

**Pending (not yet run under this rework):** the pilot (10 articles, gemini) and the three full cloud runs (`gemini-3.1-flash-lite`, `deepseek-v4-flash`, `gemma-4-31b-it`); the three local sr004 rows per [sr004-local-eval-runbook.md](../runbooks/sr004-local-eval-runbook.md). `gpt-5.4` is excluded from the experiment entirely (spec Р1) — its earlier pre-rework run artifacts are archived (`275f8c7`), not part of Table C.

**All numbers from before this rework (P_label/P3, mention-level R_all/R_term, the `sitelink_contamination.py` offline replay) are retired protocol-v2 output — not comparable to a protocol-v3 run, and not reproducible with the current code** (the scripts that produced them, `scripts/sitelink_contamination.py` and friends, are deleted). Historical write-ups live under [docs/experiments/2026-07-05-model-comparison/drafts/](../experiments/2026-07-05-model-comparison/drafts/), banner-marked superseded.

## Methodology

Methodology prose (evaluation-against-Wikipedia-links setup, the protocol-v3 formalism, ablation design) has one source of truth: [docs/paper/sections/eval-metrics-terminology.tex](../paper/sections/eval-metrics-terminology.tex). This doc no longer carries its own copy of it.

⚠️ **Code drift, not fixed by this doc pass:** [`report.py::methodology_draft()`](../../src/palimpsest/terminology/evaluation/report.py) still exists and still returns the old protocol-v1/v2 paragraph verbatim (three matching modes, label-justified/P3 precision, per-`resolved_by` slicing) — none of that is true of the shipped protocol-v3 code any more. It is dead code (`cmd_report` calls only `render_html_v3`, never `methodology_draft`) left over from spec §4.5 item 12's collapse, which the landed commits (`421c99d`/`0d89242`/`7e7ddfd`) did not carry out on the code side. Flagged for the owner/a follow-up commit — deleting it (or repointing its docstring at the tex SSOT) is a code change outside docs-keeper's remit.
