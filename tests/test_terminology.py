"""Unit tests for the terminology module: verdict logic, extraction, pipeline null rule."""
from __future__ import annotations

import json
import logging
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import pipeline
from palimpsest.terminology.base import FatalGroundingJudgeError, GroundingResult, PairResult, TermMention, WikidataRef
from palimpsest.terminology.eval_harness import wilson_ci
from palimpsest.terminology.extract import deterministic_extract, mentions_from_surfaces
from palimpsest.terminology.verdict import pair_from_forms
from palimpsest.terminology.wikidata import canonical_en_forms


# NOTE(Task 12): G6 label_first decision-table, toggle-matrix, and error-policy
# tests go here (norm/exact_match, trace v1 completeness, resolved_by paths).


# ── pairing verdict ───────────────────────────────────────────────────────────
def test_pair_green_exact():
    ts, pa, rec = pair_from_forms(["Mesopotamia"], "the region of Mesopotamia flourished")
    assert pa == "green" and ts == "Mesopotamia" and rec is None


def test_pair_short_form_person():
    ts, pa, rec = pair_from_forms(["Sargon of Akkad", "Sargon"], "then king Sargon founded")
    assert pa == "green" and ts == "Sargon"


def test_pair_red_when_absent_gives_recommended():
    ts, pa, rec = pair_from_forms(["Lugal"], "the governor of the city")
    assert pa == "red" and ts is None and rec == "Lugal"


def test_pair_head_guard_rejects_shared_tail():
    # "town of Akkad" must NOT fuzzy-match "Sargon of Akkad" on the shared tail
    ts, pa, _ = pair_from_forms(["Sargon of Akkad"], "the town of Akkad stood on the river")
    assert pa == "red"


def test_pair_empty_target_is_red():
    ts, pa, rec = pair_from_forms(["Athens"], "")
    assert pa == "red" and ts is None


# ── canonical forms ───────────────────────────────────────────────────────────
def test_canonical_forms_drop_non_latin_add_short():
    entity = {
        "labels": {"en": {"value": "Sargon of Akkad"}},
        "aliases": {"en": [{"value": "𒈗𒁺"}, {"value": "Sargon I, King of Agade"}]},
        "sitelinks": {"enwiki": {"title": "Sargon of Akkad"}},
    }
    forms = canonical_en_forms(entity)
    assert "𒈗𒁺" not in forms          # cuneiform dropped
    assert "Sargon" in forms            # short form derived


def test_canonical_short_form_skips_common_head():
    entity = {"labels": {"en": {"value": "Kingdom of Sumer and Akkad"}}, "aliases": {}, "sitelinks": {}}
    forms = canonical_en_forms(entity)
    assert "Kingdom" not in forms       # common noun never becomes a standalone form


# ── extraction ────────────────────────────────────────────────────────────────
def test_mentions_per_occurrence_and_spans():
    source = "Саргон правил. Позже Саргон умер."
    ms = mentions_from_surfaces(source, [{"surface": "Саргон"}])
    assert len(ms) == 2                                    # one row per occurrence
    assert all(source[m.char_start:m.char_end] == "Саргон" for m in ms)
    assert ms[0].char_start < ms[1].char_start


def test_mentions_longest_claims_span_first():
    source = "Законы Хаммурапи были суровы."
    ms = mentions_from_surfaces(source, [{"surface": "Хаммурапи"}, {"surface": "Законы Хаммурапи"}])
    surfaces = {m.surface for m in ms}
    assert "Законы Хаммурапи" in surfaces                  # multi-word wins the overlap


def test_deterministic_extract_finds_proper_nouns():
    # E0 is a coarse fallback: it may over-capture a leading capitalised word
    # ("Царь Кадашман-Харбе"). The precise extractor is the E1 subagent.
    ms = deterministic_extract("Царь Кадашман-Харбе воевал с Вавилоном.")
    assert any("Кадашман-Харбе" in m.surface for m in ms)
    assert any("Вавилон" in m.surface for m in ms)


def test_ner_system_prompt_covers_full_category_scope():
    from palimpsest.terminology.extract import NER_CATEGORIES, NER_SYSTEM_PROMPT
    assert "<categories>" in NER_SYSTEM_PROMPT
    assert "What to extract (examples)" in NER_SYSTEM_PROMPT
    for cat in ("deity", "work", "religion"):
        assert cat in NER_SYSTEM_PROMPT
    for cat in NER_CATEGORIES:                    # every canonical token is named in the prompt
        assert cat in NER_SYSTEM_PROMPT


def test_ner_system_prompt_requires_category_and_is_frozen():
    from palimpsest.terminology.extract import NER_SYSTEM_PROMPT
    assert "{surface, lemma, category}" in NER_SYSTEM_PROMPT
    assert "category NEVER changes" in NER_SYSTEM_PROMPT     # category never affects extraction decisions
    src = Path(__file__).resolve().parents[1] / "src/palimpsest/terminology/extract.py"
    text = src.read_text(encoding="utf-8")
    assert "FROZEN 2026-07-10" in text                       # freeze marker above NER_SYSTEM_PROMPT
    assert "Do not modify without an owner-approved spec" in text


def test_ner_user_wraps_source():
    from palimpsest.terminology.extract import ner_user
    assert ner_user("В Лагаше правил лугаль.") == "<source>\nВ Лагаше правил лугаль.\n</source>"


def test_parse_surfaces_tolerates_fence():
    from palimpsest.terminology.extract import parse_surfaces
    raw = '```json\n[{"surface":"Лагаше","lemma":"Лагаш"},{"surface":"x","lemma":"x"}]\n```'
    out = parse_surfaces(raw)
    assert out == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "other"},
                    {"surface": "x", "lemma": "x", "category": "other"}]  # missing category -> "other"


def test_parse_surfaces_ignores_trailing_commentary_with_brackets():
    from palimpsest.terminology.extract import parse_surfaces
    raw = ('[{"surface":"Лагаше","lemma":"Лагаш"}]\n'
           'Note: this also mentions [Вавилон] as a location.')
    out = parse_surfaces(raw)
    assert out == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "other"}]


def test_parse_surfaces_includes_lemma():
    from palimpsest.terminology.extract import parse_surfaces
    raw = '[{"surface":"династии Цин","lemma":"династия Цин"}]'
    out = parse_surfaces(raw)
    assert out == [{"surface": "династии Цин", "lemma": "династия Цин", "category": "other"}]


def test_parse_surfaces_valid_category_passes():
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([{"surface": "Лагаше", "lemma": "Лагаш", "category": "place"}], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert out == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "place"}]
    assert "category_raw" not in out[0]           # known token -> nothing to preserve


def test_parse_surfaces_unknown_category_normalizes_with_raw_preserved():
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([{"surface": "Лагаше", "lemma": "Лагаш", "category": "monument"}], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert out == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "other", "category_raw": "monument"}]


def test_parse_surfaces_missing_category_normalizes_to_other_no_raw():
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([{"surface": "Лагаше", "lemma": "Лагаш"}], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert out == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "other"}]
    assert "category_raw" not in out[0]           # nothing was emitted, nothing to preserve

    raw_empty = json.dumps([{"surface": "Лагаше", "lemma": "Лагаш", "category": ""}], ensure_ascii=False)
    out_empty = parse_surfaces(raw_empty)
    assert out_empty == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "other"}]
    assert "category_raw" not in out_empty[0]


