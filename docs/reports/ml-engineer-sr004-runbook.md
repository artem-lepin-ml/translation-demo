# ml-engineer report — sr004 local judge + grounding runbook

## Scope

Prepare a copy-paste-ready runbook for the LOCAL vLLM runs the paper still needs on sr004 (4×A100), for
two tables: Table A (BOUQUET LLM-as-a-judge, 3 new local judges: `Qwen3-4B-Instruct-2507`, `Gemma-3-27B-it`,
`Qwen3.6-27B`, T=0, thinking off, prompts `v1_core3`) and Table C (NER+Wikidata grounding, same 3 models as
extractor+judge, sitelink off). No GPU in this session — deliverable is the runbook + config/code ground-truth
so the owner or the sr004 overnight runner executes verbatim. Grounded against `scripts/bouquet_judge_rerun.py`,
`configs/bouquet_judges.yaml`, `scripts/wiki_eval.py`, `docs/stages/translation-eval.md` (Table B's own sr004
runbook, used only as a style/precedent reference, not reused directly), `docs/paper/paper-state.md`,
`docs/reports/overnight-mission-2026-07-09.md`, and real `meta.json` files from the 3 already-completed cloud
grounding runs (`gemini-3.1-flash-lite`, `deepseek-v4-flash`, `qwen3.7-plus`).

## Files changed

