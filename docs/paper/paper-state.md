# Paper state — EMNLP 2026 System Demonstration (Historical MT tool)

> Living document: current structure + fill-state of the paper draft, and the mapping
> experiments → tables. Update on every experiment/writing change.
> Draft source: ACL-template PDF (`2026_EMNLP_History_Demo.pdf`, uploaded 2026-07-08).
> Companion RU outline lives in the chat; spec for the current eval:
> [2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md).

## Skeleton (mirrors the abstract)

| # | Section | State |
|---|---------|-------|
| — | **Title** | TODO ("Historical Demo Title" placeholder) |
| — | **Abstract** | Drafted: domain + problem; 3 contributions (translation pipeline; terminology normalization; grammarly-style refinement module); experimental eval on datasets; demo URL + code link — **URLs TODO** |
| 1 | **Introduction** — tool + contributions | Drafted (interactive web-based tool for interpretable MT analysis; contributes: pipeline, terminology, refinement, eval) |
| 2 | **Related work** | Populated with WMT24/25, SemEval-2025 Task 2 (EA-MT), TEaR, DelTA, Tan et al. 2026 (LLM refinement in literary MT), etc. |
| 3 | **System** (tech report, 3 submodules) | In progress |
| 3.1 | Initial translation | In/out + formalization — partial |
| 3.2 | Terminology Extraction (NER + Wikidata grounding) — **Artem** | Drafted; "Ambiguous Terminology Resolution" — **TODO**; exact/ambiguous/unknown formalism to write |
| 3.3 | LLM-as-a-judge Evaluation + Refinement — **Danil** | Drafted (judge 1–10, Accuracy/Fluency/Style; issues → editor) |
| 3.x | Datasets paragraphs | 3 datasets: history volume (томик), BOUQUET, Wikipedia-100. Table 1 (data statistics) — **to fill** |
| 3.x | Demo ↔ methodology figure | **TODO** (figure linking demo interfaces to methodology) |
| 3.x | Demo interfaces | TipTap (cite GitHub), LLMs via OpenRouter, HuggingFace record — **to write** |
| 4 | **Evaluation setup** | 4.1 Evaluation Data — partial; 4.2 Evaluation metrics — **TODO**. Maximize model overlap across tables for consistency |
| 5 | **Results** (bold-takeaway paragraph names) | 5.1 Terminology Recognition — partial. Two quantitative tables (one per section). Case study / error analysis on the history book (same in demo) — **TODO**. Qualitative table comparing predictions vs Wikipedia annotation — **TODO** |
| 6 | **Conclusion** | TODO |
| — | Tables | T1 data statistics; **Table A** LLM-as-a-judge (BOUQUET only, 4 fixed systems, 7-judge comparison); **Table B** Refinement usefulness (cross base×refiner matrix, wiki-100 + QE metrics); **Table C** NER + Wikidata grounding (model-comparison v4) |
| — | Appendix | Prompts (per spec §8, `v1_core3` variant for Table A); full judge disclosure (model/config/date) per Table A protocol; per-judge full tables (Table A compact in main paper); limitations sentence re: old BOUQUET numbers from stochastic self-judge (spec §8) |

## Experiments → paper mapping

### Evaluation restructuring (owner, 2026-07-08)

Evaluation section is now **three tables, one per contribution** — replaces the earlier
flat T2/T3 numbering:

- **Table A — LLM-as-a-judge** (contribution: judge/refinement module). **BOUQUET only** —
  the one dataset with human references, so reference-based metrics and ranking are
  meaningful. Judged systems are **fixed at the 4 already-vendored ones** (TranslateGemma,
  TG-Refined, Qwen3.6-27B, Qwen3.6-27B-Refined) — translations are **not** regenerated,
  judges only re-score the existing outputs.
- **Table B — Refinement usefulness** (contribution: refinement module). Cross
  base×refiner matrix — the 7-row proposal below, still pending owner confirmation —
  on wiki-100, reported with QE metrics.
- **Table C — NER + Wikidata grounding** (contribution: terminology extraction). From
  model-comparison v4, pending the qwen3.7-plus clean re-run.

### Done
- **BOUQUET ru2en (by paragraphs)** → feeds **Table A**. Systems: TranslateGemma / TG-Refined /
  Qwen3.6-27B / Qwen-Refined; judge Acc/Flu/Sty ≈ 9.5–9.9; MetricX w/ и w/o ref; COMET.
  Spearman judge↔metrics weak (−0.13…+0.37) — discussion point. Old numbers were
  Danil-verbatim (qwen3_6-27b, T=0.7, thinking on) — kept as a **sensitivity footnote**,
  not recomputed; Table A itself uses the new 7-judge protocol below.
- **NER+Wikidata grounding, wiki corpus v2 (model-comparison v4)** → **Table C** / §5.1.
  4-model matrix: `google/gemini-3.1-flash-lite` (provider-9, clean R_doc 0.684),
  `deepseek/deepseek-v4-flash` (provider-9, clean R_doc 0.609), `qwen/qwen3.7-plus`
  (provider-8 — run INVALIDATED by provider outage, re-run queued), `openai/gpt-5.5`
  (provider-3 — EXCLUDED, no stable route >16h).
  Artifacts: `reports/terminology/wiki-eval/`, paper section draft
  `docs/experiments/2026-07-05-model-comparison/drafts/paper-section-en.tex`.
- **Wiki-100 corpus** built & handed to Danil: 2 553 paragraphs / 100 articles
  (`data/eval/wiki/`, README + sha256), pilot = 10 articles / 274 par.