def test_parse_surfaces_never_rejects_over_category_value():
    # an otherwise-valid extraction is never dropped/raised over a bad category value
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([{"surface": "Лагаше", "lemma": "Лагаш", "category": 42}], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert out[0]["surface"] == "Лагаше" and out[0]["category"] == "other"


def test_parse_surfaces_lemma_sanity_falls_back_to_surface():
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([
        {"surface": "Лагаше", "lemma": ""},
        {"surface": "Вавилон", "lemma": "x" * 81},
        {"surface": "Ниппур", "lemma": "Ниппур\nс переносом"},
    ], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert [o["lemma"] for o in out] == ["Лагаше", "Вавилон", "Ниппур"]  # sanity fails -> lemma=surface


def test_parse_surfaces_empty_array_is_honest_not_a_failure():
    from palimpsest.terminology.extract import parse_surfaces
    assert parse_surfaces("[]") == []
    assert parse_surfaces("```json\n[]\n```") == []


def test_parse_surfaces_raises_on_not_json():
    from palimpsest.terminology.extract import ExtractionParseError, parse_surfaces
    with pytest.raises(ExtractionParseError):
        parse_surfaces("not json")


def test_parse_surfaces_raises_on_single_json_object():
    from palimpsest.terminology.extract import ExtractionParseError, parse_surfaces
    with pytest.raises(ExtractionParseError):
        parse_surfaces('{"surface":"Лагаше","lemma":"Лагаш"}')


def test_parse_surfaces_raises_on_truncated_array():
    from palimpsest.terminology.extract import ExtractionParseError, parse_surfaces
    with pytest.raises(ExtractionParseError):
        parse_surfaces('[{"surface":"Лагаше","lemma":"Лагаш"}')


def test_validate_surfaces_drops_not_in_source_and_dedups():
    from palimpsest.terminology.extract import validate_surfaces
    src = "В Лагаше правил лугаль. Лагаше славился."
    surfaces = [{"surface": "Лагаше", "lemma": "Лагаш"}, {"surface": "Лагаше", "lemma": "Лагаш"},
                {"surface": "Lagash", "lemma": "Lagash"}, {"surface": "", "lemma": None}]
    valid, dropped = validate_surfaces(src, surfaces)
    assert [v["surface"] for v in valid] == ["Лагаше"]   # deduped, only substring
    assert valid == [{"surface": "Лагаше", "lemma": "Лагаш"}]  # no category key in input -> none added
    assert dropped == 1                                   # "Lagash" not in source


def test_validate_surfaces_passes_category_through_untouched():
    # validate_surfaces re-validates only substring/dedup -- it never touches category itself
    from palimpsest.terminology.extract import validate_surfaces
    src = "В Лагаше правил лугаль."
    surfaces = [{"surface": "Лагаше", "lemma": "Лагаш", "category": "place"},
                {"surface": "лугаль", "lemma": "лугаль", "category": "other", "category_raw": "monument"}]
    valid, dropped = validate_surfaces(src, surfaces)
    assert valid == [{"surface": "Лагаше", "lemma": "Лагаш", "category": "place"},
                      {"surface": "лугаль", "lemma": "лугаль", "category": "other",
                       "category_raw": "monument"}]
    assert dropped == 0


def test_gazetteer_matches_lowercase_forms_word_boundary():
    from palimpsest.terminology.gazetteer import gazetteer_surfaces
    src = "правитель-лугаль опирался на авилумов, а молодцы пировали"
    got = {s["surface"] for s in gazetteer_surfaces(src)}
    assert "лугаль" in got and "авилумов" in got
    assert "молодцы" not in got                 # suffix -цы guarded by stoplist/min-stem


def test_gazetteer_suffix_ethnonym_with_guard():
    from palimpsest.terminology.gazetteer import gazetteer_surfaces
    src = "на границе стояли иллирийцы, но бойцы бежали"
    got = {s["surface"] for s in gazetteer_surfaces(src)}
    assert "иллирийцы" in got                    # ethnonym via lexicon or suffix
    assert "бойцы" not in got                    # guarded


def test_gazetteer_does_not_truncate_capitalized_words():
    # regression: the suffix scan must not match inside a capitalised word and emit a
    # truncated surface ("Афиняне" -> "финяне"). Capitalised runs are the caps extractor's job.
    from palimpsest.terminology.gazetteer import gazetteer_surfaces
    src = "Афиняне победили в войне. Позже иллирийцы напали с севера."
    got = {s["surface"] for s in gazetteer_surfaces(src)}
    assert "финяне" not in got                    # no mid-word truncation of "Афиняне"
    assert "иллирийцы" in got                     # lowercase ethnonym still caught


def test_deterministic_surfaces_finds_lowercase_via_gazetteer():
    from palimpsest.terminology.extract import deterministic_surfaces
    surfs = {s["surface"] for s in deterministic_surfaces("В Лагаше правил лугаль над авилумами.")}
    assert "Лагаше" in surfs and "лугаль" in surfs and "авилумами" in surfs


def test_llm_surfaces_none_degrades_to_deterministic():
    from palimpsest.terminology.extract import llm_surfaces, deterministic_surfaces
    src = "В Лагаше правил лугаль."
    assert llm_surfaces(src, extractor=None) == deterministic_surfaces(src)


def test_llm_surfaces_validates_against_source():
    from palimpsest.terminology.extract import llm_surfaces
    src = "В Лагаше правил лугаль."
    fake = lambda s: [{"surface":"лугаль","category":"title"},{"surface":"Lagash","category":"place"}]
    out = llm_surfaces(src, extractor=fake)
    got = {v["surface"] for v in out}
    assert got == {"лугаль"}                     # hallucinated "Lagash" dropped
    assert out[0]["category"] == "title"          # category survives the validate_surfaces roundtrip


def test_extract_key_is_stable_and_canonical():
    from palimpsest.terminology.extract import extract_key
    a = extract_key("src", {"modelName":"m","prompt":"p","params":{"b":1,"a":2}})
    b = extract_key("src", {"modelName":"m","prompt":"p","params":{"a":2,"b":1}})
    assert a == b and len(a) == 64               # sha256 hex, key-order independent


def test_extract_paragraph_terms_builds_terms_and_holds_null_rule():
    from palimpsest.terminology.extract import extract_paragraph_terms
    cfg = {"modelName":"m","prompt":"p","params":{}}
    fake = lambda s: [{"surface":"GOODterm","category":"people"},{"surface":"REDterm","category":"people"}]
    terms = extract_paragraph_terms("GOODterm and REDterm", "X here", cfg,
                                    grounder=_Grounder(), pairer=_Pairer(), extractor=fake)
    red = next(t for t in terms if t.source_surface == "REDterm")
    assert red.difficulty == "red" and red.grounded is None and red.candidates == []


def test_terminology_module_has_no_openai_import():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/palimpsest/terminology"
    # SC4: no direct openai SDK usage and no import of the project's LLMClient wrapper.
    # Local sibling modules named *llm* (e.g. `.llm_judge`, a subagent-judge strategy)
    # are fine — the guard is about the openai/LLMClient dependency, not the word "llm".
    pattern = re.compile(r"^\s*(import openai\b|from openai\b|from .*\bimport\b.*\bLLMClient\b)", re.M)
    for p in root.rglob("*.py"):
        assert not pattern.search(p.read_text()), p


# ── pipeline null rule ────────────────────────────────────────────────────────
class _Grounder:
    """difficulty by surface prefix: 'RED*' → red, else green.

    Records every ``judge``/``scope_id``/``judge_cache`` it was called with, so
    tests can assert ``pipeline.run`` threads them through unchanged.
    """
    name = "fake"

    def __init__(self):
        self.calls: list[dict] = []

    def ground(self, mention, *, judge=None, scope_id=None, judge_cache=None):
        self.calls.append({"judge": judge, "scope_id": scope_id, "judge_cache": judge_cache})
        if mention.surface.startswith("RED"):
            return GroundingResult("red", None, [], trace={})
        ref = WikidataRef.from_qid("Q1", "X")
        return GroundingResult("green", ref, [ref], trace={"canon_en": ["X"]})


class _Pairer:
    name = "fake"

    def pair(self, req, *, judge=None):
        return PairResult("X", "green", None)


def test_pipeline_enforces_null_rule_on_red():
    source = "REDterm and GOODterm"
    mentions = [
        TermMention("REDterm", char_start=0, char_end=7),
        TermMention("GOODterm", char_start=12, char_end=20),
    ]
    terms = pipeline.run(source, "X here", mentions, grounder=_Grounder(), pairer=_Pairer())
    red = next(t for t in terms if t.source_surface == "REDterm")
    good = next(t for t in terms if t.source_surface == "GOODterm")
    assert red.difficulty == "red"
    assert red.grounded is None and red.candidates == []
    assert red.pair_accuracy is None and red.recommended is None
    assert good.difficulty == "green" and good.pair_accuracy == "green"


def test_pipeline_threads_judge_scope_and_cache_to_grounder():
    fake_judge = lambda prompt: {"qid": "Q1", "reason": "test"}
    cache: dict = {}
    grounder = _Grounder()
    mentions = [TermMention("GOODterm", char_start=0, char_end=8)]
    pipeline.run("GOODterm here", "X here", mentions, grounder=grounder, pairer=_Pairer(),
                 judge=fake_judge, scope_id="para-1", judge_cache=cache)
    assert len(grounder.calls) == 1
    assert grounder.calls[0]["judge"] is fake_judge
    assert grounder.calls[0]["scope_id"] == "para-1"
    assert grounder.calls[0]["judge_cache"] is cache


# ── per-mention isolation (defense-in-depth on top of a grounding strategy's
# own error handling -- see grounding/label_first.py's broadened catch) ──────
class _FlakyGrounder:
    """green for every mention except one whose surface triggers a raised
    exception -- simulates a grounding strategy that lets an error escape
    uncaught, independent of any particular strategy's own error handling."""
    name = "flaky"

    def __init__(self, raise_on: str, exc: Exception):
        self.raise_on = raise_on
        self.exc = exc
        self.calls: list[str] = []

    def ground(self, mention, *, judge=None, scope_id=None, judge_cache=None):
        self.calls.append(mention.surface)
        if mention.surface == self.raise_on:
            raise self.exc
        ref = WikidataRef.from_qid("Q1", "X")
        return GroundingResult("green", ref, [ref], trace={"canon_en": ["X"]})


def test_pipeline_isolates_mention_whose_grounder_raises_and_keeps_the_rest():
    # Regression: pipeline.run() used to have no per-mention try/except, so one
    # raised lookup error killed the whole paragraph's extraction (0 terms back
    # instead of just dropping the one bad mention).
    mentions = [
        TermMention("BADterm", char_start=0, char_end=7),
        TermMention("GOODterm", char_start=12, char_end=20),
    ]
    grounder = _FlakyGrounder(raise_on="BADterm", exc=RuntimeError("boom"))
    terms = pipeline.run("BADterm and GOODterm", "X here", mentions, grounder=grounder, pairer=_Pairer())

    assert grounder.calls == ["BADterm", "GOODterm"]              # loop continued past the raise
    assert [t.source_surface for t in terms] == ["GOODterm"]      # bad mention dropped, not the paragraph
    assert terms[0].difficulty == "green"


def test_pipeline_logs_skipped_mention_at_warning_level_no_secrets(caplog):
    mentions = [TermMention("BADterm", char_start=0, char_end=7)]
    grounder = _FlakyGrounder(raise_on="BADterm", exc=RuntimeError("wikidata unavailable"))

    with caplog.at_level(logging.WARNING, logger="palimpsest.terminology.pipeline"):
        terms = pipeline.run("BADterm", "X", mentions, grounder=grounder, pairer=_Pairer())

    assert terms == []
    assert caplog.records                                          # something was logged
    assert all(rec.levelno == logging.WARNING for rec in caplog.records)
    assert any("BADterm" in rec.getMessage() for rec in caplog.records)


def test_pipeline_does_not_swallow_fatal_grounding_judge_error():
    # FatalGroundingJudgeError is an explicit halt marker (token-limit overflow,
    # per-call gate violations) -- the per-mention isolation must NOT treat it
    # like an ordinary lookup failure; it has to propagate and stop the run.
    mentions = [
        TermMention("HALTterm", char_start=0, char_end=8),
        TermMention("GOODterm", char_start=12, char_end=20),
    ]
    grounder = _FlakyGrounder(raise_on="HALTterm", exc=FatalGroundingJudgeError("token-limit overflow"))

    with pytest.raises(FatalGroundingJudgeError):
        pipeline.run("HALTterm and GOODterm", "X here", mentions, grounder=grounder, pairer=_Pairer())
    assert grounder.calls == ["HALTterm"]  # halted before reaching the next mention


def test_db_tuple_candidates_never_null():
    ref = WikidataRef.from_qid("Q1", "X")
    from palimpsest.terminology.base import Term

    red = Term("s", "s", "ctx", 0, 1, "red", None, [], None, None, None, "")
    row = red.db_tuple(7)
    assert row[8] == json.dumps([])            # candidates_json is '[]', never None
    assert row[7] is None                       # grounded_json None on red


# ── extraction: sentence-initial capital drop ─────────────────────────────────
def test_deterministic_extract_drops_sentence_initial_single_word():
    ms = deterministic_extract("Вавилон пал. Позже город восстановил Навуходоносор.")
    surfaces = {m.surface for m in ms}
    assert "Вавилон" not in surfaces        # single word at sentence start → dropped
    assert "Навуходоносор" in surfaces       # mid-sentence proper noun → kept


# ── grounding candidate generation (fake Wikidata client) ─────────────────────
from palimpsest.terminology.base import GroundingConfig
from palimpsest.terminology.grounding.candidates import generate_candidates


def _entity(qid, en, ru=None, p31=(), enwiki=None):
    e = {"id": qid, "labels": {}, "aliases": {}, "descriptions": {}, "claims": {}, "sitelinks": {}}
    if en:
        e["labels"]["en"] = {"value": en}
    if ru:
        e["labels"]["ru"] = {"value": ru}
    if p31:
        e["claims"]["P31"] = [{"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": t}}}} for t in p31]
    if enwiki:
        e["sitelinks"]["enwiki"] = {"title": enwiki}
    return e


