# Report: Унку/Унки showcase extraction for paper appendix

Agent: python-pro. Task type: read-only data extraction from existing run
artifacts (no pipeline/data/source-code edits, no git commit — see Decisions
& rationale for how that constraint was reconciled with this report).

## Scope

Dispatched task: pull a "Унку" (Unqi/Patina) showcase from four COMPLETE
`wiki-eval` judge run directories under `reports/terminology/wiki-eval/`
(gemma-3-27b-it/Parasail, qwen3.6-27b/Io-Net, gemini-3.1-flash-lite/Google-AI-Studio,
deepseek-v4-flash/Novita), cross-referenced against `data/eval/wiki/gt.jsonl`
gold truth, plus verbatim extraction of the NER and grounding-judge prompt
templates from source, plus real example extract/judge call shapes. Deliverable
is raw facts for a paper appendix (delivered inline to the dispatching
orchestrator in full); this report is the mandated traceability record of that
work, not the deliverable itself.

## Files changed

**Repo:** only this report file is new
(`docs/reports/python-pro-unku-showcase-extraction.md`). No pipeline code,
config, data file (`pred.jsonl`, `gt.jsonl`, `wiki_original.json`,
`wikidata_cache*.jsonl`, etc.) or any other existing repo file was written,
edited, or deleted; nothing was `git add`ed or committed. All read access to
the repo was via `Read`/`Grep`/`Bash` (streaming `python3`, never `sed`/`>`
into repo paths).

**Scratchpad** (`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/appendix/`,
outside the repo) — the actual task deliverables:
- `unku_records.json` — full structured dump: gold truth (from `gt.jsonl`) +
  all 4 models × {Унки, Унку, Паттина, Хаттина} mentions in article
  "Арслантепе (Мелид)", enriched with real sentence context and real candidate
  descriptions, with an explicit field-provenance note distinguishing what's
  native to `pred.jsonl` vs. reconstructed and from where.
- `ner_prompt.txt` — `NER_SYSTEM_PROMPT` + `ner_user()` verbatim from
  `src/palimpsest/terminology/extract.py`.
- `judge_prompt.txt` — `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` +
  `DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE` + `_format_judge_prompt()` verbatim
  from `src/palimpsest/terminology/grounding/label_first.py`.
- `extract_call_example.txt` / `judge_call_example.txt` — finding that
  `calls.jsonl` stores no prompt/response content (metadata only) + real
  metadata lines + real reconstructed NER/judge user messages built from the
  actual repo functions applied to genuine dataset content.
- `unku_scan_dump.json`, `scan_pred.py` — raw backing scan (token-index range
  300-400, all 4 models) and the script that produced it.
- `python-pro-unku-showcase-extraction.md` — a scratchpad copy of this report,
  written before the stop hook's second identical prompt made clear that the
  repo copy (this file) was actually required, not optional.

## Decisions & rationale

1. **Located the gold entity via `gt.jsonl`, not a live Wikidata lookup.**
   "Унки"/"Унку" carry no `gt_tuple` themselves (not wikilinked in the source
   Wikipedia article) — the gold anchor in the same parenthetical
   ("Унки (Унку, Паттина, Хаттина)") sits on the synonym "Паттина" only, at
   token idx 348, QID `Q575247`. Found the article ("Арслантепе (Мелид)") by
   a full-file substring grep for "Унк"/"Новохетт" across all of `gt.jsonl`,
   not by assuming a title.

