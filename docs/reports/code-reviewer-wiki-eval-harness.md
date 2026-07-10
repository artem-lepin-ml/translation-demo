# Report — adversarial review of the wiki-eval grounding harness (pre-redo)

> Provenance: findings produced by a read-only `code-reviewer` agent (Sonnet)
> on 2026-07-10 at the orchestrator's request, ahead of the experiment-v2 redo
> (spec `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md`). The
> agent session had no Write tool, so the orchestrator persisted the findings
> verbatim. Read-only review; no code changed.

## Wiki-eval grounding harness — adversarial read-only review findings

Ranked by evaluation-result-bias severity. New findings only (the 3
pre-identified bugs — extraction max_tokens=4096 truncation, ±40-char judge
context, gt.jsonl drift — are covered elsewhere).

### CRITICAL

**1. `parse_surfaces()` silently returns `[]` on any malformed extraction JSON — uncounted anywhere.**
`src/palimpsest/terminology/extract.py:110-133`, called from `scripts/wiki_eval.py:463` (`return parse_surfaces(reply.content)`).
Three failure shapes all collapse to `[]` with zero signal: (a) truncated/malformed JSON → `except (JSONDecodeError, ValueError): return []`; (b) valid JSON shaped as a single object not an array → `for item in data if isinstance(data, list) else []` never loops; (c) a well-formed array followed by trailing commentary containing brackets → the greedy `re.search(r"\[.*\]", DOTALL)` (line 113) slices first `[` to last `]`, producing garbage. None raise, so `FailureTracker` (`wiki_eval.py:530-539`, which only catches `is_transient_error` exceptions) never records them. Sibling of the known max_tokens=4096 truncation bug — truncation triggers path (a), and this is why that bug's recall loss is invisible in meta.json.
*Failure scenario:* a chattier/higher-temperature model in the redo silently yields zero mentions on a fraction of paragraphs, uniformly deflating that model's recall with no artifact to detect it.

**2. Judge budget/`--max-judge-calls` exhaustion is absorbed as ordinary `judge_unavailable`, uncounted.**
`scripts/wiki_eval.py:613-614` raises plain `RuntimeError` from `BudgetGuard.can_reserve`; caught by `LabelFirstGrounding.ground()`'s catch-all at `src/palimpsest/terminology/grounding/label_first.py:162-175` → `resolved_by="judge_unavailable"`. `is_transient_error()` (`src/palimpsest/llm/client.py:77-96`) does not recognize a bare `RuntimeError`, so `tracker.record_failed_judge_call()` (`wiki_eval.py:639/651/658`) never fires. The article-start guard check (`wiki_eval.py:913-914`) only blocks *new* articles; articles already in flight when the cap trips get a silent burst of yellow.
*Failure scenario:* `MAX_JUDGE_CALLS=900` (`wiki_eval.py:137`) trips mid-run; whichever titles are mid-flight get artificial `judge_unavailable`, misread in `slices.resolved_by` as "the judge struggled with these articles."

### HIGH

**3. `--resume` restores only `guard.spent`, not the call/kind counters — breaks the hard judge ceiling and corrupts meta.json.**
`scripts/wiki_eval.py:1104-1131` sets only `guard.spent = ...["spent"]`; `BudgetGuard.__init__` (`wiki_eval.py:257-264`) always zeroes `calls_by_kind`/`spent_by_kind`. The `MAX_JUDGE_CALLS` ceiling is thus per-invocation, not per logical run — N container restarts (already observed twice in 1.5h per the Checkpointer docstring) multiply it by N. Post-resume `meta.json` is self-inconsistent: `spend.extract + spend.judge != spend.total`, and `n_pred_mentions` (`wiki_eval.py:1035`, computed from local non-merged records) undercounts vs. the merged `pred.jsonl`.
*Failure scenario:* another mid-run restart during the redo silently pushes total judge-call volume past the configured cap and misreports spend/counts for cost auditing.

**4. No `--temperature`/`--max-tokens` flag; both hardcoded; the only override drops the provider pin; neither is recorded.**
Hardcoded `temperature=0` at `wiki_eval.py:448` (extractor) and `:607` (judge), judge `max_tokens=JUDGE_MAX_TOKENS=512` (`:72,:607`). `_build_parser()` exposes no generation-param flags. The one lever, `--extra-body`, *replaces* rather than merges the pin in `_resolve_route` (`wiki_eval.py:108-111`): `if extra_body is not None: cr_extra_body = extra_body` — using it for the redo's params silently drops `{"provider": cr_provider}`, risking the reseller-padded-provider scenario the file's own comment warns of (`wiki_eval.py:62-63`). `meta.json` (`wiki_eval.py:1172-1198`) never records temperature or max_tokens.
*Failure scenario:* baseline and redo sit under the same model/provider/config slug with no artifact distinguishing their generation params; a metric delta gets misattributed to grounding-config bits, or the redo silently routes off provider-9.

### MEDIUM

**5. `judge_cache` key omits sentence context — cache collision across contexts.**
`src/palimpsest/terminology/grounding/label_first.py:127-146`: `cache_key = (scope_id, norm(lemma or surface), tuple(sorted(qids)))`. Documented as "one sense per discourse," but a single (possibly truncated-context) bad verdict is replayed onto every later mention sharing lemma+candidate-set in the article — amplifying the known truncated-`Sentence context` bug (context built at `extract.py:91-97`, `CONTEXT_PAD=40`, injected at `label_first.py:36/57`).
*Failure scenario:* a genuine homonym (same lemma, same candidate QIDs, two referents in one article) is forced onto one verdict for both occurrences.

**6. Reask rationale comment hardcodes the temperature=0 assumption.**
`scripts/wiki_eval.py:548-551`: "...since temperature=0 against the same prompt+system would otherwise very likely reproduce the exact same malformed reply." Premise becomes false if the redo raises temperature; functionally harmless but a stale reasoning hazard for the next tuner.

### LOW / clarifying

**7. No sentence-splitter exists anywhere.** `_context()` (`extract.py:91-97`) is a pure ±40-char window — so there is no RU-abbreviation ("до н. э.") mis-split sibling bug, but it also means widening `CONTEXT_PAD` alone won't fix the known truncation bug; real sentence-boundary detection is required.

**8. `validate_surfaces` drop count discarded.** `extract.py:136-152`, called as `valid, _ = validate_surfaces(...)` (`extract.py:235`) — no visibility into hallucinated (non-substring) vs. genuinely-absent surfaces when comparing models.

**9. Retry-vs-accounting slack.** `_complete_with_slot` (`wiki_eval.py:363-396`) can burn up to `RESILIENT_ATTEMPTS-1` real network attempts per one `reserve`/`settle` pair — minor spend imprecision, not a scoring issue.

**10. Asymmetric budget-exhaustion handling.** Extraction-side `can_reserve` failure (`wiki_eval.py:451-452`) is uncaught and crashes the run, unlike the judge side (finding 2) — recoverable via `--resume` but subject to finding 3's ceiling reset.

### Checked and clean
- `WikidataClient` locking (`wikidata.py`) — cache dict lock and network semaphore correctly separated; no corruption path.
- GT/pred paragraph segmentation identical on both sides (`wiki_gt.py:174` vs `wiki_eval.py:974/1023`), enforced loudly by `predict.py:57-62`'s join invariant.
- Judge `qid`/`null` verdict parsing (`label_first.py:177-217`) — loud and correct, no silent miscount.