class _FakeWD:
    """Minimal WikidataClient stand-in for deterministic strategy tests."""
    def __init__(self, search=None, cirrus=None, entities=None, wiki=None):
        self.n_calls = 0
        self._search = search or {}
        self._cirrus = cirrus or {}
        self._entities = entities or {}
        self._wiki = wiki or {}

    def search_entities(self, term, lang="ru", limit=7):
        return list(self._search.get(term, []))

    def search_cirrus(self, term, limit=7):
        return list(self._cirrus.get(term, []))

    def wikipedia_wikibase_item(self, title, lang="ru"):
        return self._wiki.get(title)

    def get_entities(self, qids, **kw):
        return {q: self._entities[q] for q in qids if q in self._entities}


def test_candidates_cirrus_fallback_on_zero_prefix_hits():
    # prefix search misses; CirrusSearch recovers the entity
    wd = _FakeWD(search={}, cirrus={"Саргона": [{"id": "Q199461"}]},
                 entities={"Q199461": _entity("Q199461", "Sargon of Akkad", "Саргон", p31=("Q5",), enwiki="Sargon")})
    gen = generate_candidates(wd, TermMention(surface="Саргона", lemma="Саргона"), GroundingConfig())
    assert gen["source"] == "cirrus"
    assert [c["qid"] for c in gen["candidates"]] == ["Q199461"]


def test_candidates_wikipedia_langlink_last_resort():
    # prefix + CirrusSearch both miss → RU Wikipedia title → Wikidata item recovers it
    wd = _FakeWD(search={}, cirrus={},
                 wiki={"Урукагина": "Q312060"},
                 entities={"Q312060": _entity("Q312060", "Urukagina", "Урукагина", p31=("Q5",), enwiki="Urukagina")})
    gen = generate_candidates(wd, TermMention(surface="Уруинимгину", lemma="Урукагина"), GroundingConfig())
    assert gen["source"] == "wikipedia_langlink"
    assert [c["qid"] for c in gen["candidates"]] == ["Q312060"]


def test_candidates_query_strategy_labels_escalation_ladder():
    # Same fixture as test_candidates_wikipedia_langlink_last_resort: prefix
    # search misses both forms (lemma+surface -> 2 queries), CirrusSearch
    # misses both forms too (2 more), sitelink finally resolves it (1 more)
    # -- 5 queries for one 2-word mention, each carrying the backend that
    # produced it so a trace UI can distinguish escalation from repetition.
    wd = _FakeWD(search={}, cirrus={}, wiki={"Урукагина": "Q312060"},
                 entities={"Q312060": _entity("Q312060", "Urukagina", "Урукагина", p31=("Q5",), enwiki="Urukagina")})
    gen = generate_candidates(wd, TermMention(surface="Уруинимгину", lemma="Урукагина"), GroundingConfig())
    assert gen["source"] == "wikipedia_langlink"
    strategies = [q["strategy"] for q in gen["queries"]]
    assert strategies == ["prefix", "prefix", "cirrus", "cirrus", "sitelink"]
    assert all(q["strategy"] in {"prefix", "cirrus", "sitelink"} for q in gen["queries"])


def test_candidates_use_sitelink_false_skips_wikipedia_rung_cirrus_still_fires():
    # sitelink rung disabled; the (independent) cirrus rung still recovers hits.
    wd = _FakeWD(search={}, cirrus={"Саргона": [{"id": "Q199461"}]},
                 entities={"Q199461": _entity("Q199461", "Sargon of Akkad", "Саргон", p31=("Q5",), enwiki="Sargon")})
    config = GroundingConfig(use_sitelink=False)
    gen = generate_candidates(wd, TermMention(surface="Саргона", lemma="Саргона"), config)
    assert gen["source"] == "cirrus"
    assert [c["qid"] for c in gen["candidates"]] == ["Q199461"]

    # entity only reachable via the sitelink rung -> stays unresolved, and the
    # rung is never even attempted (no "wikipedia_wikibase_item" query logged).
    wd2 = _FakeWD(search={}, cirrus={}, wiki={"Урукагина": "Q312060"},
                  entities={"Q312060": _entity("Q312060", "Urukagina", "Урукагина", p31=("Q5",), enwiki="Urukagina")})
    gen2 = generate_candidates(wd2, TermMention(surface="Уруинимгину", lemma="Урукагина"), config)
    assert gen2["source"] == "none"
    assert gen2["candidates"] == []
    assert not any(q["mechanism"] == "wikipedia_wikibase_item" for q in gen2["queries"])


