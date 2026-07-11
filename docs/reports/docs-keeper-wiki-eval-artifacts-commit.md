# docs-keeper: Wiki-Eval Artifacts Commit

## Scope

**Branch:** `claude/ner-translation-config-b0ozsc`  
**Task:** Stage and commit wiki-eval run artifacts (pred.jsonl, pred.partial.jsonl, meta.json, progress.jsonl, calls.jsonl) from `reports/terminology/wiki-eval/` directory, excluding rebuildable cache files ≥50MB.

## Files changed

### Staged and committed (17 files, all run artifacts)

**Modified (M) — existing run-dir state updates:**
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z_alt-names/calls.jsonl` (744K)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z_alt-names/pred.partial.jsonl` (2.5M)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z_alt-names/progress.jsonl` (8.0K)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z_label-guess/calls.jsonl` (956K)

**Added (A) — new run directories:**
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T22-16-28Z/calls.jsonl` (8.0K)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T22-19-00Z/calls.jsonl`, `meta.json`, `pred.jsonl`, `progress.jsonl` (276K total)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T22-48-49Z_alt-names/calls.jsonl`, `meta.json`, `pred.jsonl`, `progress.jsonl` (312K total)
- `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-22-18Z_label-guess/calls.jsonl`, `meta.json`, `pred.jsonl`, `progress.jsonl` (328K total)

**Committed:** [32f61a7](https://github.com/artem-lepin-ml/translation-demo/commit/32f61a7)

### NOT staged — rebuildable caches (4 files, ≥50MB each)

Per task specification, large merged cache files are excluded (not predictions, not critical artifacts):
- `reports/terminology/wikidata_cache_deepseek.jsonl` (645M)
- `reports/terminology/wikidata_cache_gemini.jsonl` (720M)
- `reports/terminology/wikidata_cache_gemma4.jsonl` (162M)
- `reports/terminology/wikidata_cache_qwen36.jsonl` (756M)

Remain untracked in working directory; can be rebuilt by re-running evaluation pipelines.

## Decisions & rationale

1. **Artifact classification:** Run directories and prediction/metadata files (calls.jsonl, pred.jsonl, pred.partial.jsonl, progress.jsonl, meta.json) are irreproducible judge/extraction outputs → stage and preserve as part of evaluation history.

2. **Cache exclusion:** Merged wikidata caches (deduplicated across model runs) are intermediate artifacts, not predictions, and each is independently rebuildable from source data → exclude from commit to keep repo lean.

3. **Size threshold (50MB):** Applied per task spec to distinguish one-off run states (stage <50MB) from bulk ephemeral data (exclude ≥50MB).

4. **Commit message:** Conventional Commits format (`feat(wiki-eval): …`), no AI signatures, describes *what was preserved* (judge/extraction artifacts), not the mechanical action.

5. **Push strategy:** Regular push (no force) succeeded; branch has linear history with no upstream conflicts on this worktree.

## Open questions

None. Task completed as specified.

## NOT done

None. Full scope delivered:
- ✅ Audited all 12 porcelain items (4 modified + 8 untracked dirs)
- ✅ Classified by type and size
- ✅ Staged 8 run-artifact dirs/files (<50MB)
- ✅ Listed 4 cache files for exclusion (≥50MB)
- ✅ Committed with clean message
- ✅ Pushed to remote
- ✅ Verified remaining porcelain (4 untracked caches only)
