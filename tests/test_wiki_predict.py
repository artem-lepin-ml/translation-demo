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


def _grounded(qid, label="label"):
    ref = WikidataRef.from_qid(qid, label, "") if qid else None
    return GroundingResult(
        difficulty="green" if qid else "red",
        grounded=ref,
        candidates=[ref] if ref else [],
        trace={"resolved_by": "exact_label" if qid else "no_candidates"},
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