def test_candidates_use_cirrus_false_skips_cirrus_rung_sitelink_still_fires():
    # cirrus rung disabled; the (independent) sitelink rung still recovers hits.
    wd = _FakeWD(search={}, cirrus={}, wiki={"Урукагина": "Q312060"},
                 entities={"Q312060": _entity("Q312060", "Urukagina", "Урукагина", p31=("Q5",), enwiki="Urukagina")})
    config = GroundingConfig(use_cirrus=False)
    gen = generate_candidates(wd, TermMention(surface="Уруинимгину", lemma="Урукагина"), config)
    assert gen["source"] == "wikipedia_langlink"
    assert [c["qid"] for c in gen["candidates"]] == ["Q312060"]

    # entity only reachable via cirrus -> stays unresolved, and the rung is
    # never even attempted (no "cirrus" query logged).
    wd2 = _FakeWD(search={}, cirrus={"Саргона": [{"id": "Q199461"}]},
                  entities={"Q199461": _entity("Q199461", "Sargon of Akkad", "Саргон", p31=("Q5",), enwiki="Sargon")})
    gen2 = generate_candidates(wd2, TermMention(surface="Саргона", lemma="Саргона"), config)
    assert gen2["source"] == "none"
    assert gen2["candidates"] == []
    assert not any(q["mechanism"] == "cirrus" for q in gen2["queries"])


def test_candidates_redirect_canonicalized_to_target_qid():
    # search returns a redirect id; the enriched entity carries the canonical id
    wd = _FakeWD(search={"Тест": [{"id": "Q_OLD"}]},
                 entities={"Q_OLD": _entity("Q_CANON", "Test", "Тест", p31=("Q5",), enwiki="Test")})
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert gen["candidates"][0]["qid"] == "Q_CANON"   # not the pre-redirect Q_OLD


# ── search_mode widening tiers (wiki-eval experiment, 2026-07-10) ────────────
from palimpsest.terminology.base import FatalGroundingJudgeError
from palimpsest.terminology.grounding.candidates import _alt_names_from_context


def test_alt_names_from_context_unqi_case():
    # canonical example from the spec: «Унку (Unqi)» -> ["Unqi"]
    assert _alt_names_from_context("Унку", "Народ Унку (Unqi) жил в Сирии.") == ["Unqi"]


def test_alt_names_from_context_comma_and_ili_split():
    assert _alt_names_from_context("Унку", "Унку (Unqi, или Уна) упоминается в текстах.") == ["Unqi", "Уна"]


def test_alt_names_from_context_no_parens_returns_empty():
    assert _alt_names_from_context("Унку", "Унку жил в Сирии.") == []


def test_alt_names_from_context_paren_not_immediately_following_returns_empty():
    # the parenthesized group belongs to a different word -- "immediately
    # following" per spec means only whitespace may separate surface and "("
    assert _alt_names_from_context("Унку", "Унку и другое слово (пример) здесь.") == []


def test_alt_names_from_context_empty_surface_or_context_returns_empty():
    assert _alt_names_from_context("", "Унку (Unqi) жил.") == []
    assert _alt_names_from_context("Унку", "") == []


def test_candidates_baseline_mode_never_adds_source_key():
    # hard regression constraint: baseline candidates never gain a "source"
    # key, even when a hit is found (byte-for-byte wire identity).
    wd = _FakeWD(search={"Тест": [{"id": "Q1"}]}, entities={"Q1": _entity("Q1", "Test", "Тест")})
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert "source" not in gen["candidates"][0]


def test_candidates_alt_names_not_triggered_in_baseline_mode():
    # even though the context has a parenthesized alternate that WOULD
    # resolve under alt-names, default (baseline) search_mode must not widen.
    wd = _FakeWD(search={"Unqi": [{"id": "Q99"}]}, entities={"Q99": _entity("Q99", "Unqi")})
    mention = TermMention(surface="Унку", lemma="Унку", context="Унку (Unqi) жил.")
    gen = generate_candidates(wd, mention, GroundingConfig())  # default search_mode="baseline"
    assert gen["candidates"] == []
    assert gen["source"] == "none"


def test_candidates_alt_names_widens_when_baseline_finds_nothing():
    wd = _FakeWD(search={"Unqi": [{"id": "Q99"}]}, entities={"Q99": _entity("Q99", "Unqi", p31=("Q6256",))})
    mention = TermMention(surface="Унку", lemma="Унку", context="Народ Унку (Unqi) жил в Сирии.")
    config = GroundingConfig(search_mode="alt-names")
    gen = generate_candidates(wd, mention, config)
    assert gen["source"] == "alt"
    assert [c["qid"] for c in gen["candidates"]] == ["Q99"]
    assert gen["candidates"][0]["source"] == "alt"
    assert any(q["kind"] == "alt" for q in gen["queries"])


def test_candidates_alt_names_stays_empty_when_context_has_no_alternates():
    wd = _FakeWD()  # nothing to find anywhere
    mention = TermMention(surface="Унку", lemma="Унку", context="Унку жил в Сирии, без скобок.")
    config = GroundingConfig(search_mode="alt-names")
    gen = generate_candidates(wd, mention, config)
    assert gen["candidates"] == []
    assert gen["source"] == "none"


def test_candidates_alt_names_mode_never_calls_label_guesser():
    # alt-names is zero-LLM-calls by construction: even if a label_guesser
    # happened to be passed in, it must not be consulted at this tier.
    calls = []
    wd = _FakeWD()
    mention = TermMention(surface="Совсем неизвестное", lemma="неизвестное", context="без скобок")
    config = GroundingConfig(search_mode="alt-names")
    gen = generate_candidates(wd, mention, config, label_guesser=lambda p: calls.append(p) or {})
    assert calls == []
    assert gen["candidates"] == []


def test_candidates_label_guess_tier_fires_only_after_alt_names_also_empty():
    wd = _FakeWD(search={"Guessed Label": [{"id": "Q77"}]}, entities={"Q77": _entity("Q77", "Guessed Label")})
    calls = []

    def fake_guesser(prompt):
        calls.append(prompt)
        return {"label_en": "Guessed Label", "label_ru": None}

    mention = TermMention(surface="Загадка", lemma="Загадка", context="Загадка была необычной, без скобок.")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=fake_guesser)

    assert len(calls) == 1
    assert "Загадка" in calls[0]  # surface reached the prompt
    assert gen["source"] == "label_guess"
    assert gen["candidates"][0]["source"] == "label_guess"
    assert gen["candidates"][0]["qid"] == "Q77"
    assert any(q["kind"] == "label_guess" for q in gen["queries"])


def test_candidates_label_guess_variants_reach_search_khana_class():
    """The Ханейское-царство class (2026-07-17): the common guesses
    («Хана»/"Hana") find nothing, but a scholarly-romanization variant
    ("Khana") from the new `variants` field must be queried and win."""
    wd = _FakeWD(search={"Khana": [{"id": "Q425405"}]},
                 entities={"Q425405": _entity("Q425405", "Kingdom of Khana")})

    def fake_guesser(prompt):
        return {"label_ru": "Хана", "label_en": "Hana", "variants": ["Khana", "Хана", None, 42]}

    mention = TermMention(surface="Ханейское царство", lemma="Ханейское царство",
                          context="покорила Ханейское царство, распространив власть.")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=fake_guesser)

    queried = [q["q"] for q in gen["queries"] if q["kind"] == "label_guess"]
    assert queried == ["Хана", "Hana", "Khana"]  # deduped, junk types dropped
    assert all(q["strategy"] == "guess" for q in gen["queries"] if q["kind"] == "label_guess")
    assert gen["candidates"][0]["qid"] == "Q425405"
    assert gen["candidates"][0]["source"] == "label_guess"


