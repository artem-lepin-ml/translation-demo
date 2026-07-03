# Wiki-evaluation (E1+E2) — implementation plan

Up-link: spec [2026-07-03-wiki-eval-design.md](../specs/2026-07-03-wiki-eval-design.md). Branch `feat/wiki-eval` off G6 (`bf3cec2`). Test command: `PYTHONPATH=src /Users/a1111/Projects/Work/worktrees/grounding-label-first/.venv/bin/python -m pytest tests/ -q` (reused venv resolves `palimpsest` to THIS worktree via PYTHONPATH). Conventional Commits, no Co-Authored-By trailer. All modules under `src/palimpsest/terminology/evaluation/`.

Pinned constants (spec §11): HTML parser `BeautifulSoup(html, "lxml")`; tokenizer `re.split(r"\s+", nfc+nbsp→space)`, punctuation attached, global index no per-paragraph reset; chrono P31 set `chrono_p31_v1` = {Q3186692, Q39911, Q578, Q3311614, Q29964144, Q14795564, Q18340514}; underpowered cell n<30; MAX_JUDGE_CALLS=900, default --max-usd 40, judge max_tokens 512.

## Task sequence

| Task | Files | Depends |
|---|---|---|
| W1 tokenize | `evaluation/tokenize.py` + tests | — |
| W2 matching+metrics | `evaluation/matching.py`, `evaluation/metrics.py` + tests | — (pure, tuple-level) |
| W3 wiki_gt | `evaluation/wiki_gt.py` + tests | W1 |
| W4 predict | `evaluation/predict.py` + tests | W1, G6 extractor/grounding |
| W5 report+CLI | `evaluation/report.py`, `scripts/wiki_eval.py` + stage doc | W1-W4 |
| W6 build-gt sample + eval pilot | run, commit artifacts (LFS) | W3-W5 |

### W1 — tokenize.py
`flatten(html)->str` (BeautifulSoup lxml, body `<p>` paragraphs joined by `\n`, drop infobox/navbox/reference/table nodes; NFC+NBSP→space), `tokens(text)->list[str]` (`re.split(r"\s+")`, drop empties, punctuation attached), `char_to_token_index(text, char_pos)->int` (count tokens before offset, global). Tests: NBSP/multi-space/attached-punct fixture → exact token list; char→index round-trip.

### W2 — matching.py + metrics.py
`matching`: pure functions M1 strict (index+norm(word)+qid), M2 span-overlap (token spans overlap + qid; span_len drives overlap; NO surface compare), M3 document (`(norm-lemma, qid)` anywhere). Tuple = `(index, surface, qid, span_len)`. Reuse G6 `grounding/match.norm`.
`metrics`: recall (3 modes), precision P1/P2(dedup by (lemma,qid))/P3(label-justified, per resolved_by, NEVER unsliced aggregate), slices (stratum/resolved_by/type), Wilson CI per cell (reuse `eval_harness.wilson_ci`), underpowered-flag n<30, → metrics.json. Tests: M1/M2/M3 on hand-built sets incl multi-word overlap + inflected (norm+lemma); recall/precision arithmetic; slice sums back to totals; underpowered flag; P3 refuses unsliced aggregate.

### W3 — wiki_gt.py
Article selection (pool from ru-wiki history categories; hardness = share of ambiguous anchors: piped-link anchor≠title + anchor→different-QID-across-pool; strata 50 hard + 50 typical; forced seeds; disclose seed count/percentile). Parsoid/REST HTML fetch (`https://ru.wikipedia.org/api/rest_v1/page/html/<title>` or action=parse) + cache to `data/eval/wiki/pages/<title>.html` (LFS). GT-tuple extraction from anchors (main-namespace links only; multi-word → (first-token index, surface, qid, span_len)). Batched title→QID (own pageprops fetcher, ≤50 pipe-joined titles, redirects=1, record anchor_target_title + canonical_title). Filters: chrono by §11 P31 set (store version hash in gt.jsonl); counters n_no_qid/n_redlink/n_fetch_failed/n_malformed_html (E-D17), fail-loud >10%. Determinism: no set-ordering in serialized output, sort before dump, named parser. Tests: anchor extraction from fixed HTML fixture; redirect-chain canonicalization; chrono filter; hardness on crafted page; failure counters on fixtures.

### W4 — predict.py (E-D16 bridge)
`predict_tuples(article_text, paragraphs, extractor, grounder, judge, judge_cache)`: feed each paragraph to G6 extractor, track running base offset → global char pos → `char_to_token_index` → pair mention with grounding `chosen_qid` → predicted `(index, surface, qid, span_len)`. Canonicalize predicted QIDs through the same redirect path as GT (E-D18). Carry the G6 trace for resolved_by slicing. Tests: multi-paragraph fixture, mention in 3rd paragraph → GLOBAL index correct (offset stitching); lemma≠surface pairs to right QID.

### W5 — report.py + scripts/wiki_eval.py
CLI subcommands (spec §3): `build-gt` (free), `run --config` (paid: extractor+judge, OpenAI direct gpt-4o-mini per [[project_provider_keys_night_0703]] — OR/CloseRouter keys dead), `ablate` (loops run), `report` (offline recompute → metrics.json + dark-theme HTML in report palette + EN §7 methodology emitter). Budget: pre-call reservation, --dry-run forecast aborts if > cap. Stage doc `docs/stages/wiki-eval.md` + pipeline.md link; §7 methodology verbatim.

### W6 — build-gt sample + pilot
Run `build-gt` on a small real sample (10-20 history articles) to prove end-to-end (real Wikipedia + title→QID). Then a small `run` pilot on ~3-5 articles with the OpenAI judge (cents) to prove predict+matching+metrics end-to-end. Commit gt.jsonl + cached HTML + pilot metrics (LFS). Full 100-article run documented as ready-to-launch (scale = article list + budget).

## verify-pr
After W5: read-only reviewers on correctness (tuple/index/offset), data (determinism, GT extraction, redirect), R&D (metric defensibility). Fix loop. Then W6.
