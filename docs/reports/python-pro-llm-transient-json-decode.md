# `is_transient_error` malformed-JSON widening — safety analysis + transport-boundary fix

## Scope

Mission: classify malformed/non-JSON provider HTTP response bodies as transient
(retryable) in `palimpsest.llm.client.is_transient_error` — motivated by the
2026-07-10 wiki-eval deepseek mini-pilot, where a raw `json.decoder.JSONDecodeError`
from httpx's `response.json()` (inside the `openai` SDK's transport parsing) killed a
run on the first occurrence because `is_transient_error` classified it as
deterministic (see [docs/reports/wiki-eval-v2-pilot-2026-07-10.md](wiki-eval-v2-pilot-2026-07-10.md),
"Phase 3a").

The task carried a mandatory pre-flight safety check: grep every caller of
`is_transient_error` and confirm that LLM-**content** parse failures (as opposed to
malformed HTTP **transport** bodies) can never reach those call sites as a raw
`json.JSONDecodeError` — because such a widening would make them silently retried
instead of terminal. Two rounds:

1. **Round 1 (STOP).** A naive "treat every `json.JSONDecodeError` as transient"
   widening was found unsafe: `src/palimpsest/webapp/app.py:_judge_live` calls
   `judge_one` (`src/palimpsest/webapp/judge.py`) via `asyncio.to_thread` entirely
   inside the `is_transient_error`-gated retry loop, and `judge_one` bundles the
   transport call with a content-level `_parse_json(result.content)` that raises a
   genuine `json.JSONDecodeError` on malformed model output. Per the mission's
   explicit instruction, this was reported instead of implemented — no code changed
   in that round.
2. **Round 2 (orchestrator decision, implemented here).** Rather than either of the
   two remediation options proposed in round 1 (decouple `judge_one`, or scope
   retries per-call-site), the orchestrator directed disambiguating **at the
   transport boundary** inside `LLMClient.complete()` itself: wrap ONLY the
   `chat.completions.create(...)` call, converting a `json.JSONDecodeError` raised
   there into a new `MalformedProviderResponseError`, and classify only that
   (plus `openai.APIResponseValidationError`) as transient. A bare
   `json.JSONDecodeError` — as raised by any caller-side content parse, including
   `judge_one`'s — never reaches this wrapping and stays terminal. This makes the
   fix safe by construction rather than by call-site discipline.

## Files changed

- `src/palimpsest/llm/client.py` — added `MalformedProviderResponseError` (a
  `RuntimeError` subclass); `LLMClient.complete()` now wraps only
  `self._client.chat.completions.create(**kwargs)` in
  `try/except json.JSONDecodeError as exc: raise MalformedProviderResponseError(str(exc)) from exc`;
  `is_transient_error` classifies `MalformedProviderResponseError` and
  `openai.APIResponseValidationError` as transient, with the docstring extended to
  state the transport/content disambiguation explicitly; `complete_retrying`'s
  docstring updated to say "malformed-response-body" retries and drop the stale
  "malformed JSON" from its "propagates on first hit" list (that phrase now only
  applies to content-level parse failures, which this method never sees).
- `tests/test_llm_transient.py` — module docstring rewritten to state the new
  transient/terminal split; added `MalformedProviderResponseError(...)` and a
  constructed `openai.APIResponseValidationError` to the transient-classified
  parametrize list; removed the bare `json.JSONDecodeError` case from the
  deterministic-classified list and replaced it with a dedicated
  `test_content_level_json_decode_error_stays_deterministic` regression pin (still
  asserts `is_transient_error(json.JSONDecodeError(...)) is False`, now with an
  explanatory docstring tying it to the `judge_one` finding); added
  `test_complete_wraps_transport_json_decode_error`, which drives a fake
  `chat.completions.create` that raises `json.JSONDecodeError` through
  `LLMClient.complete` and asserts it raises `MalformedProviderResponseError`
  instead (`APIResponseValidationError` was directly constructible —
  `openai.APIResponseValidationError(response=httpx.Response(...), body=None)` — so
  no skip-with-reason was needed).
- `docs/known_issues.md` — new entry "RESOLVED 2026-07-10: malformed provider
  response body killed a wiki-eval run", describing symptom, root cause, the
  round-1 safety finding, and the round-2 transport-boundary fix, with a run-dir
  reference to `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-10T08-38-16Z`.