def test_candidates_label_guess_later_form_rank2_survives_junk_rich_first_form():
    """Prod 2026-07-17, «Ханейское царство» round 2: the first guess form
    («Хана») returned 7 junk hits that filled ``hits[:enrich_top=5]``, so
    "Khana" rank 2 = Q425405 never reached enrichment or the judge. The
    rank-wise interleave in ``_widen`` plus the widened-tier enrich cap must
    let a later form's top-2 hit through."""
    junk = [{"id": f"Q_J{i}"} for i in range(7)]
    wd = _FakeWD(
        search={"Хана": junk, "Khana": [{"id": "Q_J0"}, {"id": "Q425405"}]},
        entities={
            "Q425405": _entity("Q425405", "Kingdom of Khana"),
            **{f"Q_J{i}": _entity(f"Q_J{i}", f"Junk {i}") for i in range(7)},
        },
    )

    def fake_guesser(prompt):
        return {"label_ru": "Хана", "label_en": None, "variants": ["Khana"]}

    mention = TermMention(surface="Ханейское царство", lemma="Ханейское царство",
                          context="покорила Ханейское царство, распространив власть.")
    gen = generate_candidates(wd, mention, GroundingConfig(search_mode="label-guess"),
                              label_guesser=fake_guesser)

    qids = [c["qid"] for c in gen["candidates"]]
    assert "Q425405" in qids
    # interleave puts each form's rank-1 first: Хана#1, Khana#1(dup), then rank 2
    assert qids[:3] == ["Q_J0", "Q_J1", "Q425405"]


def test_candidates_label_guess_variants_capped_at_five_forms():
    wd = _FakeWD(search={}, entities={})

    def fake_guesser(prompt):
        return {"label_ru": "а", "label_en": "b", "variants": ["c", "d", "e", "f", "g"]}

    mention = TermMention(surface="Нечто", lemma="Нечто", context="Нечто случилось, без скобок.")
    gen = generate_candidates(wd, mention, GroundingConfig(search_mode="label-guess"),
                              label_guesser=fake_guesser)
    queried = [q["q"] for q in gen["queries"] if q["kind"] == "label_guess"]
    assert queried == ["а", "b", "c", "d", "e"]  # hard cap of 5 widening searches


def test_candidates_label_guess_not_called_when_alt_names_already_succeeded():
    # cumulation: alt-names success short-circuits the (more expensive)
    # label-guess tier entirely.
    wd = _FakeWD(search={"Unqi": [{"id": "Q99"}]}, entities={"Q99": _entity("Q99", "Unqi")})
    calls = []

    def fake_guesser(prompt):
        calls.append(prompt)
        return {"label_en": "Should not be used"}

    mention = TermMention(surface="Унку", lemma="Унку", context="Унку (Unqi) жил.")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=fake_guesser)

    assert calls == []
    assert gen["source"] == "alt"


def test_candidates_label_guess_mode_without_guesser_yields_no_candidates():
    # label_guesser=None (e.g. no judge configured) degrades to "skip this
    # tier" rather than crashing -- the CLI-level guard is what's supposed to
    # prevent this combination in practice (search_mode=label-guess + no
    # judge), generate_candidates itself stays defensive regardless.
    wd = _FakeWD()
    mention = TermMention(surface="Совсем неизвестный термин", lemma="термин", context="")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=None)
    assert gen["candidates"] == []
    assert gen["source"] == "none"


def test_candidates_label_guess_call_failure_degrades_to_no_guess():
    wd = _FakeWD()

    def failing_guesser(prompt):
        raise RuntimeError("boom")

    mention = TermMention(surface="X", lemma="X", context="")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=failing_guesser)
    assert gen["candidates"] == []
    assert gen["source"] == "none"


def test_candidates_label_guess_fatal_error_propagates():
    wd = _FakeWD()

    def fatal_guesser(prompt):
        raise FatalGroundingJudgeError("halt marker")

    mention = TermMention(surface="X", lemma="X", context="")
    config = GroundingConfig(search_mode="label-guess")
    with pytest.raises(FatalGroundingJudgeError):
        generate_candidates(wd, mention, config, label_guesser=fatal_guesser)


def test_candidates_label_guess_ignores_null_labels_in_response():
    wd = _FakeWD()

    def null_guesser(prompt):
        return {"label_ru": None, "label_en": None}

    mention = TermMention(surface="X", lemma="X", context="")
    config = GroundingConfig(search_mode="label-guess")
    gen = generate_candidates(wd, mention, config, label_guesser=null_guesser)
    assert gen["candidates"] == []
    assert gen["source"] == "none"


# ── G6 label_first: norm() + exact_match() ─────────────────────────────────────
from palimpsest.terminology.grounding.match import exact_match, norm


def test_norm_folds_yo_to_ye_both_cases():
    assert norm("Семён") == norm("Семен")
    assert norm("ЁЖИК") == norm("ЕЖИК")


def test_norm_collapses_whitespace_including_tabs():
    assert norm("  Саргон\tАккадский  ") == norm("Саргон Аккадский")


def test_norm_folds_unicode_dashes_to_ascii():
    # U+2010 hyphen, U+2013 en dash, U+2015 horizontal bar, U+2212 minus sign
    for dash in ("‐", "‑", "‒", "–", "—", "―", "−"):
        assert norm(f"Кадашман{dash}Харбе") == norm("Кадашман-Харбе")


def _candidate(qid, label_ru=None, aliases_ru=(), aliases_en=()):
    return {
        "qid": qid, "label_ru": label_ru, "label_en": None, "description": "",
        "aliases_ru": list(aliases_ru), "aliases_en": list(aliases_en),
    }


def test_exact_match_label_hit_records_matched_kind():
    cands = [_candidate("Q1", label_ru="Саргон")]
    hits = exact_match(["Саргон"], cands, match_aliases=True)
    assert len(hits) == 1
    assert hits[0]["qid"] == "Q1"
    assert hits[0]["matched"] == {"kind": "label_ru", "value": "Саргон", "query": "Саргон"}


def test_exact_match_prefers_label_over_alias_when_both_present():
    # candidate matches on label AND (separately) would match on alias for
    # another query — label match must win and be the recorded kind.
    cands = [_candidate("Q1", label_ru="Саргон", aliases_ru=["Саргон Аккадский"])]
    hits = exact_match(["Саргон"], cands, match_aliases=True)
    assert len(hits) == 1
    assert hits[0]["matched"]["kind"] == "label_ru"


def test_exact_match_alias_ru_hit_when_label_differs():
    cands = [_candidate("Q1", label_ru="Sargon of Akkad", aliases_ru=["Саргон"])]
    hits = exact_match(["Саргон"], cands, match_aliases=True)
    assert len(hits) == 1
    assert hits[0]["matched"] == {"kind": "alias_ru", "value": "Саргон", "query": "Саргон"}


def test_exact_match_alias_en_hit_when_query_is_english_form():
    cands = [_candidate("Q1", label_ru="Саргон", aliases_en=["Sargon"])]
    hits = exact_match(["Sargon"], cands, match_aliases=True)
    assert len(hits) == 1
    assert hits[0]["matched"] == {"kind": "alias_en", "value": "Sargon", "query": "Sargon"}


def test_exact_match_alias_only_hit_respects_match_aliases_toggle():
    cands = [_candidate("Q1", label_ru="Sargon of Akkad", aliases_ru=["Саргон"])]
    assert exact_match(["Саргон"], cands, match_aliases=False) == []
    assert len(exact_match(["Саргон"], cands, match_aliases=True)) == 1


def test_exact_match_no_hit_returns_empty_list():
    cands = [_candidate("Q1", label_ru="Саргон")]
    assert exact_match(["Навуходоносор"], cands, match_aliases=True) == []


# NOTE(Task 12): further G6 label_first tests (toggle-matrix, trace-completeness,
# full error-policy) go here; below are only the 4 core decision-table cases.
from palimpsest.terminology.grounding.label_first import LabelFirstGrounding


def _judge_counter(response):
    calls = []

    def judge(prompt):
        calls.append(prompt)
        return response

    return judge, calls


def test_label_first_exact_one_match_resolves_green_without_judge():
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон")})
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"), judge=judge)

    assert result.difficulty == "green"
    assert result.trace["resolved_by"] == "exact_label"
    assert result.grounded.qid == "Q1"
    assert calls == []


def test_label_first_two_exact_matches_escalates_to_judge_disambiguation():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q2", "reason": "context points to Thutmose II"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=judge)

    assert result.difficulty == "yellow"
    assert result.trace["resolved_by"] == "llm_disambiguation"
    assert result.grounded.qid == "Q2"
    assert len(calls) == 1


