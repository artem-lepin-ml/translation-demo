"""Eval-owned bridge from the G6 extractor to predicted GT-comparable tuples (E-D16).

The G6 extractor (``terminology/extract.py``) emits mentions with
PARAGRAPH-LOCAL char offsets -- it only ever sees one paragraph at a time.
``predict_tuples`` feeds the article paragraph-by-paragraph (the extractor's
native chunk unit), tracks a running base char offset so each mention maps to
a GLOBAL whole-article char position, converts that to a whole-article token
index via the pinned E-D6 tokenizer (``tokenize.char_to_token_index``), and
pairs it with the grounding ``chosen_qid`` to build predicted tuples in the
shared convention: ``(index, surface, qid, span_len)``.

``extract_fn``/``ground_fn`` are injected so this module is testable with
fakes and never hard-depends on a live LLM/Wikidata connection.
"""
from __future__ import annotations

from typing import Any, Callable

from ..base import GroundingResult, TermMention
from .tokenize import char_to_token_index, tokens

ExtractFn = Callable[[str], list[TermMention]]
GroundFn = Callable[..., GroundingResult]
CanonicalizeFn = Callable[[str], str]


def predict_tuples(
    article_text: str,
    paragraphs: list[str],
    extract_fn: ExtractFn,
    ground_fn: GroundFn,
    *,
    judge: Any | None = None,
    judge_cache: dict | None = None,
    scope_id: object | None = None,
    canonicalize: CanonicalizeFn | None = None,
) -> dict:
    """Extract + ground every paragraph, stitching paragraph-local offsets into
    global whole-article token indices.

    ``paragraphs`` concatenated with ``"\\n"`` (matching ``tokenize.flatten``'s
    join) must equal ``article_text`` -- that join is how the running base
    offset lines up with the global text used for token-index conversion.

    Returns ``{"tuples": [(index, surface, qid, span_len), ...], "records": [...]}``.
    ``tuples`` only carries mentions that were successfully grounded (qid is
    not None); ungrounded mentions are still present in ``records`` (with
    ``qid=None``) for auditing, but skipped from the tuple set used for
    matching against GT.

    Raises ``ValueError`` up front if ``paragraphs`` joined by ``"\\n"``
    doesn't equal ``article_text`` -- the whole global-offset stitching
    below is only correct under that invariant, so a caller that violates it
    (e.g. wrong paragraph split, stale ``article_text``) fails loud instead
    of silently producing wrong token indices.
    """
    if "\n".join(paragraphs) != article_text:
        raise ValueError(
            "predict_tuples: paragraphs joined by '\\n' must equal article_text "
            "(offset-stitching invariant, spec E-D16/Sec.9) -- got a mismatch, "
            "check the paragraph split matches tokenize.flatten's join."
        )

    tuples: list[tuple[int, str, str, int]] = []
    records: list[dict] = []

    base_offset = 0
    for paragraph in paragraphs:
        for mention in extract_fn(paragraph):
            global_char = base_offset + mention.char_start
            index = char_to_token_index(article_text, global_char)
            span_len = len(tokens(mention.surface))

            result = ground_fn(
                mention, judge=judge, scope_id=scope_id, judge_cache=judge_cache,
            )
            qid = result.grounded.qid if result.grounded else None
            resolved_by = (result.trace or {}).get("resolved_by")

            if qid is not None and canonicalize is not None:
                qid = canonicalize(qid)

            if qid is not None:
                tuples.append((index, mention.surface, qid, span_len))

            records.append({
                "index": index,
                "surface": mention.surface,
                "lemma": mention.lemma,
                "qid": qid,
                "span_len": span_len,
                "resolved_by": resolved_by,
            })

        base_offset += len(paragraph) + 1  # "\n" separator, matches tokenize.flatten's join

    return {"tuples": tuples, "records": records}
