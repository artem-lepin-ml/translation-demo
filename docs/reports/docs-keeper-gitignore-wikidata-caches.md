# docs-keeper: .gitignore per-run Wikidata caches

## Scope

Housekeeping task to properly ignore per-run Wikidata API response cache files that accumulate during wiki-eval runs. These are rebuildable (~600 MB each) and should not be tracked in version control.

**Branch**: `claude/ner-translation-config-b0ozsc`

## Files changed

| File | Change | Rationale |
|---|---|---|
| `.gitignore` | Line 66: fixed pattern from `wikidata_cache.*.jsonl` to `wikidata_cache_*.jsonl`; added preceding comment `# per-run Wikidata API caches (rebuildable, 600+MB each)` | Original pattern used dots (`.`) which cannot match underscore-separated filenames like `wikidata_cache_deepseek.jsonl`. This left 4 per-run cache files unignored. |

## Decisions & rationale

1. **Pattern fix**: Changed from `wikidata_cache.*.jsonl` (dot-based glob) to `wikidata_cache_*.jsonl` (underscore-based).
   - Reason: The actual per-run cache files use underscores (`wikidata_cache_{model}.jsonl`), not dots. The dot pattern would only match files like `wikidata_cache.foo.jsonl`, which don't exist.
   - Impact: 4 previously-unignored files (`wikidata_cache_deepseek.jsonl`, `gemini`, `gemma4`, `qwen36`) are now properly excluded from tracking.

2. **Preserved base file ignore**: Left line 41 intact (`reports/terminology/wikidata_cache.jsonl`), which ignores the base warm-up cache.
   - Tracking status: Base file is **not tracked** (verified via `git ls-files`).
   - Rationale: Both base and per-run files are rebuildable and expensive (600+ MB); both belong in `.gitignore`. The base file ignore was already correct.

3. **Added explanatory comment**: Clarified the purpose of the per-run cache ignore pattern in `.gitignore` to future readers.

## Open questions

None. All per-run cache files are now properly ignored and do not appear in `git status --porcelain`.

## NOT done

None. Task completed:
- ✓ Tracked-status finding verified (base file not tracked)
- ✓ `.gitignore` pattern corrected
- ✓ Preceding comment added
- ✓ `git status --porcelain` confirms no wikidata_cache files listed
- ✓ Commit `97dffff` pushed to origin

### Verified code↔doc pairs

| Entity | Code | Doc |
|---|---|---|
| Per-run Wikidata cache ignore | `.gitignore:67` pattern `wikidata_cache_*.jsonl` | `.gitignore:66` comment |
| Base Wikidata cache ignore | `.gitignore:41` pattern `wikidata_cache.jsonl` | `.gitignore:40` comment |