def test_label_first_candidates_but_no_exact_match_judge_rejects_to_red():
    wd = _FakeWD(search={"Кадаш": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Kadashman-Harbe I", "Кадашман-Харбе I")})
    judge, calls = _judge_counter({"qid": None, "reason": "no candidate fits"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Кадаш", lemma="Кадаш"), judge=judge)

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "judge_rejected"
    assert result.grounded is None
    assert len(calls) == 1


def test_label_first_no_candidates_resolves_red_without_judge():
    wd = _FakeWD(search={}, cirrus={}, wiki={})
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Неизвестный", lemma="Неизвестный"), judge=judge)

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "no_candidates"
    assert result.grounded is None
    assert calls == []


# ── Task 7b: judge-decision cache ("one sense per discourse") ─────────────────
def test_label_first_judge_cache_hit_reuses_decision_within_same_scope():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q2", "reason": "context points to Thutmose II"})
    strategy = LabelFirstGrounding(wd)
    cache: dict = {}
    mention = TermMention(surface="Тутмос", lemma="Тутмос")

    result1 = strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=cache)
    result2 = strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=cache)

    assert len(calls) == 1  # judge invoked exactly once
    assert result1.difficulty == result2.difficulty == "yellow"
    assert result1.trace["resolved_by"] == result2.trace["resolved_by"] == "llm_disambiguation"
    assert result1.grounded.qid == result2.grounded.qid == "Q2"
    assert result1.trace["judge"]["cache_hit"] is False
    assert result2.trace["judge"]["cache_hit"] is True


def test_label_first_judge_cache_miss_on_different_scope_id():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q2", "reason": "context points to Thutmose II"})
    strategy = LabelFirstGrounding(wd)
    cache: dict = {}
    mention = TermMention(surface="Тутмос", lemma="Тутмос")

    strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=cache)
    strategy.ground(mention, judge=judge, scope_id="doc2", judge_cache=cache)

    assert len(calls) == 2  # different scope_id -> miss -> judge invoked again


def test_label_first_judge_cache_miss_on_different_candidate_set():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос"),
                           "Q3": _entity("Q3", "Thutmose III", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q2", "reason": "context points to Thutmose II"})
    strategy = LabelFirstGrounding(wd)
    cache: dict = {}
    mention = TermMention(surface="Тутмос", lemma="Тутмос")

    strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=cache)

    # second call sees a 3rd candidate (different candidate_qids) -> different key -> miss
    wd2 = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}, {"id": "Q3"}]},
                  entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                            "Q2": _entity("Q2", "Thutmose II", "Тутмос"),
                            "Q3": _entity("Q3", "Thutmose III", "Тутмос")})
    strategy2 = LabelFirstGrounding(wd2)
    strategy2.ground(mention, judge=judge, scope_id="doc1", judge_cache=cache)

    assert len(calls) == 2  # different candidate set -> miss -> judge invoked again


def test_label_first_no_cache_when_judge_cache_is_none_preserves_backcompat():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q2", "reason": "context points to Thutmose II"})
    strategy = LabelFirstGrounding(wd)
    mention = TermMention(surface="Тутмос", lemma="Тутмос")

    strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=None)
    strategy.ground(mention, judge=judge, scope_id="doc1", judge_cache=None)

    assert len(calls) == 2  # no cache dict -> no caching -> judge called every time


# ── Task 12: toggle matrix ──────────────────────────────────────────────────
def test_label_first_use_lemma_false_queries_surface_not_lemma():
    from palimpsest.terminology.grounding.candidates import generate_candidates
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон")})
    mention = TermMention(surface="Саргон", lemma="Саргона")  # lemma differs from surface

    gen_with_lemma = generate_candidates(wd, mention, GroundingConfig(use_lemma=True))
    queried_with_lemma = {q["q"] for q in gen_with_lemma["queries"]}
    assert "Саргона" in queried_with_lemma      # lemma query issued

    gen_without_lemma = generate_candidates(wd, mention, GroundingConfig(use_lemma=False))
    queried_without_lemma = {q["q"] for q in gen_without_lemma["queries"]}
    assert "Саргона" not in queried_without_lemma
    assert "Саргон" in queried_without_lemma    # surface query still issued


def test_label_first_use_fallbacks_false_cirrus_only_term_stays_no_candidates():
    # entity is only reachable via CirrusSearch (prefix search misses); with
    # fallbacks disabled the fallback ladder is never attempted -> red/no_candidates.
    wd = _FakeWD(search={}, cirrus={"Саргона": [{"id": "Q199461"}]},
                 entities={"Q199461": _entity("Q199461", "Sargon of Akkad", "Саргон")})
    judge, calls = _judge_counter({"qid": "Q199461", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd, config=GroundingConfig(use_fallbacks=False))
    result = strategy.ground(TermMention(surface="Саргона", lemma="Саргона"), judge=judge)

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "no_candidates"
    assert calls == []  # fallback never attempted -> no candidates -> no judge call


def test_grounding_config_use_fallbacks_compat_sets_and_reads_both_split_fields():
    # deprecated use_fallbacks alias still sets/reads both use_cirrus and use_sitelink.
    assert GroundingConfig().use_fallbacks is True                    # default: both on
    off = GroundingConfig(use_fallbacks=False)
    assert (off.use_cirrus, off.use_sitelink) == (False, False)
    assert off.use_fallbacks is False
    on = GroundingConfig(use_fallbacks=True)
    assert (on.use_cirrus, on.use_sitelink) == (True, True)
    assert on.use_fallbacks is True
    # split fields set independently -> the derived compat read is False
    split = GroundingConfig(use_cirrus=True, use_sitelink=False)
    assert split.use_fallbacks is False


def test_label_first_match_aliases_false_forces_escalation_instead_of_exact():
    # candidate matches only via alias, not label_ru; with match_aliases off the
    # exact-match set is empty even though candidates exist -> escalate to judge,
    # not a silent exact_label resolution.
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Sargon of Akkad")})
    # label_ru differs from the query; alias_ru carries the exact form instead.
    wd._entities["Q1"]["labels"]["ru"] = {"value": "Sargon of Akkad"}
    wd._entities["Q1"]["aliases"]["ru"] = [{"value": "Саргон"}]

    judge, calls = _judge_counter({"qid": "Q1", "reason": "alias-only match, judge confirms"})
    strategy = LabelFirstGrounding(wd, config=GroundingConfig(match_aliases=False))
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"), judge=judge)

    assert result.trace["resolved_by"] != "exact_label"
    assert result.trace["exact_matches"] == []
    assert len(calls) == 1  # escalated to judge instead of resolving deterministically


# ── Task 12: trace v1 completeness ──────────────────────────────────────────
_REQUIRED_TRACE_KEYS = {
    "v", "config", "queries", "search_source", "candidates", "exact_matches",
    "resolved_by", "judge", "chosen_qid", "n_api_calls", "latency_ms",
}


def test_label_first_trace_complete_on_exact_label_path():
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон")})
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"), judge=judge)

    assert _REQUIRED_TRACE_KEYS <= set(result.trace)
    assert result.trace["resolved_by"] == "exact_label"


def test_label_first_trace_complete_on_no_candidates_path():
    wd = _FakeWD(search={}, cirrus={}, wiki={})
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Неизвестный", lemma="Неизвестный"), judge=judge)

    assert _REQUIRED_TRACE_KEYS <= set(result.trace)
    assert result.trace["resolved_by"] == "no_candidates"


def test_label_first_trace_config_writes_split_fields_not_deprecated_use_fallbacks():
    # GroundingConfig split use_fallbacks -> use_cirrus/use_sitelink (2026-07-06,
    # see base.py's docstring); the trace's "config" block must reflect the
    # actual current toggles, not the deprecated combined name -- no consumer
    # (frontend GlossaryTab/glossary-grouping, the demo contracts spec) reads
    # trace.config, so this is a straight rename, not a compat shim.
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон")})
    strategy = LabelFirstGrounding(wd, config=GroundingConfig(use_cirrus=False, use_sitelink=True))
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"))

    assert result.trace["config"]["use_cirrus"] is False
    assert result.trace["config"]["use_sitelink"] is True
    assert "use_fallbacks" not in result.trace["config"]


# ── Task 12: error policy ───────────────────────────────────────────────────
class _RaisingWD:
    """Fake WikidataClient whose search methods raise, simulating an unavailable API."""
    n_calls = 0

    def search_entities(self, term, lang="ru", limit=7):
        raise RuntimeError("wikidata search_entities exhausted retries")

    def search_cirrus(self, term, limit=7):
        raise RuntimeError("wikidata search_cirrus exhausted retries")

    def wikipedia_wikibase_item(self, title, lang="ru"):
        raise RuntimeError("wikidata wikipedia_wikibase_item exhausted retries")

    def get_entities(self, qids, **kw):
        return {}


def test_label_first_wikidata_unavailable_is_red_and_distinct_from_no_candidates():
    wd = _RaisingWD()
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"), judge=judge)

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "wikidata_unavailable"
    assert result.trace["resolved_by"] != "no_candidates"
    assert calls == []  # candidate-gen failure short-circuits before any judge call


# ── HTTPError/OSError catch broadening (per-mention isolation root cause) ────
class _RaisingOnceWD:
    """Fake WikidataClient whose search methods raise a single injected
    exception -- used to prove label_first.py's catch is broad enough for
    non-RuntimeError failures (urllib.error.HTTPError, OSError) that
    WikidataClient's own retry loop lets escape bare (see wikidata.py::_fetch
    -- a non-retryable HTTPError, or a retryable one whose retries are
    exhausted, is re-raised unwrapped, not as RuntimeError)."""
    n_calls = 0

    def __init__(self, exc: Exception):
        self._exc = exc

    def search_entities(self, term, lang="ru", limit=7):
        raise self._exc

    def search_cirrus(self, term, limit=7):
        raise self._exc

    def wikipedia_wikibase_item(self, title, lang="ru"):
        raise self._exc

    def get_entities(self, qids, **kw):
        return {}


def _http_error(code: int = 503) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://www.wikidata.org/w/api.php", code, "err", {}, None)


def test_label_first_http_error_resolves_wikidata_unavailable_not_crash():
    wd = _RaisingOnceWD(_http_error(503))
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"), judge=judge)

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "wikidata_unavailable"
    assert calls == []  # candidate-gen failure short-circuits before any judge call


def test_label_first_os_error_resolves_wikidata_unavailable_not_crash():
    wd = _RaisingOnceWD(ConnectionResetError("connection reset by peer"))
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Саргон", lemma="Саргон"))

    assert result.difficulty == "red"
    assert result.trace["resolved_by"] == "wikidata_unavailable"


class _PartialFailureWD:
    """_FakeWD-style lookup table that raises for one specific query term and
    resolves the rest normally -- reproduces 'one bad Wikidata call mid-
    paragraph', distinct from _RaisingOnceWD/_RaisingWD which simulate the
    whole client being down for every mention."""

    def __init__(self, search=None, entities=None, raise_on=(), exc=None):
        self.n_calls = 0
        self._search = search or {}
        self._entities = entities or {}
        self._raise_on = set(raise_on)
        self._exc = exc

    def search_entities(self, term, lang="ru", limit=7):
        if term in self._raise_on:
            raise self._exc
        return list(self._search.get(term, []))

    def search_cirrus(self, term, limit=7):
        return []

    def wikipedia_wikibase_item(self, title, lang="ru"):
        return None

    def get_entities(self, qids, **kw):
        return {q: self._entities[q] for q in qids if q in self._entities}


def test_pipeline_survives_one_mention_wikidata_http_error_mid_paragraph():
    # Full-stack regression for the bug this fix addresses: a single
    # non-retryable Wikidata HTTPError on one mention used to propagate
    # uncaught through label_first.ground() (RuntimeError-only catch) and then
    # through pipeline.run()'s mention loop (no per-mention try/except),
    # dropping every term of the paragraph -- not just the one bad lookup.
    wd = _PartialFailureWD(
        search={"Саргон": [{"id": "Q1"}]},
        entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон")},
        raise_on={"Навуходоносор"},
        exc=_http_error(500),
    )
    grounder = LabelFirstGrounding(wd)
    mentions = [
        TermMention(surface="Навуходоносор", lemma="Навуходоносор", char_start=0, char_end=13),
        TermMention(surface="Саргон", lemma="Саргон", char_start=18, char_end=24),
    ]
    terms = pipeline.run("Навуходоносор ... Саргон ...", "... ...", mentions,
                          grounder=grounder, pairer=_Pairer())

    assert [t.source_surface for t in terms] == ["Навуходоносор", "Саргон"]  # both mentions survive
    bad, good = terms
    assert bad.difficulty == "red"
    assert bad.trace["resolved_by"] == "wikidata_unavailable"
    assert good.difficulty == "green"


def test_label_first_judge_raises_resolves_judge_unavailable_called_once_not_retried():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    calls = []

    def flaky_judge(prompt):
        calls.append(prompt)
        raise TimeoutError("judge model timed out")

    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=flaky_judge)

    assert result.difficulty == "yellow"
    assert result.trace["resolved_by"] == "judge_unavailable"
    assert result.grounded is None
    assert len(calls) == 1  # terminal failure -- the strategy itself never retries


