"""G6 -- label_first grounding: deterministic exact-label match, judge only on
genuine ambiguity (spec 2026-07-03-grounding-label-first-design.md sec 3.2).

Decision table:
  exactly 1 exact-label match      -> green, resolved_by=exact_label, no judge call
  >=2 exact matches                -> judge -> yellow/llm_disambiguation
  candidates present, 0 exact      -> judge -> yellow/llm_disambiguation or red/judge_rejected
  0 candidates after fallbacks     -> red, resolved_by=no_candidates, no judge call

Error policy: candidate-gen RuntimeError -> red/wikidata_unavailable (not
no_candidates -- a network failure must not masquerade as an honest miss).
judge=None, judge raising, or malformed judge output (missing/invalid ``qid``
key) on escalation all collapse to yellow/judge_unavailable -- terminal, no
retry (retries are the caller's job, see webapp's ``_judge_live``). A QID
outside the candidate set is a contract violation, not a top-1 fallback (the
old G3 anti-pattern) -- also yellow/judge_unavailable.
"""
from __future__ import annotations

import time

from ..base import GroundingConfig, GroundingResult, Judge, TermMention, WikidataRef
from ..wikidata import WikidataClient
from .candidates import generate_candidates
from .match import exact_match, norm

DEFAULT_GROUNDING_JUDGE_PROMPT = """## Role
You are a Wikidata disambiguation judge for a Russian-to-English historical
translation pipeline. Given a Russian term, its lemma, the sentence it occurs
in, and a numbered list of Wikidata candidates, decide which candidate (if
any) the term refers to.

## Input
Surface form: {surface}
Lemma: {lemma}
Sentence context: {context}

Candidates:
{candidates}

## Output
Return strict JSON only, no other text:
{{"qid": "Q..." or null, "reason": "<one sentence>"}}

Use null when no candidate genuinely fits the context.
"""


def _format_judge_prompt(mention: TermMention, candidates: list[dict]) -> str:
    options = "\n".join(
        f"{i}. {c['qid']}: {c.get('label_ru') or c.get('label_en') or c['qid']} — {c.get('description', '')}"
        for i, c in enumerate(candidates, 1)
    )
    return DEFAULT_GROUNDING_JUDGE_PROMPT.format(
        surface=mention.surface,
        lemma=mention.lemma or mention.surface,
        context=mention.context,
        candidates=options,
    )


class LabelFirstGrounding:
    name = "label_first"

    def __init__(self, client: WikidataClient, config: GroundingConfig | None = None) -> None:
        self.wd = client
        self.config = config or GroundingConfig()

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
            gen = generate_candidates(self.wd, mention, config)
        except RuntimeError as exc:
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
        except Exception as exc:  # noqa: BLE001 -- any judge failure is terminal here, not retried
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
            "config": {"use_lemma": self.config.use_lemma, "use_fallbacks": self.config.use_fallbacks,
                       "match_aliases": self.config.match_aliases},
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