- **New**: [docs/runbooks/sr004-local-eval-runbook.md](../runbooks/sr004-local-eval-runbook.md) — the runbook.
  Prereqs, why no base-URL patch was needed (verified live), the `extra_body`/`t0_local` patch rationale,
  per-model vLLM bring-up (sequential, port 8000 reused), Ф0 probe (including a `curl` smoke test for
  `<think>`-leakage), Table A pilot+full+stats commands, Table C pilot+full+report commands, resume semantics,
  commit convention (matches this branch's existing `feat(eval): ...` style), a deliverables checklist, and a
  verified-vs-NOT-verified ledger.
- **`configs/bouquet_judges.yaml`** — appended 3 new judge entries (`qwen3-4b-instruct`, `gemma-3-27b-it`,
  `qwen3.6-27b`), all `enabled: false` with an inline `# enable on sr004` comment, `regime: t0_local`; the
  `qwen3.6-27b` entry also carries `extra_body: {chat_template_kwargs: {enable_thinking: false}}`. Appended
  after the existing 6 cloud entries — no existing entry touched.
- **`scripts/bouquet_judge_rerun.py`** — minimal patch: `JudgeSpec.extra_body: dict[str, Any] | None = None`
  (parsed from YAML in `load_judges()`), a new `t0_local` regime (temperature=0, no `reasoning` key — that key
  is an OpenRouter/CloseRouter convention a raw vLLM server doesn't implement), and an unconditional
  `if judge.extra_body: payload.update(judge.extra_body)` at the end of `build_payload()`.
- **`scripts/wiki_eval.py`** — minimal patch: `extra_body: dict | None` threaded through `_resolve_route`,
  `_build_extract_fn`, `_build_judge`, `_run_one_config`; a new `--extra-body <JSON string>` CLI flag on both
  `run` and `ablate`; `_parse_extra_body()` helper (fails loud on malformed JSON). When passed, it replaces
  the provider-pin `extra_body` default for both extract and judge roles.
- **New**: [tests/test_bouquet_judge_rerun.py](../../tests/test_bouquet_judge_rerun.py) — 5 tests for the new
  `t0_local` regime, `extra_body` merge (present/absent), and YAML parsing (no test file existed for this
  runner before).
- **`tests/test_wiki_eval_runner.py`** — 6 new tests for `_resolve_route`'s `extra_body` parameter and the
  `--extra-body` CLI flag / `_parse_extra_body` helper. Existing 70 tests untouched.
- **Doc-parity (Hard Invariant 2)**: `docs/README.md` (new L1 index row), `docs/paper/paper-state.md`
  ("Execution split" bullet corrected — it pointed at Table B's Danil-pipeline runbook, which is wrong for
  Table A's local judges; now points at the new runbook), `docs/stages/wiki-eval.md` (one sentence in the
  Status sub-section pointing Table C's 3 pending local rows at the new runbook). All three are single-line
  or single-paragraph surgical edits, isolated diffs (verified via `git diff` before committing — no other
  content in any of the three files touched).

Not touched: `external/gse-translation/` (untouched, confirmed); any file another agent had already modified
in this shared working tree before this session started (`docs/experiments/2026-07-05-model-comparison/
sitelink-clean-full-metrics.json`, `scripts/sitelink_clean_full_metrics.py`, `scripts/sitelink_contamination.py`,
`reports/bouquet/judges/summary.md`, the untracked `reports/bouquet/judges/{gemini-3.1-flash-lite-think,
gemini-3.1-pro,gpt-5.5}/` and `reports/terminology/wiki-eval/openai--gpt-5.4--auto/` dirs) — `git status`/
`git diff` checked immediately before every edit and before staging; none of those paths are in this commit.

## Decisions & rationale

**Base-URL routing needed no patch — verified, not assumed.** Both runners already read `OPENROUTER_BASE_URL`
unconditionally in their route-resolution code (`cmd_run`'s `base_url = os.environ.get("OPENROUTER_BASE_URL",
DEFAULT_BASE_URL)` in the BOUQUET runner; `_resolve_route`'s identical pattern in `wiki_eval.py`). Confirmed
live with a `uv run python3 -c "..."` call against the actual module (not just read) with
`OPENROUTER_BASE_URL=http://localhost:8000/v1` — both `extract_base_url`/`judge_base_url` came back as the
localhost URL. `--provider auto` (an existing, already-tested flag) avoids sending an OpenRouter-specific
`{"provider": ...}` field a raw vLLM server wouldn't understand.

**A real gap DOES exist, separate from routing: no way to force `thinking OFF` for Qwen3.6-27B locally.**
`Qwen3-4B-Instruct-2507` and `Gemma-3-27B-it` are non-thinking by construction, so the owner-locked "T=0,
thinking off" protocol is free for them. `Qwen3.6-27B` is a hybrid-thinking model that reasons by default
unless a request carries `chat_template_kwargs: {"enable_thinking": false}` — a first-party vLLM request
field, the SAME mechanism Danil's `models.yaml` already uses for this exact model
(`docs/stages/translation-eval.md`). Neither runner had any way to send this: `bouquet_judge_rerun.py`'s
`build_payload()` had no generic passthrough; `wiki_eval.py`'s `LLMConfig.extra_body` field already existed
and was already fully wired through `LLMClient`, but nothing let the CLI *set* it for the local/closerouter
route. Chose a minimal, additive patch on both files rather than a server-side custom-chat-template workaround
(the latter needs live vLLM/Jinja verification this session cannot do; the client-side patch is pure
request-payload logic, fully unit-testable without a GPU, and consistent with the existing `models.yaml`
`extra_body` convention already established elsewhere in this codebase).

**`t0_local` as a distinct regime, not reusing `t0_no_reasoning`.** `t0_no_reasoning` sends
`reasoning: {"enabled": false}`, an OpenRouter-specific field. vLLM's OpenAI-compat server is generally
permissive about unknown fields, but sending a semantically-meaningless key to a local server is misleading
and untested on this exact server version — `t0_local` sends temperature=0 only, nothing else, and relies on
`extra_body` for anything model-specific. This keeps the regime honest about what it actually does, matching
this codebase's existing pattern (`vendor_default`'s docstring: "true provider defaults, no override either
way").

**`--max-usd 50` for the local grounding runs is a deliberately generous forecast ceiling, not a real budget.**
A local vLLM server reports no `usage.cost`, so `BudgetGuard` falls back to a `gpt-4o-mini`-list-price
estimate purely for tracking/display (`compute_usage_totals`'s `cost_usd_estimated`). Real spend on a local
run is $0 (GPU-hours only) — flagged explicitly in the runbook so the owner doesn't misread a nonzero `spend`
field in `meta.json` as a real dollar cost, and doesn't accidentally cap a free run on a meaningless estimate.

**`--gt data/eval/wiki/gt_v2.jsonl` (100 articles), not the CLI default `gt.jsonl` (20-article pre-v2 pool).**
Confirmed by reading real `meta.json` files from the 3 completed cloud grounding runs — all three show
`n_articles: 100`, which only matches `gt_v2.jsonl`'s line count (100), not the default `gt.jsonl` (20 lines,
counted directly). `data/eval/wiki/gt_v2_sub20.jsonl` (20 lines, confirmed a genuine title-subset of
`gt_v2.jsonl` via a direct Python check) is used as the pilot gate, matching the same file real cloud pilot
segments already used.

**`--article-workers`/`--llm-workers`/`--max-judge-calls` values copied from the real cloud `meta.json`s**,
not invented: `--max-judge-calls 30000` (all 3 real runs used this, far above the CLI's 900 default),
`--article-workers`/`--llm-workers` scaled down slightly from the cloud runs' 10/16 to 6/8 for the local pilot
(conservative starting point for an unmeasured local server, explicitly flagged as tunable up once Ф0
confirms throughput) but left at the cloud runs' own values as an option for the full run.

**vLLM bring-up is ASSUMPTION-heavy, same disclosure style as `docs/stages/translation-eval.md`.** No vendored
`vllm serve` precedent exists for `Gemma-3-27B-it` at all; `Qwen3-4B-Instruct-2507`/`Qwen3.6-27B` precedents
exist in translation-eval.md but were sized for a *translation* role (larger `max_tokens`) — this runbook
picks its own `--max-model-len 16384` (judge/extractor completions top out at 8192) rather than blindly
copying the 32768 translation-role value, explicitly justified rather than copy-pasted. TP sizing
(`Qwen3.6-27B` TP=2, matches translation-eval.md's own precedent for the identical model; the other two TP=1)
and the 80GB-A100 VRAM assumption are both flagged ASSUMPTION per this repo's established convention for
undocumented sr004 hardware facts.

**Sequential, port-reused bring-up (not translation-eval.md's simultaneous 3-port scheme)** — explicitly
requested by the task ("sequential one-model-at-a-time is fine and simpler"), and genuinely simpler here since
Table A/C don't need 3 models answering at once the way Table B's GPU-layout does. One efficiency note added:
if Table B's own Qwen3.6-27B server (GPU2-3, port 8000, kept up continuously per that runbook) happens to
already be running, reuse it instead of starting a duplicate.

**Verification performed in this session (no GPU needed for any of it):** `python3 -m py_compile` on both
patched scripts; `uv run pytest tests/test_wiki_eval_runner.py tests/test_bouquet_judge_rerun.py -q` → 81
passed (70 pre-existing + 11 new); `uv run pytest tests/ -q --ignore=<those two files>` → 501 passed, zero
regression; a live `uv run python3 -c "..."` call exercising `_resolve_route`/`build_payload`/`load_judges`
against the real localhost-pointed env vars and the real (now-patched) `configs/bouquet_judges.yaml`, printed
in the runbook's "Code patches" section verbatim.

## Open questions

- Whether `chat_template_kwargs.enable_thinking=false` actually suppresses `Qwen3.6-27B`'s `<think>` output
  on the specific vLLM build sr004 has installed — this is exactly what the runbook's Ф0 `curl` smoke test
  checks; it cannot be verified from this cloud session. If it doesn't fully suppress, the fallback
  `--reasoning-parser deepseek_r1` flag is already in the bring-up command as a belt-and-suspenders measure
  (same ASSUMPTION already flagged for this exact model in `docs/stages/translation-eval.md`), and any
  residual `<think>` leakage is discoverable (retried once, then logged/counted), not silently corrupting.
- Whether vLLM's guided-JSON backend on the installed build accepts `response_format: {"type": "json_object"}`
  cleanly for all 3 models without extra flags — added as the 3rd Ф0 probe check; not verified here.
- Actual local wall-clock numbers — every runtime estimate in the runbook (BOUQUET ~20–45 min/judge, grounding
  ~1.5–4h/model) is stated as an ASSUMPTION range derived from the cloud runs' network-latency-bound numbers,
  not a local measurement. The runbook tells the operator to measure the pilot's wall-clock first and
  extrapolate rather than trust the range blindly.
- 80GB-A100 VRAM assumption (inherited from `translation-eval.md`'s TranslateGemma-on-one-GPU precedent, never
  independently confirmed against `nvidia-smi` on sr004) — if the cards are actually 40GB, `Gemma-3-27B-it`
  and `Qwen3.6-27B`'s TP sizing in this runbook would need doubling.

## NOT done

- Nothing was actually run on sr004 or against any real vLLM server — no GPU/SSH in this session, exactly as
  scoped. Every command is either grounded in source-reading + this-session's own GPU-free test execution, or
  explicitly marked ASSUMPTION/UNVERIFIED, per the runbook's own closing ledger.
- Did not flip any judge's `enabled: false` → `true` in `configs/bouquet_judges.yaml` — that's the runbook's
  own "what to commit after each run" step, done by whoever actually executes the run on sr004, not by this
  task (no real scores exist yet to justify enabling).
- Did not touch `docs/paper/table-a-judges.tex` / `docs/paper/sections/table-c-grounding.tex` — those get real
  numbers only once the sr004 runs actually produce them; out of this task's scope (runbook preparation only).
- Did not update `docs/reports/overnight-mission-2026-07-09.md` (the live overnight coordination doc other
  background agents check in on hourly) — deliberately left alone to avoid racing with agents actively
  reading/writing it; this task's own deliverable (the runbook) is what that doc's own "PREPARE IT OVERNIGHT"
  line asked for, and updating its own checklist is that document's own maintainer's job, not this report's.
- No HTML/Claude Artifact delivery — this is an engineering-task report (mandatory reporting protocol for a
  named agent), not an owner-facing step-6/8 report under CLAUDE.md's "Reports & communication style" template.
- Did not attempt to determine the exact `--reasoning-parser` name for the sr004-installed vLLM build for
  `Qwen3.6-27B` — same open, unresolved risk `docs/stages/translation-eval.md` already carries for the
  identical model; not re-solved here, just carried forward with the same disclosure.
