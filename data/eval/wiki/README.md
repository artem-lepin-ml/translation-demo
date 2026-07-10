# Wiki-100 corpus — evaluation data

100 ru-Wikipedia articles used by two paper sections: the NER/Wikidata grounding eval
and the LLM-judge translation eval. The text is token-identical between both
(audited: [cleanliness check](../../../docs/reports/python-pro-wiki-corpus-cleanliness-check.md)).
Spec: [2026-07-07-wiki-llm-judge-eval.md](../../../docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md).

## Handoff files for the gse-translation pipeline

These three files are the input package for translation runs (Danil's pipeline):

| File | What it is |
|---|---|
| [`wiki_original.json`](wiki_original.json) | 2 553 paragraphs, flat JSON array of strings — schema identical to `data/bouquet/bouquet_original.json`. Place as `data/wiki/wiki_original.json`; `02_translate_json.py` consumes it unchanged. |
| [`wiki_index.json`](wiki_index.json) | Sidecar for the same indices: `{i, title, section, par_idx, n_tokens}` — per-article slicing in analysis; not needed by the pipeline. |
| [`pilot_articles.json`](pilot_articles.json) | Pilot subset: 10 articles / 274 paragraphs (length deciles + the article with the longest paragraph + an article with a wiki notice box). Run the pilot first, then the full corpus. |

sha256:

```
7e11c18bb0cd2d58d1eb2c0a5999b331d24c690f98d747985efab1a04a9ebacc  wiki_original.json
bbd61fdda3865a8a2b0b8f3ddf3e137417bd08fb571592e439a20449abdc748a  wiki_index.json
5b047b9a933b4638e901f9024a430933e69495d3f031f16968c730c07c7030d7  pilot_articles.json
```

### Differences from BOUQUET

1. **No reference translations** — ref-based MetricX/COMET cannot be computed; only QE
   variants (MetricX `--qe`, CometKiwi) plus the LLM judge.
2. **37 degenerate paragraphs** (section headings like «Источники», `n_tokens <= 3` in
   `wiki_index.json`): translate as-is, filter at the analysis stage.
3. **Fixed judge config for wiki runs**: `qwen3_6-27b`, `temperature: 0`,
   `enable_thinking: false`, `universal` prompts as-is — so all systems land in one
   comparable table. Alternatively, deliver only `translation.json` per system and
   judging runs centrally. Details: spec §3.

## Other files in this directory

Artifacts of the grounding eval and corpus selection, not part of the translation
handoff: `gt*.jsonl` (ground-truth extractions), `pages/` (cached article HTML),
`selection_v2.json`, `titles_*.txt`.

## cleanup/ — gold anchor-relevance cleanup campaign (2026-07-10)

LLM-assisted removal of clearly history-irrelevant anchors from the raw markup
(modern brands/websites, genetics/chemistry vocabulary, generic everyday words,
language template tags, abstract navigational phrases), later re-verified by a
human. `audit_prompt_v11.md` is the auditor instruction; `removals-wave1/` holds
per-article removal lists for articles 001-010; `overrides_wave1.json` is the
orchestrator verification layer on top of them (restores + added removals +
open questions). `gt.jsonl` itself is NOT modified until the owner approves the
final exclusion list. `tools/` holds the campaign scripts (see headers).
