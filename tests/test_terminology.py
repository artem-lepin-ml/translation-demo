"""Unit tests for the terminology module: verdict logic, extraction, pipeline null rule."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology import pipeline
from palimpsest.terminology.base import GroundingResult, PairResult, TermMention, WikidataRef
from palimpsest.terminology.extract import deterministic_extract, mentions_from_surfaces
from palimpsest.terminology.verdict import (
    difficulty_from_candidates,
    pair_from_forms,
    passes_type_filter,
)
from palimpsest.terminology.wikidata import canonical_en_forms


# ── type filter ───────────────────────────────────────────────────────────────
def test_type_filter_keeps_human_drops_football_club():
    assert passes_type_filter(["Q5"]) is True
    assert passes_type_filter(["Q476028"]) is False       # association football club
    assert passes_type_filter(["Q4167410"]) is False      # disambiguation
    assert passes_type_filter(["Q13442814"]) is False      # scholarly article


# ── difficulty verdict ────────────────────────────────────────────────────────
def test_difficulty_red_when_no_candidates():
    d, g, c = difficulty_from_candidates(["любой"], [])
    assert d == "red" and g is None and c == []


def test_difficulty_green_single_exact():
    cands = [{"qid": "Q11767", "label": "Mesopotamia", "aliases": ["Месопотамия"], "types": ["Q1620908"]}]
    d, g, _ = difficulty_from_candidates(["Месопотамия", "Месопотамия"], cands)
    assert d == "green" and g.qid == "Q11767"


def test_difficulty_yellow_two_exact_homonyms():
    # yellow requires ≥2 *notable* (enwiki-sitelinked) candidates that exact-match
    cands = [
        {"qid": "Q1", "label": "Ур", "aliases": [], "types": ["Q515"], "notable": True},
        {"qid": "Q2", "label": "Ур", "aliases": [], "types": ["Q515"], "notable": True},
    ]
    d, _, _ = difficulty_from_candidates(["Ур"], cands)
    assert d == "yellow"


def test_difficulty_green_when_second_namesake_not_notable():
    # a minor (non-notable) namesake must NOT trigger yellow
    cands = [
        {"qid": "Q1", "label": "Ур", "aliases": [], "types": ["Q515"], "notable": True},
        {"qid": "Q2", "label": "Ур", "aliases": [], "types": ["Q515"], "notable": False},
    ]
    d, _, _ = difficulty_from_candidates(["Ур"], cands)
    assert d == "green"


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
    assert out[0] == {"surface": "Лагаше", "category": "place"}
    assert out[1]["category"] is None            # unknown category -> None
    assert parse_surfaces("not json") == []


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
    """difficulty by surface prefix: 'RED*' → red, else green."""
    name = "fake"

    def ground(self, mention, *, judge=None):
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


# ── grounding strategies (fake Wikidata client) ───────────────────────────────
from palimpsest.terminology.grounding import ApiFirstGrounding, HybridGrounding, LlmJudgeGrounding
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
    gen = generate_candidates(wd, TermMention(surface="Саргона", lemma="Саргона"))
    assert gen["source"] == "cirrus"
    assert [c["qid"] for c in gen["candidates"]] == ["Q199461"]


def test_candidates_wikipedia_langlink_last_resort():
    # prefix + CirrusSearch both miss → RU Wikipedia title → Wikidata item recovers it
    wd = _FakeWD(search={}, cirrus={},
                 wiki={"Урукагина": "Q312060"},
                 entities={"Q312060": _entity("Q312060", "Urukagina", "Урукагина", p31=("Q5",), enwiki="Urukagina")})
    gen = generate_candidates(wd, TermMention(surface="Уруинимгину", lemma="Урукагина"))
    assert gen["source"] == "wikipedia_langlink"
    assert [c["qid"] for c in gen["candidates"]] == ["Q312060"]


def test_candidates_redirect_canonicalized_to_target_qid():
    # search returns a redirect id; the enriched entity carries the canonical id
    wd = _FakeWD(search={"Тест": [{"id": "Q_OLD"}]},
                 entities={"Q_OLD": _entity("Q_CANON", "Test", "Тест", p31=("Q5",), enwiki="Test")})
    gen = generate_candidates(wd, TermMention(surface="Тест", lemma="Тест"))
    assert gen["candidates"][0]["qid"] == "Q_CANON"   # not the pre-redirect Q_OLD


def _api_green_fixture():
    # Q1 is the exact, notable sense; Q2 is a lower-ranked non-exact candidate
    return _FakeWD(
        search={"Тест": [{"id": "Q1"}, {"id": "Q2"}]},
        entities={
            "Q1": _entity("Q1", "Test", "Тест", p31=("Q5",), enwiki="Test"),
            "Q2": _entity("Q2", "Other", "Другое", p31=("Q5",)),
        },
    )


def test_hybrid_degrades_to_api_first_without_judge():
    wd = _api_green_fixture()
    m = TermMention(surface="Тест", lemma="Тест")
    a = ApiFirstGrounding(wd).ground(m)
    h = HybridGrounding(wd).ground(m, judge=None)
    assert h.difficulty == a.difficulty == "green"
    assert h.grounded.qid == a.grounded.qid == "Q1"
    assert h.trace["grounded_from"] == "api_first"


def test_hybrid_keeps_api_difficulty_swaps_judge_qid():
    wd = _api_green_fixture()
    m = TermMention(surface="Тест", lemma="Тест")
    # judge resolves a different (non-red) entity; api_first rated the difficulty green
    judge = lambda prompt: {"qid": "Q2", "difficulty": "yellow"}
    h = HybridGrounding(wd).ground(m, judge=judge)
    assert h.difficulty == "green"          # difficulty stays api_first's, not the judge's "yellow"
    assert h.grounded.qid == "Q2"           # QID swapped to the judge's pick
    assert h.trace["grounded_from"] == "llm_judge"


def test_hybrid_red_short_circuits_without_calling_judge():
    wd = _FakeWD(search={}, cirrus={})       # nothing found → api_first red
    called = []
    judge = lambda prompt: called.append(1) or {"qid": "Q9", "difficulty": "green"}
    h = HybridGrounding(wd).ground(TermMention(surface="Ничто", lemma="Ничто"), judge=judge)
    assert h.difficulty == "red" and h.grounded is None
    assert called == []                      # judge never invoked on a red term
