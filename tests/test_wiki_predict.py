"""Tests for the eval-owned predict bridge (E-D16): extractor -> grounding -> tuples.

The critical point: the G6 extractor emits PARAGRAPH-LOCAL char offsets;
predict_tuples stitches them into GLOBAL whole-article token indices before
pairing with the grounding QID. Tuple convention (spec Sec.3/E-D6):
(index, surface, qid, span_len).
"""
from __future__ import annotations

import pytest

from palimpsest.terminology.base import GroundingResult, TermMention, WikidataRef
from palimpsest.terminology.evaluation.predict import predict_tuples


def _mention(surface, char_start, char_end, lemma=None):
    return TermMention(
        surface=surface, context="", lemma=lemma or surface,
        char_start=char_start, char_end=char_end, lang="ru", category=None,
    )


def _grounded(qid, label="label", *, trace_candidates=None, search_source=None):
    ref = WikidataRef.from_qid(qid, label, "") if qid else None
    trace = {"resolved_by": "exact_label" if qid else "no_candidates"}
    if trace_candidates is not None:
        trace["candidates"] = trace_candidates
    if search_source is not None:
        trace["search_source"] = search_source
    return GroundingResult(
        difficulty="green" if qid else "red",
        grounded=ref,
        candidates=[ref] if ref else [],
        trace=trace,
    )


def test_global_offset_stitching_mention_in_third_paragraph():
    """Regression test: index must be GLOBAL, not paragraph-local."""
    paragraphs = [
        "Первый абзац текста здесь.",
        "Второй абзац тоже есть тут.",
        "Третий абзац содержит Рим и историю.",
    ]
    article_text = "\n".join(paragraphs)

    # "Рим" is at local offset 22 within paragraph 3 (paragraph-local char_start).
    local_start = paragraphs[2].index("Рим")
    local_end = local_start + len("Рим")

    def extract_fn(paragraph: str):
        if paragraph is paragraphs[2] or paragraph == paragraphs[2]:
            return [_mention("Рим", local_start, local_end)]
        return []

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return _grounded("Q220")

    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn)
    tuples = result["tuples"]

    assert len(tuples) == 1
    index, surface, qid, span_len = tuples[0]
    assert surface == "Рим"
    assert qid == "Q220"
    assert span_len == 1

    # The paragraph-local index would be wrong -- assert it's NOT that.
    from palimpsest.terminology.evaluation.tokenize import char_to_token_index, tokens
    local_wrong_index = char_to_token_index(paragraphs[2], local_start)
    assert index != local_wrong_index or True  # sanity guard below is the real assertion

    # Compute the true global index independently and compare.
    base_offset = len(paragraphs[0]) + 1 + len(paragraphs[1]) + 1  # two "\n" separators
    global_char = base_offset + local_start
    expected_index = char_to_token_index(article_text, global_char)
    assert index == expected_index
    # And it must land on the "Рим" token when we look it up directly.
    assert tokens(article_text)[index] == "Рим"


def test_lemma_differs_from_surface_pairs_to_grounded_qid():
    paragraphs = ["Жители Рима почитали богов."]
    article_text = paragraphs[0]
    local_start = article_text.index("Рима")
    local_end = local_start + len("Рима")

    def extract_fn(paragraph: str):
        return [_mention("Рима", local_start, local_end, lemma="Рим")]

    captured = {}

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        captured["lemma"] = mention.lemma
        captured["surface"] = mention.surface
        return _grounded("Q220")

    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn)
    tuples = result["tuples"]

    assert len(tuples) == 1
    index, surface, qid, span_len = tuples[0]
    assert surface == "Рима"
    assert qid == "Q220"
    assert captured["lemma"] == "Рим"
    assert captured["surface"] == "Рима"


def test_mention_grounded_to_none_is_skipped():
    paragraphs = ["Некий неизвестный термин здесь."]
    article_text = paragraphs[0]
    local_start = article_text.index("термин")
    local_end = local_start + len("термин")

    def extract_fn(paragraph: str):
        return [_mention("термин", local_start, local_end)]

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return _grounded(None)

    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn)

    assert result["tuples"] == []
    # The record is still emitted for auditing, but marked as not grounded.
    assert len(result["records"]) == 1
    record = result["records"][0]
    assert record["qid"] is None
    assert record["resolved_by"] == "no_candidates"


def test_record_carries_compact_candidate_list_and_search_source():
    """R_search patch (2026-07-10): the record's `candidates` field mirrors
    the grounding trace's full candidate list, compacted to {qid, label},
    plus `search_source` -- independent of whether the mention was resolved
    (qid may still be None/ambiguous while candidates were found)."""
    paragraphs = ["Царь Саргон правил Аккадом."]
    article_text = paragraphs[0]
    local_start = article_text.index("Саргон")
    local_end = local_start + len("Саргон")

    def extract_fn(paragraph: str):
        return [_mention("Саргон", local_start, local_end)]

    trace_candidates = [
        {"qid": "Q1", "label_ru": "Саргон Древний", "label_en": "Sargon of Akkad",
         "description": "", "aliases_ru": [], "aliases_en": []},
        {"qid": "Q2", "label_ru": "Саргон II", "label_en": None,
         "description": "", "aliases_ru": [], "aliases_en": []},
    ]

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return _grounded("Q1", trace_candidates=trace_candidates, search_source="wbsearchentities")

    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn)
    record = result["records"][0]

    assert record["search_source"] == "wbsearchentities"
    assert record["candidates"] == [
        {"qid": "Q1", "label": "Sargon of Akkad"},  # label_en preferred
        {"qid": "Q2", "label": "Саргон II"},  # falls back to label_ru when label_en is None
    ]


