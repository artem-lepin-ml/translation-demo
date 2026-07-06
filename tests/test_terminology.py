"""Unit tests for the terminology module: verdict logic, extraction, pipeline null rule."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import pipeline
from palimpsest.terminology.base import GroundingResult, PairResult, TermMention, WikidataRef
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


def test_categories_and_prompt_present():
    from palimpsest.terminology.extract import CATEGORIES, DEFAULT_NER_PROMPT
    assert {"people", "title", "social"} <= CATEGORIES
    assert "{{source}}" in DEFAULT_NER_PROMPT
    assert "<categories>" in DEFAULT_NER_PROMPT and "bad_example" in DEFAULT_NER_PROMPT


def test_parse_surfaces_tolerates_fence_and_bad_category():
    from palimpsest.terminology.extract import parse_surfaces
    raw = '```json\n[{"surface":"Лагаше","category":"place"},{"surface":"x","category":"nonsense"}]\n```'
    out = parse_surfaces(raw)
    assert out[0] == {"surface": "Лагаше", "lemma": "Лагаше", "category": "place"}
    assert out[1]["category"] is None            # unknown category -> None
    assert parse_surfaces("not json") == []


def test_parse_surfaces_includes_lemma():
    from palimpsest.terminology.extract import parse_surfaces
    raw = '[{"surface":"династии Цин","lemma":"династия Цин","category":"dynasty"}]'
    out = parse_surfaces(raw)
    assert out == [{"surface": "династии Цин", "lemma": "династия Цин", "category": "dynasty"}]


def test_parse_surfaces_lemma_sanity_falls_back_to_surface():
    from palimpsest.terminology.extract import parse_surfaces
    raw = json.dumps([
        {"surface": "Лагаше", "lemma": "", "category": "place"},
        {"surface": "Вавилон", "lemma": "x" * 81, "category": "place"},
        {"surface": "Ниппур", "lemma": "Ниппур\nс переносом", "category": "place"},
    ], ensure_ascii=False)
    out = parse_surfaces(raw)
    assert [o["lemma"] for o in out] == ["Лагаше", "Вавилон", "Ниппур"]  # sanity fails -> lemma=surface


def test_validate_surfaces_drops_not_in_source_and_dedups():
    from palimpsest.terminology.extract import validate_surfaces
    src = "В Лагаше правил лугаль. Лагаше славился."
    surfaces = [{"surface":"Лагаше","category":"place"},{"surface":"Лагаше","category":"place"},
                {"surface":"Lagash","category":"place"},{"surface":"","category":None}]
    valid, dropped = validate_surfaces(src, surfaces)
    assert [v["surface"] for v in valid] == ["Лагаше"]   # deduped, only substring
    assert dropped == 1                                   # "Lagash" not in source


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
    got = {v["surface"] for v in llm_surfaces(src, extractor=fake)}
    assert got == {"лугаль"}                     # hallucinated "Lagash" dropped


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