def test_label_first_judge_fatal_error_propagates_out_of_ground():
    # FatalGroundingJudgeError (halt marker: token-limit overflow, per-call gate
    # violation) must halt the run, NOT collapse to judge_unavailable like a
    # plain RuntimeError does (wiki-eval experiment v2, spec 2026-07-10 Р15).
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})

    def fatal_judge(prompt):
        raise FatalGroundingJudgeError("token-limit overflow")

    strategy = LabelFirstGrounding(wd)
    with pytest.raises(FatalGroundingJudgeError):
        strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=fatal_judge)


def test_label_first_judge_qid_not_in_candidates_is_judge_unavailable_never_top1():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос")})
    judge, calls = _judge_counter({"qid": "Q999", "reason": "hallucinated qid"})
    strategy = LabelFirstGrounding(wd)
    result = strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=judge)

    assert result.trace["resolved_by"] == "judge_unavailable"
    assert result.grounded is None          # never silently falls back to candidates[0]
    assert result.trace["chosen_qid"] is None
    assert len(calls) == 1


def test_label_first_candidate_order_stable_across_identical_calls():
    wd = _FakeWD(search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}, {"id": "Q3"}]},
                 entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос-A"),
                           "Q2": _entity("Q2", "Thutmose II", "Тутмос-B"),
                           "Q3": _entity("Q3", "Thutmose III", "Тутмос-C")})
    judge, calls = _judge_counter({"qid": "Q1", "reason": "n/a"})
    strategy = LabelFirstGrounding(wd)
    mention = TermMention(surface="Тутмос", lemma="Тутмос")

    result1 = strategy.ground(mention, judge=judge)
    result2 = strategy.ground(mention, judge=judge)

    order1 = [c["qid"] for c in result1.trace["candidates"]]
    order2 = [c["qid"] for c in result2.trace["candidates"]]
    assert order1 == order2 == ["Q1", "Q2", "Q3"]


# ── canon_en propagation regression (label_first -> pipeline -> pairing) ─────
class _CapturingPairer:
    """Fake PairingStrategy that records the PairRequest it was called with."""
    name = "fake"

    def __init__(self):
        self.requests = []

    def pair(self, req, *, judge=None):
        self.requests.append(req)
        return PairResult(None, None, None)


def test_pipeline_propagates_canon_en_from_label_first_to_pairing():
    # Real LabelFirstGrounding against a fake Wikidata client that returns an
    # entity with EN aliases + an enwiki sitelink, so canon_by_qid is non-empty.
    # Regression for the bug where label_first.py never wrote trace["canon_en"],
    # so pipeline.run's gr.trace.get("canon_en", []) was always [] downstream.
    wd = _FakeWD(search={"Саргон": [{"id": "Q1"}]},
                 entities={"Q1": _entity("Q1", "Sargon of Akkad", "Саргон", enwiki="Sargon of Akkad")})
    grounder = LabelFirstGrounding(wd)
    pairer = _CapturingPairer()
    mentions = [TermMention(surface="Саргон", lemma="Саргон", char_start=0, char_end=6)]

    terms = pipeline.run("Саргон правил", "Sargon ruled", mentions, grounder=grounder, pairer=pairer)

    assert terms[0].difficulty == "green"
    assert len(pairer.requests) == 1
    assert pairer.requests[0].canon_en != []
    assert "Sargon of Akkad" in pairer.requests[0].canon_en


# ── Task 10: Wilson CI ──────────────────────────────────────────────────────
def test_wilson_ci_zero_total_is_maximally_uninformative():
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_wilson_ci_matches_known_reference_interval():
    # 61/78 correct, z=1.96 -> the reference interval quoted in spec §5 metrics.json example
    lo, hi = wilson_ci(61, 78)
    assert 0.67 < lo < 0.69
    assert 0.85 < hi < 0.87


# ── grounding quality fix: junk-P31 candidate filtering + near-dup dedup ─────
# Regression for the owner-reported prod defects (2026-07-16): «Египтяне»
# candidates included Wikinews-article items (Q99042315 etc.) reaching the
# judge via the CirrusSearch full-text tier, and «Париж» got judge_rejected
# on document 10 despite Q90 being a slam-dunk exact match (real trace pulled
# from https://glossa-mt.com/api/documents/10 -- see the investigation report).
def _with_desc(entity: dict, en_desc: str = "", ru_desc: str = "") -> dict:
    if en_desc:
        entity["descriptions"]["en"] = {"value": en_desc}
    if ru_desc:
        entity["descriptions"]["ru"] = {"value": ru_desc}
    return entity