- **deepseek CloseRouter smoke** ($0.0052): reasoning-off flag mandatory; provider-9 pin
  incompatible with json_object (judge role → route auto). **Superseded 2026-07-08**:
  locked protocol is reasoning **ON** for the judge role (see Table A protocol below).

### In flight (current task)

**Table A — LLM-as-a-judge, 7-judge lineup (owner-locked, 2026-07-08; updated 2026-07-08 —
Gemini judge swapped to flash-lite):**
- Local vLLM: `qwen3.6-27b` (prod anchor), `qwen3-4b-instruct`, `gemma-3-27b-it`
  (same family/scale as TranslateGemma → family-bias check; also a Gemma-vs-Gemini
  open-vs-cloud same-vendor angle).
- Cloud via CloseRouter: `deepseek-v4-flash`, `claude-opus-4.8`, `gpt-5.5`,
  **`gemini-3.1-flash-lite`** (replaces `gemini-3.1-pro`; exact router ID still being
  confirmed by a smoke test — `google/gemini-3.1-flash-lite` or `-preview`, mirroring
  the `-preview` suffix pattern found for pro in the probe). Side benefit: flash-lite
  already appears in the Table B translator matrix and the Table C grounding eval, so
  the swap increases model overlap across tables, per the §4 "maximize model overlap
  across tables" note.

**Table A protocol (owner-locked, 2026-07-08; updated 2026-07-08):**
- Local/open judges → `temperature=0`, thinking OFF.
- `deepseek-v4-flash` → `T=0`, **reasoning ON** (locked protocol as of 2026-07-08 —
  supersedes the earlier "reasoning OFF mandatory" note from the smoke test; per the
  probe, `reasoning.enabled:false` didn't actually suppress thinking anyway, so ON is
  now the honest, locked setting).
- GPT-5.5 / Opus 4.8 / Gemini-3.1-Flash-Lite → no temperature param, **default effort**,
  thinking on where the gateway honors it. Disclosed quirk (probe, 2026-07-08): the
  OpenAI-compat bridge on CloseRouter silently drops reasoning params for Opus
  (0 reasoning tokens across all 3 parameter forms tried) — Opus judges without
  thinking in practice; GPT-5.5 reasons normally at default effort (110–292 reasoning
  tokens/call). Full per-judge config disclosure goes to the paper appendix
  (`app:judge-configs`), not the compact main-paper table.
- Prompts = **`v1_core3`** (filtered variant of `v1`, 3 criteria only: accuracy/fluency/style;
  `cultural.md` / `terminology.md` dropped — `load_prompts` globs `*.md` in the variant dir,
  no code change needed). The old Danil-verbatim `qwen3.6-27b` run (T=0.7, thinking on —
  the screenshot numbers) is kept as a **sensitivity footnote**, not recomputed.
- Stats to report: per-system mean Accuracy/Fluency/Style per judge; Spearman
  judge↔MetricX-ref / MetricX-QE / COMET; tie-rate (share of {9,10} scores). Full
  per-judge tables → appendix; compact table in the main paper.
- Execution split: the 4 cloud judges run from the cloud session via CloseRouter; the
  3 local judges run via the sr004 vLLM runbook (Danil pipeline +
  `patches/gse-translation-sr004/`).
- Cost estimates (from the judge probe,
  [docs/experiments/2026-07-08-judge-probe/probe-results.md](../experiments/2026-07-08-judge-probe/probe-results.md),
  per full 2 376-call BOUQUET run): Opus 4.8 ≈ $2.3, GPT-5.5 ≈ $1.3, DeepSeek-V4-Flash
  ≈ $1.5. `gemini-3.1-pro` (≈ $9–14) was dropped in favor of flash-lite, partly on cost —
  flash-lite pricing/cost still TBD, to be confirmed by the pending smoke test.

**Table B — Wiki-100 LLM-judge + refinement eval**, extended matrix: 5 systems
  (TranslateGemma-27B, Qwen3-4B-Instruct-2507, Qwen3.6-27B — local vLLM on 4×A100;
  deepseek-v4-flash, gemini-3.1-flash-lite — CloseRouter), translate + refine stages.
  - Judge prompts = **v1_core3** (see Table A above; same filtered variant, no separate copy).
  - Judge config = **Danil-verbatim** (qwen3_6-27b, T=0.7, thinking on) for this table
    specifically — Table B is about refinement usefulness, not judge comparison, so the
    judge stays fixed.
  - **Invariant: the refiner is strictly stronger than the base translator.**
    No self-refinement anywhere. Assumed strength order:
    Qwen3-4B < TranslateGemma-27B ≤ Qwen3.6-27B < gemini-3.1-flash-lite < deepseek-v4-flash.
  - Runner = **Path A**: Danil's pipeline + `patches/gse-translation-sr004/`.
  - Proposed matrix (7 rows, before→after columns): 2×2 sub-matrix
    {Qwen3-4B, TranslateGemma-27B} × {Qwen3.6-27B, deepseek-v4-flash refiners},
    Qwen3.6-27B→deepseek, gemini-lite→deepseek, deepseek base-only (ceiling).
    Awaiting owner confirmation.
  Runbook (4-system version): [translation-eval.md](../stages/translation-eval.md);
  patches: `patches/gse-translation-sr004/`.
- Judge probes: test-retest (verbatim config), J′ = deepseek inter-judge agreement.

### Queued
- qwen3.7-plus clean re-run (grounding eval, Table C).
- Case study / error analysis (history volume) + qualitative wiki-annotation table.
