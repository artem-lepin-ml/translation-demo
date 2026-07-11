# Judge x3 survival-score refresh — 2026-07-11T04:2x UTC

## Scope
Urgent (≤8 min budget), owner-waiting: refresh the judge x3 survival scores
(baseline / alt-names / label-guess, all `google/gemma-3-27b-it (Parasail)`,
run family `2026-07-10T23-40-53Z*`) against the CURRENT snapshot of
progress/pred files, reusing the existing driver from a prior lane
(`scratchpad/final-scoring/driver.py`). Also: one-line process-state check
(alive/DEAD) for all 7 live wiki_eval runs, and a total spend-ledger sum.
No repo code/contract changes, no commits, no API keys touched, no dead-run
resurrection (explicitly out of scope, handled by a separate lane).

## Files changed
Repo: none.

Scratchpad only (`/tmp/claude-0/.../scratchpad/final-scoring/`):
- `snapshot_refresh/{baseline,alt-names,label-guess}/{progress.jsonl,pred.partial.jsonl}` — fresh copies taken at 2026-07-11T04:23:49Z from the live run dirs under `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T23-40-53Z*`.
- `driver_refresh.py` — copy of `driver.py` narrowed to the judge x3 section only (extraction/no_judge rows intentionally NOT recomputed — not requested this pass; reused verbatim from the prior `scores.json`).
- `scores_refresh.json` — refreshed judge x3 survival output.

## Decisions & rationale
- **Reused the existing driver's metric logic verbatim** (`aggregate_survival` from `palimpsest.terminology.evaluation.metrics`, tier_assignment + anchor_exclusions applied gold-side) rather than re-deriving it, per the task's explicit "reuse it" instruction and to guarantee comparability with the 01:44Z baseline numbers.
- **Only judge dirs re-snapshotted**; extraction (no_judge) rows left untouched — task scope was explicitly "judge x3", and re-copying+rescoring 4 more multi-MB pred files wasn't worth the time budget for a metric that wasn't asked for.
- **Process-state check was file-mtime-based, not PID-based** — see Open questions below; this is a material caveat, not swept under the rug.

## Findings

**Refresh snapshot: 2026-07-11T04:23:49Z** (progress/pred copy time). Report generated 2026-07-11T04:25Z.

### Article intersection (judge x3 family)
| run | own completed articles (progress.jsonl) |
|---|---|
| baseline | 25 |
| alt-names | 25 |
| label-guess | 20 |
| **intersection (all 3)** | **20** (label-guess's set, fully contained in the other two — same pattern as the 01:44Z snapshot, just grown from 14/14/11→11 to 25/25/20→20) |

### Judge x3 survival metrics (matched/total, intersection n=20 articles)
| mode | R_NER | R_search | A_disamb | R | P | spend so far ($) |
|---|---|---|---|---|---|---|
| baseline | 755/850 (88.8%) | 619/755 (82.0%) | 589/619 (95.2%) | 589/850 (69.3%) | 620/1177 (52.7%) | 0.0788 |
| alt-names | 755/850 (88.8%) | 616/755 (81.6%) | 585/616 (95.0%) | 585/850 (68.8%) | 616/1165 (52.9%) | 0.0856 |
| label-guess | 755/850 (88.8%) | 629/755 (83.3%) | 594/629 (94.4%) | 594/850 (69.9%) | 627/1254 (50.0%) | 0.0946 |

R_NER is identical across all three (same NER stage output over the same 20-article intersection, judge mode only affects search/disambiguation downstream) — expected, not an anomaly.

### Process state (7 runs total)
`ps aux | grep wiki_eval` in this Bash tool's sandbox returned **no matching process** — confirmed via a full `/proc` scan (only session/MCP infra processes present; this container booted 2026-07-11T04:19Z, i.e. after these eval runs started, and is isolated from wherever the driver processes actually execute). Alive/DEAD below is therefore inferred from file-mtime recency (`progress.jsonl` / `calls.jsonl`), not a real PID check — flagged explicitly, see Open questions.

| run | progress.jsonl last write (UTC) | calls.jsonl last write (UTC) | done | inferred state |
|---|---|---|---|---|
| baseline (judge) | 04:06:03 | 04:10:10 | 25 | ACTIVE — calls.jsonl still being written ~14 min before check, checkpoint pending on current article |
| alt-names (judge) | 04:05:02 | 04:10:09 | 25 | ACTIVE — same pattern |
| label-guess (judge) | 04:03:08 | 04:10:10 | 20 | ACTIVE — same pattern |
| gemini 20-19-19Z | 04:01:05 | 04:01:15 | 49 | STALLED/DEAD-suspect — no write activity for ~23 min at check time, no PID visible |
| qwen 20-19-44Z | 02:27:03 | 02:27:24 | 53 | DEAD — no write activity for ~117 min |
| gemma4 20-20-09Z | 04:09:03 | 04:10:44 | 27 | ACTIVE — calls.jsonl ~14 min before check |
| deepseek 20-20-34Z | 02:29:07 | 01:01:29 (calls older than progress) | 60 | DEAD — no write activity for ~115 min |

### Spend ledger (last progress.jsonl line per run, sum across all 7)
| run | spent ($) |
|---|---|
| baseline | 0.0788 |
| alt-names | 0.0856 |
| label-guess | 0.0946 |
| gemini 20-19-19Z | 3.4713 |
| qwen 20-19-44Z | 1.4895 |
| gemma4 20-20-09Z | 0.6297 |
| deepseek 20-20-34Z | 1.0463 |
| **total** | **$6.8958** |

## Open questions
- Process-state table is mtime-inferred, not PID-confirmed — this sandbox has no visibility into the actual driver processes' process table. If a real alive/DEAD confirmation is needed, it must come from whatever session/container actually launched the 7 `wiki_eval` runs.
- gemini/qwen/deepseek show no recent write activity; whether they are truly dead, rate-limited, or mid-long-article is not distinguishable from file mtimes alone.

## NOT done (explicit)
- No resurrection of stalled/dead runs (qwen, deepseek, possibly gemini) — explicitly out of scope per the task, handled by a separate lane.
- Extraction (no_judge) survival rows NOT refreshed — only judge x3 was requested; the 01:44Z snapshot numbers for those 4 runs (gemini/qwen/gemma4/deepseek extraction-mode survival) still stand in `scratchpad/final-scoring/scores.json`.
- No repo commit of this report or of any scratchpad artifact (per explicit "NO commits" instruction).
- No real PID-based process check (see Open questions).