def test_candidates_filters_wikinews_article_via_p31():
    # Real shape of the DEFECT 2 report: a Wikinews-article item surfaces via
    # CirrusSearch full-text alongside the genuine entity.
    wd = _FakeWD(
        search={},
        cirrus={"Египтяне": [{"id": "Q41616"}, {"id": "Q99042315"}]},
        entities={
            "Q41616": _with_desc(_entity("Q41616", "Egyptians", "Египтяне", p31=("Q41710",)),
                                  "ethnic group"),
            "Q99042315": _with_desc(_entity("Q99042315", "Египтяне", "Египтяне", p31=("Q17633526",)),
                                     "Wikinews article"),
        },
    )
    gen = generate_candidates(wd, TermMention(surface="Египтяне", lemma="Египтяне"), GroundingConfig())
    qids = [c["qid"] for c in gen["candidates"]]
    assert qids == ["Q41616"]
    assert "Q99042315" not in qids


def test_candidates_filters_each_non_entity_p31_blocklist_value():
    # All 5 blocklisted P31 values are dropped, not just the Wikinews case.
    blocklisted = {
        "QW": "Q17633526",   # Wikinews article
        "QD": "Q4167410",    # Wikimedia disambiguation page
        "QC": "Q4167836",    # Wikimedia category
        "QT": "Q11266439",   # Wikimedia template
        "QL": "Q13406463",   # Wikimedia list article
    }
    entities = {"Q_GOOD": _entity("Q_GOOD", "Real Entity", "РеальнаяСущность", p31=("Q5",))}
    for qid, p31 in blocklisted.items():
        entities[qid] = _entity(qid, f"Meta {qid}", "Мета", p31=(p31,))
    wd = _FakeWD(search={"Тест": [{"id": qid} for qid in ["Q_GOOD", *blocklisted]]}, entities=entities)
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["Q_GOOD"]


def test_candidates_wikinews_description_fallback_when_p31_missing():
    # No P31 claim at all (defensive fallback path): description text alone
    # still catches the single documented "Wikinews article" pattern.
    wd = _FakeWD(
        search={"Тест": [{"id": "Q1"}]},
        entities={"Q1": _with_desc(_entity("Q1", "Тест", "Тест"), "Wikinews article")},
    )
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert gen["candidates"] == []


def test_candidates_legitimate_entity_with_no_p31_is_not_dropped():
    # No P31 + an unrelated description must NOT be treated as junk -- the
    # filter is narrowly targeted, not "reject anything without P31".
    wd = _FakeWD(search={"Тест": [{"id": "Q1"}]},
                 entities={"Q1": _with_desc(_entity("Q1", "Тест", "Тест"), "a plain entity")})
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["Q1"]


def test_candidates_dedup_identical_label_and_description():
    # Two candidates with the exact same (label_ru, description) offered to
    # the judge are pure noise -- keep only the first.
    wd = _FakeWD(
        search={"Париж": [{"id": "QDUPA"}, {"id": "QDUPB"}]},
        entities={
            "QDUPA": _with_desc(_entity("QDUPA", "Paris FC", "Париж"), "football club in France"),
            "QDUPB": _with_desc(_entity("QDUPB", "Paris FC", "Париж"), "football club in France"),
        },
    )
    gen = generate_candidates(wd, TermMention(surface="Париж", lemma="Париж"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["QDUPA"]


def test_candidates_dedup_keeps_distinct_descriptions_for_same_label():
    # Men's vs women's Paris FC share a label but differ in description --
    # both are genuinely distinct candidates and must both survive.
    wd = _FakeWD(
        search={"Париж": [{"id": "QMEN"}, {"id": "QWOMEN"}]},
        entities={
            "QMEN": _with_desc(_entity("QMEN", "Paris FC", "Париж"), "football club in France"),
            "QWOMEN": _with_desc(_entity("QWOMEN", "Paris FC", "Париж"), "women's association football club"),
        },
    )
    gen = generate_candidates(wd, TermMention(surface="Париж", lemma="Париж"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["QMEN", "QWOMEN"]


def test_candidates_dedup_does_not_merge_homonyms_with_empty_descriptions():
    # Safety regression: two GENUINELY DIFFERENT entities sharing a Russian
    # label but carrying no description (a routine real-world data gap, not
    # an edge case) must never be collapsed by the dedup fix -- that's
    # exactly the ">=2 exact matches" homonym case G6's judge escalation
    # exists to disambiguate (e.g. two rulers of the same name).
    wd = _FakeWD(
        search={"Тутмос": [{"id": "Q1"}, {"id": "Q2"}]},
        entities={"Q1": _entity("Q1", "Thutmose I", "Тутмос"),
                  "Q2": _entity("Q2", "Thutmose II", "Тутмос")},
    )
    gen = generate_candidates(wd, TermMention(surface="Тутмос", lemma="Тутмос"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["Q1", "Q2"]


def test_candidates_dedup_does_not_merge_candidates_without_a_label():
    # Two label-less candidates are never collapsed together just because
    # both keys happen to be falsy -- dedup only fires on a real label match.
    wd = _FakeWD(
        search={"Тест": [{"id": "Q1"}, {"id": "Q2"}]},
        entities={"Q1": _entity("Q1", "Q1", None), "Q2": _entity("Q2", "Q2", None)},
    )
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"), GroundingConfig())
    assert [c["qid"] for c in gen["candidates"]] == ["Q1", "Q2"]


def test_grounding_judge_system_prompt_has_temporal_context_caveat():
    # DEFECT 1 fix marker: the judge must be told not to reject an enduring
    # real-world referent merely because the surrounding narrative describes
    # an earlier historical period (the root cause of the «Париж»
    # judge_rejected defect -- real trace reason: "the provided candidates
    # refer to modern entities" although Q90 IS the correct referent).
    from palimpsest.terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT
    assert "enduring real-world referent" in DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT
    assert "era mismatch" in DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT


def test_label_first_paris_class_scenario_filters_junk_and_judge_grounds_city():
    # End-to-end regression for the real defect: 5 raw hits include a
    # Wikinews-article item (must be filtered) and a near-duplicate club pair
    # (must be deduped to 1), leaving a clean candidate set that still needs
    # the judge (2 genuine exact matches on "Париж": the city + the club) --
    # the mocked judge picks the city, proving the mechanism (clean candidate
    # list reaching the judge) works, independent of any specific LLM call.
    wd = _FakeWD(
        search={"Париж": [
            {"id": "Q90"},        # Paris, the city -- the correct referent
            {"id": "QJUNK"},      # Wikinews article titled "Париж" -- filtered
            {"id": "QDUPA"},      # Paris FC (men's)
            {"id": "QDUPB"},      # identical (label_ru, description) -- deduped
            {"id": "Q830149"},    # Paris, Texas -- legitimate distinct candidate
        ]},
        entities={
            "Q90": _with_desc(_entity("Q90", "Paris", "Париж", p31=("Q515",)),
                               "capital and most populous city in France"),
            "QJUNK": _with_desc(_entity("QJUNK", "Париж", "Париж", p31=("Q17633526",)),
                                 "Wikinews article"),
            "QDUPA": _with_desc(_entity("QDUPA", "Paris FC", "Париж"), "football club in France"),
            "QDUPB": _with_desc(_entity("QDUPB", "Paris FC", "Париж"), "football club in France"),
            "Q830149": _with_desc(_entity("Q830149", "Paris, TX", "Парис"),
                                   "city in Texas, United States"),
        },
    )
    judge, calls = _judge_counter({"qid": "Q90", "reason": "modern Paris is the museum's location"})
    strategy = LabelFirstGrounding(wd)
    mention = TermMention(surface="Париж", lemma="Париж",
                           context="Конец XXIII в. до н.э. Париж, Лувр")
    result = strategy.ground(mention, judge=judge)

    trace_qids = {c["qid"] for c in result.trace["candidates"]}
    assert trace_qids == {"Q90", "QDUPA", "Q830149"}   # junk + dup never reach the trace/judge
    assert len(calls) == 1                             # 2 exact matches (Q90, QDUPA) -> escalation
    assert result.difficulty == "yellow"
    assert result.trace["resolved_by"] == "llm_disambiguation"
    assert result.grounded is not None
    assert result.grounded.qid == "Q90"