def test_record_candidate_list_empty_when_trace_has_no_candidates_key():
    """wikidata_unavailable trace shape (`{"error": ...}`, no "candidates" key
    at all) must not crash -- degrades to an empty list, not None/KeyError."""
    paragraphs = ["Некий термин здесь."]
    article_text = paragraphs[0]
    local_start = article_text.index("термин")
    local_end = local_start + len("термин")

    def extract_fn(paragraph: str):
        return [_mention("термин", local_start, local_end)]

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return GroundingResult(
            difficulty="red", grounded=None, candidates=[],
            trace={"error": "wikidata unavailable"},  # no "resolved_by"/"candidates" keys
        )

    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn)
    record = result["records"][0]

    assert record["candidates"] == []
    assert record["search_source"] is None
    assert record["resolved_by"] is None


def test_no_judge_none_still_yields_populated_candidates_via_real_grounding():
    """Integration-level guard for the --no-judge protocol: judge=None must
    not skip candidate search. Exercises the REAL LabelFirstGrounding.ground()
    (not a predict.py-level fake) end to end through predict_tuples, mirroring
    what `run --no-judge` actually wires up."""
    from palimpsest.terminology.base import GroundingConfig
    from palimpsest.terminology.grounding.label_first import LabelFirstGrounding

    class _FakeWD:
        def __init__(self):
            self.n_calls = 0

        def search_entities(self, term, lang="ru", limit=7):
            if term == "Саргон":
                return [{"id": "Q1"}, {"id": "Q2"}]
            return []

        def search_cirrus(self, term, limit=7):
            return []

        def wikipedia_wikibase_item(self, title, lang="ru"):
            return None

        def get_entities(self, qids, **kw):
            entities = {
                "Q1": {"id": "Q1", "labels": {"en": {"value": "Sargon of Akkad"}},
                       "aliases": {}, "descriptions": {}, "claims": {}, "sitelinks": {}},
                "Q2": {"id": "Q2", "labels": {"en": {"value": "Sargon II"}},
                       "aliases": {}, "descriptions": {}, "claims": {}, "sitelinks": {}},
            }
            return {q: entities[q] for q in qids if q in entities}

    paragraphs = ["Царь Саргон правил Аккадом."]
    article_text = paragraphs[0]
    local_start = article_text.index("Саргон")
    local_end = local_start + len("Саргон")

    def extract_fn(paragraph: str):
        return [_mention("Саргон", local_start, local_end)]

    grounder = LabelFirstGrounding(_FakeWD(), GroundingConfig())

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return grounder.ground(mention, judge=judge, scope_id=scope_id, judge_cache=judge_cache)

    # judge=None end to end, same as `run --no-judge`.
    result = predict_tuples(article_text, paragraphs, extract_fn, ground_fn, judge=None)
    record = result["records"][0]

    # 2 exact matches ("Саргон" surface has no exact-label match to either
    # entity's label here since labels are English -- candidates still found
    # via search, escalation with judge=None -> judge_unavailable, but the
    # free-search candidate list is populated regardless.
    assert record["resolved_by"] == "judge_unavailable"
    assert record["qid"] is None  # no judge -> unresolved, but...
    assert {c["qid"] for c in record["candidates"]} == {"Q1", "Q2"}  # ...candidates ARE there
    assert record["search_source"] == "wbsearchentities"


def test_canonicalize_remaps_predicted_qid():
    paragraphs = ["Империя простиралась широко."]
    article_text = paragraphs[0]
    local_start = article_text.index("Империя")
    local_end = local_start + len("Империя")

    def extract_fn(paragraph: str):
        return [_mention("Империя", local_start, local_end)]

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        return _grounded("Q_OLD_REDIRECT")

    def canonicalize(qid: str) -> str:
        return {"Q_OLD_REDIRECT": "Q220"}.get(qid, qid)

    result = predict_tuples(
        article_text, paragraphs, extract_fn, ground_fn, canonicalize=canonicalize,
    )
    tuples = result["tuples"]

    assert len(tuples) == 1
    _, _, qid, _ = tuples[0]
    assert qid == "Q220"


def test_predict_tuples_passes_judge_scope_id_and_cache_through():
    paragraphs = ["Термин появляется тут."]
    article_text = paragraphs[0]
    local_start = article_text.index("Термин")
    local_end = local_start + len("Термин")

    def extract_fn(paragraph: str):
        return [_mention("Термин", local_start, local_end)]

    captured = {}

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        captured["judge"] = judge
        captured["scope_id"] = scope_id
        captured["judge_cache"] = judge_cache
        return _grounded("Q1")

    sentinel_judge = object()
    sentinel_cache = {}
    predict_tuples(
        article_text, paragraphs, extract_fn, ground_fn,
        judge=sentinel_judge, scope_id="article-42", judge_cache=sentinel_cache,
    )

    assert captured["judge"] is sentinel_judge
    assert captured["scope_id"] == "article-42"
    assert captured["judge_cache"] is sentinel_cache


def test_predict_tuples_raises_on_paragraph_article_text_mismatch():
    """Precondition guard: paragraphs joined by '\\n' must equal article_text
    -- the global-offset stitching is silently wrong otherwise, so a caller
    that violates it must fail loudly rather than produce bad token indices."""
    paragraphs = ["Первый абзац.", "Второй абзац."]
    wrong_article_text = "Это совсем другой текст, не совпадающий с абзацами."

    def extract_fn(paragraph: str):
        return []

    def ground_fn(mention, *, judge=None, scope_id=None, judge_cache=None):
        raise AssertionError("should never be called -- precondition must fail first")

    with pytest.raises(ValueError):
        predict_tuples(wrong_article_text, paragraphs, extract_fn, ground_fn)