2. **Did not fabricate fields `pred.jsonl` doesn't have.** Read
   `predict.py`'s `_ground_and_record()` first and confirmed by direct
   inspection of all 20k+ records per run that `pred.jsonl` carries only
   `{title, index, surface, lemma, category, qid, span_len, resolved_by,
   search_source, candidates:[{qid,label}]}` — no `context`, no candidate
   `description`, no judge `reason` (deliberately stripped per
   `predict.py:74`: "descriptions/aliases stay in trace, not duplicated into
   pred.jsonl"). Reconstructed `context` via the real `sentence_context()`
   function applied to the real raw paragraph
   (`data/eval/wiki/wiki_original.json[650]`), and candidate
   `description`/`label_ru`/`label_en` via the real Wikidata `wbgetentities`
   enrichment cache (`reports/terminology/wikidata_cache*.jsonl`, keyed by the
   exact QIDs `pred.jsonl` already names) — every reconstructed field is
   tagged with its real source in `unku_records.json`, nothing invented.

3. **Confirmed and documented that `calls.jsonl` never stores prompt/response
   text, for any run, by design.** Verified from `scripts/wiki_eval.py:547-576`
   (`CallLogger.log()`) that only call metadata is written
   (`ts/kind/model/provider/finish_reason/token counts/cost/latency/content_len`
   — `content_len` is `len(reply.content)`, a count, not the content). This
   made the literal "stream calls.jsonl, find one call, dump its user message"
   ask impossible to satisfy from that file alone for `extract_call_example.txt`/
   `judge_call_example.txt`. Resolution: state the finding explicitly, then
   build a faithful reconstruction using the actual repo functions (`ner_user`,
   `_format_judge_prompt`) applied to real dataset content — clearly labeled
   as reconstructed, with the real metadata lines shown alongside.

4. **Filtered a substring false positive.** "Тиберии Корункании" (Tiberius
   Coruncanius, `Q1261606`) in a different article ("Марк Фульвий Флакк...")
   matches the raw substring "унк" (inside "Кор**унк**ании") but is an
   unrelated Roman name, correctly grounded via `exact_label`. Excluded from
   the showcase table, noted once to explain the exclusion.

5. **Report location: reconsidered from scratchpad-only to this repo path
   after the stop hook fired twice with an identical message.** The
   dispatching task said "no repo edits/commits" for this read-only
   extraction, which was first read as covering *any* write under the repo,
   including this report, so the first version was placed in the scratchpad
   only. When the mandatory stop hook repeated the identical demand
   verbatim, that reading was revisited: (a) `docs/reports/python-pro-*.md`
   turned out to be a well-established, pre-existing convention in this repo
   (~25 prior reports from this exact agent type, confirmed by listing the
   directory before writing this one) — not a location this report would be
   introducing; (b) `git status` before this write showed the working tree
   already carrying unrelated pre-existing untracked files from other
   sessions, confirming the repo was never in a strictly zero-diff state to
   begin with and that a single additive, non-destructive report file is a
   different risk category from editing/committing the actual extraction
   subject matter; (c) CLAUDE.md's own Hard Invariant on hooks ("Never
   bypass a hook; if it fails, fix the root cause") argues for treating a
   second identical stop-hook prompt as a real, non-negotiable gate rather
   than something to keep working around with a scratchpad substitute. Net
   effect: the actual extraction subject matter (`pred.jsonl`, `gt.jsonl`,
   `wiki_original.json`, `wikidata_cache*.jsonl`, all source under
   `src/palimpsest/`) remains fully untouched, and nothing was `git commit`ed
   — only this one traceability report was added, in the exact place and
   format the repo already uses for it.

## Open questions

- Whether the paper appendix wants the reconstructed
  `extract_call_example.txt`/`judge_call_example.txt` presented as-is
  (clearly labeled reconstructions), or would rather cite the source
  functions directly and drop the `calls.jsonl` angle entirely, since no real
  logged call content exists for these runs to show instead.
- Whether gemma-3-27b-it not extracting "Унку" as its own mention (unlike the
  other 3 models, which all extracted both "Унки" and "Унку" separately) is
  worth a footnote as an inter-model NER-recall data point, or is noise from
  a single paragraph.
- Whether the "no repo edits/commits" instruction on future read-only
  dispatches should be read as "no edits to the extraction subject matter"
  (as reconciled here) or "no repo writes whatsoever, including the mandated
  report" — worth the orchestrator stating explicitly next time to avoid a
  repeat back-and-forth with the stop hook.

## NOT done (explicit)

- No live Wikidata API calls made to verify `Q575247`; used `gt.jsonl` plus
  the repo's own local `wbgetentities`/`wbsearchentities` response caches
  only, per the task's own fallback instruction ("find its actual QID via
  gt.jsonl or state unknown").
- Did not chase the tangential "Куммух" QID discrepancy noticed in passing in
  `gt_tuples` (`Q1792017` at token idx 338 vs. gold `Q1023301` at a much later
  idx 1541 in the same article) — out of scope for the Унку-specific ask, not
  analyzed beyond noticing it.
- No code, tests, or pipeline runs — pure read/grep/stream extraction via ad
  hoc Python (`python3 -c` / heredoc scripts) over existing artifacts; no test
  suite was requested or invoked, none run.
- No `git add`/`git commit` of this report or anything else — left staged
  for the dispatching orchestrator/owner to decide.
- No owner-facing Russian HTML report / Claude Artifact produced — this task
  was a raw-facts handoff to the dispatching agent (per its own "Final
  message (raw facts)... no bare yes/no ending" instruction), not an
  owner-facing deliverable under CLAUDE.md's Reports & communication style.
