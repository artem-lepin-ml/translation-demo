"""G6 -- label_first grounding: deterministic exact-label match, judge only on
genuine ambiguity (spec 2026-07-03-grounding-label-first-design.md sec 3.2).

Decision table:
  exactly 1 exact-label match      -> green, resolved_by=exact_label, no judge call
  >=2 exact matches                -> judge -> yellow/llm_disambiguation
  candidates present, 0 exact      -> judge -> yellow/llm_disambiguation or red/judge_rejected
  0 candidates after fallbacks     -> red, resolved_by=no_candidates, no judge call

Post-rejection escalation (2026-07-17, search_mode="label-guess" only): when
the judge rejects EVERY candidate and the guess tier hasn't already run, one
extra guesser+judge round runs over the newly guessed candidates only (see
``_guess_escalation_after_rejection``); success is yellow/llm_disambiguation,
anything else keeps the honest rejection.

Error policy: candidate-gen failure (``RuntimeError`` -- e.g. Wikidata retries
exhausted -- or a bare non-retryable ``urllib.error.HTTPError``/``OSError``
that escaped the client's own retry loop) -> red/wikidata_unavailable (not
no_candidates -- a network failure must not masquerade as an honest miss).
judge=None, judge raising, or malformed judge output (missing/invalid ``qid``
key) on escalation all collapse to yellow/judge_unavailable -- terminal, no
retry (retries are the caller's job, see webapp's ``_judge_live``). A QID
outside the candidate set is a contract violation, not a top-1 fallback (the
old G3 anti-pattern) -- also yellow/judge_unavailable. EXCEPTION:
``FatalGroundingJudgeError`` (halt markers such as token-limit overflow or
per-call gate violations) is re-raised out of ``ground()`` instead of
collapsing to judge_unavailable -- it must stop the run, not be tolerated
(wiki-eval experiment v2, spec 2026-07-10 Р15).
"""
from __future__ import annotations

import time
import urllib.error

from ..base import (
    FatalGroundingJudgeError,
    GroundingConfig,
    GroundingResult,
    Judge,
    TermMention,
    WikidataRef,
)
from ..wikidata import WikidataClient
from .candidates import escalate_label_guess, generate_candidates
from .match import exact_match, norm

DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT = """## Role
You are a Wikidata disambiguation judge for a Russian-to-English historical
translation pipeline. Given a Russian term, its lemma, the sentence it
occurs in, and a numbered list of Wikidata candidates, decide which
candidate (if any) the term refers to.

## Context notes
The sentence context can name two different timeframes at once: the
historical period being narrated (an artifact's date, an ancient event,
etc.) and a modern-day fact stated about it (where the artifact is held
today, a caption, a citation). For example "Конец XXIII в. до н.э. Париж,
Лувр" dates an artifact to the 23rd century BC while naming its present-day
location -- the modern city of Paris and the Louvre museum -- not implying
the referent itself must date to that period. Judge each candidate on
whether it IS the entity the term names. An enduring real-world referent
(a city, country, museum, or other institution that still exists today) is
a genuinely correct answer even in a passage about an earlier era -- do not
reject it merely because the surrounding narrative describes an older
period. Reject a candidate only when its identity does not match what the
term refers to, never because of an unrelated era mismatch in the context.

## Output
Return strict JSON only, no other text:
{"qid": "Q..." or null, "reason": "<one sentence>"}

Use null when no candidate genuinely fits the context.
"""

DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE = """Surface form: {surface}
Lemma: {lemma}
Sentence context: {context}

Candidates:
{candidates}
"""

# Combined system+user string, kept ONLY because the webapp DB stores a single
# prompt-template string per config row (migrate.py/seed.py seed
# grounding_config.prompt from this) -- regenerating that demo seed to split
# system/user in the DB is explicitly out of scope here (spec 2026-07-10 §9).
# Live judge calls use the two constants above directly, not this string.
DEFAULT_GROUNDING_JUDGE_PROMPT = DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT + "\n\n" + DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE


def _format_judge_prompt(mention: TermMention, candidates: list[dict]) -> str:
    options = "\n".join(
        f"{i}. {c['qid']}: {c.get('label_ru') or c.get('label_en') or c['qid']} — {c.get('description', '')}"
        for i, c in enumerate(candidates, 1)
    )
    return DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE.format(
        surface=mention.surface,
        lemma=mention.lemma or mention.surface,
        context=mention.context,
        candidates=options,
    )