- `docs/subsystems/webapp.md` — doc-parity for the behavior change (Hard Invariant
  2; not in the mission's explicit file list, but the retry behavior it documents
  changed): the `llm/client.py` table row and the "Transient-error retry (per
  criterion)" paragraph both updated to mention
  `MalformedProviderResponseError`/`APIResponseValidationError` as now-transient and
  to spell out that a caller-side content parse (`judge_one`'s `_parse_json`) still
  raises a plain `json.JSONDecodeError` and stays terminal.
- `docs/reports/python-pro-llm-transient-json-decode.md` — this report, rewritten
  from the round-1 STOP-and-report version to describe the final implemented
  design.

## Decisions & rationale

**Why the transport-boundary wrap instead of the two round-1 options.** Both
round-1 options (decouple `judge_one`, or scope retries per-call-site) require
correct discipline at every current AND future call site that might bundle a
transport call with content parsing — a convention that's easy to violate silently
later. Wrapping `json.JSONDecodeError` only around `LLMClient.complete()`'s own
`chat.completions.create(...)` call makes the distinction structural: `complete()`
raises `MalformedProviderResponseError` for a bad HTTP body and returns a
`LLMResult` for anything that parsed successfully; any `json.JSONDecodeError` a
caller sees afterwards is, by construction, from the caller's own parse of
`result.content`, never from the transport layer. This holds regardless of how a
future call site structures its retry loop.

**Re-verification of the `judge_one` path (per the orchestrator's explicit
instruction to re-grep and confirm).** Re-ran the same trace as round 1:
`judge_one` (`src/palimpsest/webapp/judge.py:141-159`) calls
`client.complete(system, user)` — which now raises `MalformedProviderResponseError`
on a malformed transport body, correctly retried by `_judge_live` — followed by
`_parse_json(result.content)` (`judge.py:86-99`), which still raises a **plain**
`json.JSONDecodeError` on malformed model-generated text at line 95/99. That plain
`json.JSONDecodeError` propagates out of `judge_one`, through `asyncio.to_thread`,
into `_judge_live`'s `except Exception as exc: if is_transient_error(exc)` check
(`app.py:517-518`) — and since `is_transient_error` does NOT special-case bare
`json.JSONDecodeError` (only `MalformedProviderResponseError` and
`openai.APIResponseValidationError`), this still returns `False`: **terminal,
exactly as before the change.** Confirmed both by static trace and by the new
regression test `test_content_level_json_decode_error_stays_deterministic` (asserts
`is_transient_error(json.JSONDecodeError(...)) is False` directly) plus
`test_complete_wraps_transport_json_decode_error` (asserts the wrapping is scoped
to the transport call, not to `complete()`'s caller).

The other three call sites re-checked in round 1
(`scripts/wiki_eval.py`'s extraction/judge closures, `translate.py:_translate_one`,
`app.py:_grounding_judge_live`) are unaffected by this design change — they were
already safe in round 1 by having their content parsing physically outside the
retried unit, and remain so; they simply also gain the new transient-retry benefit
for genuine transport-level malformed bodies via `client.complete()`.

**Docstring/doc updates.** `is_transient_error`'s docstring and
`complete_retrying`'s docstring were both touched because their prose asserted
"unparseable JSON... NOT transient" as a blanket statement, which is no longer
accurate without the transport/content qualifier — left uncorrected, the docstring
itself would mislead a future reader into re-introducing the round-1 bug.
`docs/subsystems/webapp.md`'s retry-behavior paragraph carries the same
information for `_judge_live` specifically, since that's the one call site where
the transient/terminal split is load-bearing (the other three sites don't route
content parsing through the retry loop at all).

## Open questions

None blocking. One residual observation for the owner, not a decision needed now:
the fix as implemented only widens `LLMClient.complete()` itself; any *future*
caller that hand-rolls its own `openai.OpenAI().chat.completions.create(...)` call
outside `LLMClient` would not get this classification for free — but that's already
disallowed by the existing "no other module may import `openai` directly" rule
(enforced for `webapp/` by `test_webapp_has_no_direct_openai_import`), so no new
gap is introduced.

## NOT done

- No change to `judge_one`/`_judge_live`'s structure (the round-1-proposed
  decoupling) — superseded by the transport-boundary design, which makes it
  unnecessary.
- No live/paid-API verification against a real Novita malformed-body response —
  the fix is validated by a fake `chat.completions.create` that raises
  `json.JSONDecodeError` (mirroring the exact stack-level failure from the incident
  report), not by reproducing the incident live. Live confirmation would require
  either waiting for a natural recurrence or a way to force Novita to return a
  malformed body on demand, neither available here.
- Did not investigate whether `openai.APIResponseValidationError` is actually the
  exception type Novita/OpenRouter malformed bodies raise in practice (vs. the bare
  `json.JSONDecodeError` observed in the incident) — added per the orchestrator's
  explicit instruction as a second transient category, not because it was observed
  live.
