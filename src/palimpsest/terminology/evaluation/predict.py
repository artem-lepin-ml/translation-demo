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

Each ``records`` entry (2026-07-10, R_search candidate-list patch) is
``{index, surface, lemma, category, qid, span_len, resolved_by,
search_source, candidates}`` -- ``candidates`` is the compact ``{qid,
label}`` list from the grounding trace's free Wikidata search (already
capped at ``GroundingConfig.enrich_top``), populated the same way regardless
of whether a judge was configured (search runs before any judge-escalation
decision inside ``ground_fn``), so downstream candidate-in-gold analysis
(R_search) doesn't need to replay the Wikidata cache. Each compact candidate
dict also carries ``"source"`` (``"baseline"``/``"alt"``/``"label_guess"``)
when the grounding trace's own candidate dicts have one -- i.e. whenever
``GroundingConfig.search_mode != "baseline"`` (2026-07-10, search-mode
widening patch); baseline-mode candidates never carry the key, so
``search_mode="baseline"`` stays byte-for-byte identical to the pre-patch
wire shape.

``predict_tuples_from_mentions`` (2026-07-10, ``--reuse-extraction`` patch)
is the same per-mention ground+record contract as ``predict_tuples`` but for
a caller that already has a fully-formed mention list with GLOBAL char
offsets (reconstructed from a prior run's ``pred.jsonl``, see
``scripts/wiki_eval.py``'s ``_reconstruct_mentions_for_article``) instead of
a paragraph-chunked ``extract_fn`` -- it skips the base-offset stitching
entirely since there is no extraction phase to stitch. Both functions share
the same per-mention body via ``_ground_and_record``.
"""
from __future__ import annotations

from typing import Any, Callable

from ..base import GroundingResult, TermMention
from .tokenize import char_to_token_index, tokens

ExtractFn = Callable[[str], list[TermMention]]
GroundFn = Callable[..., GroundingResult]
CanonicalizeFn = Callable[[str], str]


def _ground_and_record(
    mention: TermMention, index: int, ground_fn: GroundFn, *,
    judge: Any | None, scope_id: object | None, judge_cache: dict | None,
    canonicalize: CanonicalizeFn | None,
) -> tuple[tuple[int, str, str, int] | None, dict]:
    """Ground one mention (already assigned its whole-article token
    ``index``) and build its pred.jsonl record. Shared by ``predict_tuples``
    (paragraph-chunked extraction) and ``predict_tuples_from_mentions``
    (``--reuse-extraction``, pre-extracted mentions) so the ground+record
    contract is written exactly once."""
    result = ground_fn(mention, judge=judge, scope_id=scope_id, judge_cache=judge_cache)
    trace = result.trace or {}
    qid = result.grounded.qid if result.grounded else None
    resolved_by = trace.get("resolved_by")
    span_len = len(tokens(mention.surface))
    # Candidate list (R_search downstream analysis, 2026-07-10): the free
    # Wikidata search already runs unconditionally inside ground_fn/
    # generate_candidates BEFORE any judge escalation check (LabelFirstGrounding
    # .ground() builds `candidates` first, then decides exact_label/escalate/
    # judge=None) -- so this is populated the same way whether or not a judge
    # is configured, including under --no-judge. Already capped at
    # GroundingConfig.enrich_top by generate_candidates (the "search's own
    # limit"), so no re-capping here. Compact {qid, label[, source]} only --
    # descriptions/aliases stay in trace, not duplicated into pred.jsonl.
    # "source" (baseline/alt/label_guess, 2026-07-10 search-mode patch) is
    # passed through only when the trace candidate itself carries one --
    # baseline-mode traces never do, keeping that mode's records unchanged.
    candidates = [
        {"qid": c["qid"], "label": c.get("label_en") or c.get("label_ru") or c["qid"],
         **({"source": c["source"]} if "source" in c else {})}
        for c in (trace.get("candidates") or [])
    ]
    # search_source (cheap, already computed): which candidate-search rung
    # produced them ("wbsearchentities"/"cirrus"/"wikipedia_langlink"/"alt"/
    # "label_guess"/"none") -- the escalation-stage provenance R_search needs
    # to interpret an empty candidate list correctly (no rung fired vs. every
    # rung fired and still found nothing).
    search_source = trace.get("search_source")

    if qid is not None and canonicalize is not None:
        qid = canonicalize(qid)

    tup = (index, mention.surface, qid, span_len) if qid is not None else None
    record = {
        "index": index,
        "surface": mention.surface,
        "lemma": mention.lemma,
        "category": mention.category,
        "qid": qid,
        "span_len": span_len,
        "resolved_by": resolved_by,
        "search_source": search_source,
        "candidates": candidates,
    }
    return tup, record


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
            tup, record = _ground_and_record(
                mention, index, ground_fn, judge=judge, scope_id=scope_id,
                judge_cache=judge_cache, canonicalize=canonicalize,
            )
            if tup is not None:
                tuples.append(tup)
            records.append(record)

        base_offset += len(paragraph) + 1  # "\n" separator, matches tokenize.flatten's join

    return {"tuples": tuples, "records": records}


def predict_tuples_from_mentions(
    mentions_with_index: list[tuple[TermMention, int]],
    ground_fn: GroundFn,
    *,
    judge: Any | None = None,
    judge_cache: dict | None = None,
    scope_id: object | None = None,
    canonicalize: CanonicalizeFn | None = None,
) -> dict:
    """Ground a pre-extracted mention list directly (``--reuse-extraction``,
    scripts/wiki_eval.py Deliverable 2): each ``(mention, index)`` pair
    already carries its whole-article token ``index`` (reconstructed by the
    caller from a prior run's ``pred.jsonl``, see
    ``scripts/wiki_eval.py``'s ``_reconstruct_mentions_for_article``), so
    unlike ``predict_tuples`` there is no paragraph-chunked ``extract_fn`` to
    call and no base-offset stitching to do -- unmodified reuse of every
    other choice ``predict_tuples`` makes (grounding, candidate/search_source
    passthrough, tuple/record shape), via the shared ``_ground_and_record``.

    Returns the same ``{"tuples": [...], "records": [...]}`` shape as
    ``predict_tuples``.
    """
    tuples: list[tuple[int, str, str, int]] = []
    records: list[dict] = []

    for mention, index in mentions_with_index:
        tup, record = _ground_and_record(
            mention, index, ground_fn, judge=judge, scope_id=scope_id,
            judge_cache=judge_cache, canonicalize=canonicalize,
        )
        if tup is not None:
            tuples.append(tup)
        records.append(record)

    return {"tuples": tuples, "records": records}