class LabelFirstGrounding:
    name = "label_first"

    def __init__(self, client: WikidataClient, config: GroundingConfig | None = None, *,
                 label_guesser: Judge | None = None) -> None:
        self.wd = client
        self.config = config or GroundingConfig()
        # Only consulted by generate_candidates when config.search_mode ==
        # "label-guess" (wiki-eval experiment, 2026-07-10) -- a DIFFERENT
        # callable than the disambiguation ``judge`` passed per-call to
        # ground() below, since it needs its own system prompt
        # (candidates.DEFAULT_LABEL_GUESS_SYSTEM_PROMPT), even though both
        # are typically built from the same run's judge-configured LLM route
        # (see scripts/wiki_eval.py's _build_label_guesser).
        self.label_guesser = label_guesser

    def ground(
        self,
        mention: TermMention,
        *,
        judge: Judge | None = None,
        scope_id: object | None = None,
        judge_cache: dict | None = None,
    ) -> GroundingResult:
        t0 = time.perf_counter()
        calls0 = self.wd.n_calls
        config = self.config

        try:
            gen = generate_candidates(self.wd, mention, config, label_guesser=self.label_guesser)
        except (RuntimeError, urllib.error.HTTPError, OSError) as exc:
            # RuntimeError: WikidataClient retries exhausted (see wikidata.py::_fetch).
            # urllib.error.HTTPError: a non-retryable 4xx (or a retryable one whose
            # retries were exhausted) that the client re-raises bare -- retryable
            # errors are still retried inside the client before ever reaching here.
            # OSError: defense-in-depth for any other transport-level failure that
            # isn't already normalized to one of the two above.
            return self._result(
                "red", None, [], t0, calls0,
                queries=[], search_source=None, candidates=[], exact_matches=[],
                resolved_by="wikidata_unavailable", judge_trace={"error": str(exc)}, chosen_qid=None, canon_en=[],
            )

        candidates = gen["candidates"]
        queries = gen["queries"]
        search_source = gen["source"]
        canon_by_qid = gen["canon_by_qid"]

        if not candidates:
            return self._result(
                "red", None, [], t0, calls0,
                queries=queries, search_source=search_source, candidates=[], exact_matches=[],
                resolved_by="no_candidates", judge_trace=None, chosen_qid=None, canon_en=[],
            )

        query_terms = [q for q in (mention.lemma, mention.surface) if q]
        exact_matches = exact_match(query_terms, candidates, match_aliases=config.match_aliases)

        candidates_traced = [
            {**c, "matched": next((m["matched"] for m in exact_matches if m["qid"] == c["qid"]), None)}
            for c in candidates
        ]

        if len(exact_matches) == 1:
            chosen = exact_matches[0]
            ref = WikidataRef.from_qid(chosen["qid"], chosen.get("label_en") or chosen.get("label_ru") or chosen["qid"],
                                        chosen.get("description", ""))
            refs = [WikidataRef.from_qid(c["qid"], c.get("label_en") or c.get("label_ru") or c["qid"],
                                          c.get("description", "")) for c in candidates]
            return self._result(
                "green", ref, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="exact_label", judge_trace=None, chosen_qid=chosen["qid"],
                canon_en=canon_by_qid.get(chosen["qid"], []),
            )

        # >=2 exact matches, or candidates present with 0 exact matches: escalate.
        refs = [WikidataRef.from_qid(c["qid"], c.get("label_en") or c.get("label_ru") or c["qid"],
                                      c.get("description", "")) for c in candidates]

        # "One sense per discourse" cache (spec §4): model name and prompt-template
        # hash are deliberately omitted from the key -- within a single run the
        # judge model and DEFAULT_GROUNDING_JUDGE_PROMPT are constant, so they
        # can't vary the decision, and adding them now would be a speculative
        # abstraction (repo convention) with no caller needing multi-model
        # caching yet. Last-write-wins on upsert is fine because grounding is
        # sequential (spec §4 concurrency note).
        cache_key = None
        if scope_id is not None and judge_cache is not None:
            cache_key = (
                scope_id,
                norm(mention.lemma or mention.surface),
                tuple(sorted(c["qid"] for c in candidates)),
            )
            if cache_key in judge_cache:
                cached = judge_cache[cache_key]
                return self._from_cached_decision(
                    cached, refs, t0, calls0, queries=queries, search_source=search_source,
                    candidates=candidates_traced, exact_matches=exact_matches, canon_by_qid=canon_by_qid,
                )

        if judge is None:
            decision = {"resolved_by": "judge_unavailable", "chosen_qid": None,
                        "judge_trace": {"error": "judge not configured"}}
            if cache_key is not None:
                judge_cache[cache_key] = decision
            return self._result(
                "yellow", None, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="judge_unavailable",
                judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=None, canon_en=[],
            )

        prompt = _format_judge_prompt(mention, candidates)
        j0 = time.perf_counter()
        try:
            response = judge(prompt)
        except FatalGroundingJudgeError:
            # A halt marker (token-limit overflow, per-call gate violations) must
            # propagate out of ground() and stop the run -- it is NOT a tolerable
            # degradation to judge_unavailable (wiki-eval experiment v2, Р15).
            raise
        except Exception as exc:  # noqa: BLE001 -- any other judge failure is terminal here, not retried
            decision = {"resolved_by": "judge_unavailable", "chosen_qid": None,
                        "judge_trace": {"error": str(exc),
                                        "latency_ms": round((time.perf_counter() - j0) * 1000, 1)}}
            if cache_key is not None:
                judge_cache[cache_key] = decision
            return self._result(
                "yellow", None, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="judge_unavailable",
                judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=None, canon_en=[],
            )

        if not isinstance(response, dict) or "qid" not in response:
            decision = {"resolved_by": "judge_unavailable", "chosen_qid": None,
                        "judge_trace": {"error": "malformed judge response", "response": response,
                                        "latency_ms": round((time.perf_counter() - j0) * 1000, 1)}}
            if cache_key is not None:
                judge_cache[cache_key] = decision
            return self._result(
                "yellow", None, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="judge_unavailable",
                judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=None, canon_en=[],
            )

        judge_latency = round((time.perf_counter() - j0) * 1000, 1)
        qid = response["qid"]

        if qid is None:
            # Post-rejection label-guess escalation (2026-07-17): the pre-judge
            # guess tier only fires on ZERO hits, but "7 hits, all the wrong
            # entity" (prod: «Хана» -> given name / Hawaii CDP / football club,
            # never the Bronze-age kingdom) is invisible to that gate -- only
            # the judge's rejection reveals it. One extra guesser + judge round
            # over the NEW candidates only; any failure keeps the honest
            # rejection. Skipped when the guess tier already ran pre-judge
            # (nothing new to try).
            if (config.search_mode == "label-guess" and self.label_guesser is not None
                    and not any(q.get("kind") == "label_guess" for q in queries)):
                escalated = self._guess_escalation_after_rejection(
                    mention, judge, response,
                    candidates_traced=candidates_traced, queries=queries,
                    search_source=search_source, exact_matches=exact_matches,
                    t0=t0, calls0=calls0,
                )
                if escalated is not None:
                    # Deliberately NOT written to judge_cache: the chosen ref
                    # lies outside this mention's generated candidate set, so
                    # _from_cached_decision could not replay it -- a duplicate
                    # mention repeats one guesser + one judge call instead
                    # (bounded; scope_id is per-paragraph in the demo anyway).
                    return escalated
            decision = {"resolved_by": "judge_rejected", "chosen_qid": None,
                        "judge_trace": {"response": response, "error": None, "latency_ms": judge_latency}}
            if cache_key is not None:
                judge_cache[cache_key] = decision
            return self._result(
                "red", None, [], t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="judge_rejected",
                judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=None, canon_en=[],
            )

        chosen_ref = next((r for r in refs if r.qid == qid), None)
        if chosen_ref is None:
            decision = {"resolved_by": "judge_unavailable", "chosen_qid": None,
                        "judge_trace": {"error": f"qid {qid!r} not in candidate set", "response": response,
                                        "latency_ms": judge_latency}}
            if cache_key is not None:
                judge_cache[cache_key] = decision
            return self._result(
                "yellow", None, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates_traced,
                exact_matches=exact_matches, resolved_by="judge_unavailable",
                judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=None, canon_en=[],
            )

        decision = {"resolved_by": "llm_disambiguation", "chosen_qid": qid,
                    "judge_trace": {"response": response, "error": None, "latency_ms": judge_latency}}
        if cache_key is not None:
            judge_cache[cache_key] = decision
        return self._result(
            "yellow", chosen_ref, refs, t0, calls0,
            queries=queries, search_source=search_source, candidates=candidates_traced,
            exact_matches=exact_matches, resolved_by="llm_disambiguation",
            judge_trace={**decision["judge_trace"], "cache_hit": False}, chosen_qid=qid,
            canon_en=canon_by_qid.get(qid, []),
        )

    def _guess_escalation_after_rejection(
        self, mention: TermMention, judge: Judge, first_response: dict, *,
        candidates_traced: list[dict], queries: list[dict], search_source,
        exact_matches: list[dict], t0: float, calls0: int,
    ) -> GroundingResult | None:
        """One label-guess round after the judge rejected every candidate.

        Returns a yellow/llm_disambiguation result when the second judge call
        picks one of the NEW candidates; ``None`` in every other case -- the
        caller then returns the original honest rejection. New candidates are
        judged only, never exact-label matched: a fresh exact match inside a
        homonym set the judge just vetoed must not auto-green (false-green is
        the worst error class). ``queries`` is extended in place so the guess
        attempt stays visible in the trace even when the rejection stands.
        """
        try:
            esc = escalate_label_guess(
                self.wd, mention, self.config, self.label_guesser,
                exclude_qids={c["qid"] for c in candidates_traced})
        except FatalGroundingJudgeError:
            raise
        except (RuntimeError, urllib.error.HTTPError, OSError):
            return None  # transport failure mid-escalation: the rejection stands
        queries.extend(esc["queries"])
        new_cands = esc["candidates"]
        if not new_cands:
            return None
        prompt = _format_judge_prompt(mention, new_cands)
        j0 = time.perf_counter()
        try:
            response = judge(prompt)
        except FatalGroundingJudgeError:
            raise
        except Exception:  # noqa: BLE001 -- the first judge DID answer; its rejection stands
            return None
        judge_latency = round((time.perf_counter() - j0) * 1000, 1)
        qid = response.get("qid") if isinstance(response, dict) else None
        if not qid:
            return None  # rejected again (or malformed): keep the original rejection
        chosen = next((c for c in new_cands if c["qid"] == qid), None)
        if chosen is None:
            return None  # contract violation on the escalation round only
        all_candidates = candidates_traced + [{**c, "matched": None} for c in new_cands]
        refs = [WikidataRef.from_qid(c["qid"], c.get("label_en") or c.get("label_ru") or c["qid"],
                                      c.get("description", "")) for c in all_candidates]
        chosen_ref = next(r for r in refs if r.qid == qid)
        judge_trace = {"response": response, "error": None, "latency_ms": judge_latency,
                       "cache_hit": False, "first_rejection": first_response}
        return self._result(
            "yellow", chosen_ref, refs, t0, calls0,
            queries=queries, search_source=search_source, candidates=all_candidates,
            exact_matches=exact_matches, resolved_by="llm_disambiguation",
            judge_trace=judge_trace, chosen_qid=qid,
            canon_en=esc["canon_by_qid"].get(qid, []),
        )

    def _from_cached_decision(self, decision, refs, t0, calls0, *, queries, search_source,
                               candidates, exact_matches, canon_by_qid) -> GroundingResult:
        """Rebuild a GroundingResult from a cached judge decision (cache hit path).

        Classifies difficulty/grounded exactly as the fresh path would for the
        same resolved_by value.
        """
        resolved_by = decision["resolved_by"]
        chosen_qid = decision["chosen_qid"]
        judge_trace = {**decision["judge_trace"], "cache_hit": True}

        if resolved_by == "llm_disambiguation":
            chosen_ref = next((r for r in refs if r.qid == chosen_qid), None)
            return self._result(
                "yellow", chosen_ref, refs, t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates,
                exact_matches=exact_matches, resolved_by=resolved_by,
                judge_trace=judge_trace, chosen_qid=chosen_qid,
                canon_en=canon_by_qid.get(chosen_qid, []),
            )
        if resolved_by == "judge_rejected":
            return self._result(
                "red", None, [], t0, calls0,
                queries=queries, search_source=search_source, candidates=candidates,
                exact_matches=exact_matches, resolved_by=resolved_by,
                judge_trace=judge_trace, chosen_qid=None, canon_en=[],
            )
        # judge_unavailable
        return self._result(
            "yellow", None, refs, t0, calls0,
            queries=queries, search_source=search_source, candidates=candidates,
            exact_matches=exact_matches, resolved_by=resolved_by,
            judge_trace=judge_trace, chosen_qid=None, canon_en=[],
        )

    def _result(self, difficulty, grounded, refs, t0, calls0, *, queries, search_source, candidates,
                exact_matches, resolved_by, judge_trace, chosen_qid, canon_en) -> GroundingResult:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        n_api_calls = self.wd.n_calls - calls0
        trace = {
            "v": 1,
            # use_cirrus/use_sitelink (split from the deprecated use_fallbacks
            # 2026-07-06, see GroundingConfig's docstring in base.py) -- no
            # trace consumer (frontend GlossaryTab/glossary-grouping, the demo
            # contracts spec) reads trace.config, so this is a straight rename,
            # not a compat shim.
            "config": {"use_lemma": self.config.use_lemma, "use_cirrus": self.config.use_cirrus,
                       "use_sitelink": self.config.use_sitelink, "match_aliases": self.config.match_aliases},
            "queries": queries,
            "search_source": search_source,
            "candidates": candidates,
            "exact_matches": exact_matches,
            "resolved_by": resolved_by,
            "judge": judge_trace,
            "chosen_qid": chosen_qid,
            "canon_en": canon_en,
            "n_api_calls": n_api_calls,
            "latency_ms": latency_ms,
        }
        return GroundingResult(
            difficulty=difficulty,
            grounded=grounded,
            candidates=refs,
            latency_ms=latency_ms,
            n_api_calls=n_api_calls,
            trace=trace,
        )
