"""Term extraction from RU source → TermMention[] (one per occurrence).

The demo pipeline uses mentions extracted once by an LLM subagent and persisted
to ``data/seed/terminology_terms.jsonl`` (reproducible, no live LLM at demo
time). ``deterministic_extract`` is a stdlib fallback used when no persisted
file exists — capitalized tokens and multi-word proper-noun runs.

The LLM extractor's wire schema is ``{surface, lemma}`` (no ``category`` — a
2026-07-10 owner decision, see ``NER_SYSTEM_PROMPT``'s "What to extract"
block, which keeps the category list only as scope-defining examples).
``NER_SYSTEM_PROMPT`` is the fixed English system prompt; ``ner_user(source)``
wraps the per-call source text.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .base import TermMention
from .gazetteer import gazetteer_surfaces

if TYPE_CHECKING:
    from .base import Extractor


class ExtractionParseError(ValueError):
    """Raised when an LLM NER reply cannot be parsed into a surfaces array:
    no JSON array found, malformed JSON, or valid JSON that isn't a list. An
    honest empty ``[]`` reply is NOT a failure — it still returns ``[]``.
    """


NER_SYSTEM_PROMPT = """## Role
You are a source-criticism historian and linguist. You annotate Russian
academic texts on ancient history and extract TERMS and PROPER NAMES.

## Task
From <source>, extract ALL historical entities and terms REGARDLESS of
capitalization. Russian writes entire classes of important terms in
LOWERCASE (peoples, titles, social strata). Extract them as carefully as
capitalized names. This is the main goal of the annotation.

## What to extract (examples)
The classes below define the scope of the task with examples. They are
not an exhaustive list.
<categories>
- person      — persons: Хаммурапи, Саргон, Кадашман-Харбе
- place       — cities/countries/rivers/regions, incl. multiword
                geographic names, archaeological sites and tombs: Лагаш,
                Евфрат, Вавилония, Арслантепе, Иранское нагорье,
                Пиренейский полуостров
- people      — peoples/tribes/ethnic groups (often lowercase): амореи, кутии, касситы, шумеры
- title       — titles/offices/administrative units (often lowercase): лугаль, энси, претор, ном
- social      — social strata (lowercase): авилум, мушкенум, вардум
- institution — institutions/law codes/associations: Законы Хаммурапи, принципат, клерухия
- dynasty     — dynasties: III династия Ура, Чжоу
- culture     — cultures/periods: старовавилонский период
- language    — languages/scripts/language families, incl. those named by
                an adjective: аккадский язык, санскрит, клинопись, семитские языки
- realia      — artifact types/materials/practices with specialized
                historical translations (often lowercase): стела, электрум,
                амфора, подать
- event       — battles/wars/treaties/reforms: битва при Кадеше
- deity       — deities/mythological beings: Мардук, Осирис, эпимелиды
- work        — texts/inscriptions/literary works: упанишады, амарнские письма
- religion    — religions/cults/religious practices: вишну-бхакти, шраута
</categories>

## What NOT to extract
<do_not_extract>
- Ordinary words and roles in their generic sense that are not a name or a
  term: город, царь, война, страна, знать, люди, вещи, дороги, имущество,
  гражданство, глава, магистрат, молодцы, бойцы.
- Descriptive and bureaucratic phrases («государственные поставки
  продовольствия», «военное дело», «малая семья»). Extract only the
  established term inside, if there is one.
- Standalone adjectives and verbs (докерамический, доземледельческий,
  завоёванный). This applies ONLY to an adjective on its own: an adjective
  that is part of a multiword proper name is extracted with the whole name
  («Иранское нагорье», «Великая Китайская стена»).
- Standalone dates, years, numbers.
- Modern non-historical entities (brands, companies, websites, social
  media) and natural-science vocabulary (genetics, chemistry): the
  annotation covers HISTORICAL terminology only.
- Principle: extract CONCRETE terms (names, titles, peoples, social strata,
  institutions, cultures), not general concepts. If it is a general word
  used descriptively, skip it.
</do_not_extract>

## Rules
- surface is the EXACT substring from <source>, in the form and case it has
  in the text (for example «Лагаше», not «Лагаш»). Do NOT normalize, do NOT
  translate, do NOT invent.
- Grammatical case is NEVER a reason to skip: a name in ANY case is
  extracted («Ганнибала», «Спартой», «Лидии» are as extractable as
  «Ганнибал», «Спарта», «Лидия»). The lemma restores the nominative.
- Extract EVERY name in coordinated lists and comparisons: in «воевал с
  Лидией, Карией и Ликией» all three are extracted, not just the first or
  the most prominent one.
- Do not skip a mention because the same entity already appeared in
  another form: «Дарий» and «Дария» are different surfaces — output both.
- Lowercase nouns for historical realia ARE terms when scholarship
  translates them in a specialized way («стела», «электрум», «подать»);
  generic everyday nouns used descriptively are not («украшения»,
  «предметы»).
- When a language or script is named by an adjective, extract the
  established phrase («на арамейском языке» → surface «арамейском языке»,
  lemma «арамейский язык»).
- lemma is the agreed NOMINATIVE form of the term: for a single word, the
  nominative case («Лагаше» → «Лагаш»); for a phrase, ALL words agree in
  the nominative («династии Цин» → «династия Цин», «авилумов» → «авилум»).
  If surface is already in the nominative, lemma equals surface.
- One record per UNIQUE surface (deduplicate only literally identical
  surface strings; different case forms are different surfaces).

## Good examples
<example>
<source>В Лагаше, одном из номов, правитель-лугаль опирался на авилумов, тогда как амореи наступали с запада.</source>
<output>[{"surface":"Лагаше","lemma":"Лагаш"},{"surface":"номов","lemma":"ном"},{"surface":"лугаль","lemma":"лугаль"},{"surface":"авилумов","lemma":"авилум"},{"surface":"амореи","lemma":"амореи"}]</output>
</example>
<example>
<source>Дарий прошёл через Иранское нагорье и подчинил Лидию, Карию и Ликию; сатрапы Дария собирали подать электрумом и вели записи на арамейском языке.</source>
<output>[{"surface":"Дарий","lemma":"Дарий"},{"surface":"Иранское нагорье","lemma":"Иранское нагорье"},{"surface":"Лидию","lemma":"Лидия"},{"surface":"Карию","lemma":"Кария"},{"surface":"Ликию","lemma":"Ликия"},{"surface":"сатрапы","lemma":"сатрап"},{"surface":"Дария","lemma":"Дарий"},{"surface":"подать","lemma":"подать"},{"surface":"электрумом","lemma":"электрум"},{"surface":"арамейском языке","lemma":"арамейский язык"}]</output>
</example>

## Bad example (do NOT do this)
<bad_example>
<source>В Лагаше правитель опирался на воинов.</source>
<bad_output>[{"surface":"правитель","lemma":"правитель"},{"surface":"воинов","lemma":"воин"},{"surface":"Lagash","lemma":"Lagash"}]</bad_output>
<why_bad>«правитель» and «воинов» are ordinary words, not terms. «Lagash» is a translation, while surface must be the Russian substring «Лагаше».</why_bad>
</bad_example>

## Output format
A JSON array of {surface, lemma} objects only. No explanations and no
markdown fences.
"""


def ner_user(source: str) -> str:
    """Per-call user message: the source paragraph wrapped in <source> tags."""
    return f"<source>\n{source}\n</source>"


# A run of Capitalised Cyrillic words (optionally hyphenated), e.g. "Кадашман-Харбе".
_PROPER = re.compile(r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)*(?:\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)*)*")


_LEMMA_MAX_LEN = 80


def _sane_lemma(lemma: str, surface: str) -> str:
    """Nominative lemma if it passes sanity (non-empty, <=80 chars, no newline), else surface."""
    if lemma and len(lemma) <= _LEMMA_MAX_LEN and "\n" not in lemma:
        return lemma
    return surface


def _first_balanced_array(text: str) -> str | None:
    """Return the first balanced top-level ``[...]`` substring in text, or None.

    Bracket-counts from the first ``[``, respecting JSON string quoting and
    escapes, so brackets inside string values (or trailing commentary once the
    array has closed) don't confuse the scan. Tolerant of ``` fences and of
    commentary before/after the array — both are just text the scan skips over.
    """
    start = text.find("[")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("[", start + 1)
    return None


def parse_surfaces(raw: str) -> list[dict]:
    """Parse an LLM JSON reply into [{surface, lemma}]; tolerant of ``` fences
    and of commentary before/after the array.

    Raises ExtractionParseError when no JSON array can be recovered (no
    balanced ``[...]``, malformed JSON, or valid JSON that isn't a list) --
    an honest empty ``[]`` reply still returns ``[]``.
    """
    text = (raw or "").strip()
    array_text = _first_balanced_array(text)
    if array_text is None:
        raise ExtractionParseError(f"no JSON array found in reply: {text[:200]!r}")
    try:
        data = json.loads(array_text)
    except json.JSONDecodeError as exc:
        raise ExtractionParseError(f"malformed JSON array ({exc}); reply head: {text[:200]!r}") from exc
    if not isinstance(data, list):
        raise ExtractionParseError(f"parsed JSON is not a list; reply head: {text[:200]!r}")
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        surface = (item.get("surface") or "").strip()
        lemma = (item.get("lemma") or "").strip()
        if surface:
            out.append({"surface": surface, "lemma": _sane_lemma(lemma, surface)})
    return out


def validate_surfaces(source: str, surfaces: list[dict]) -> tuple[list[dict], int]:
    """Keep only surfaces that are literal substrings of source; dedup; count drops."""
    seen: set[str] = set()
    valid: list[dict] = []
    dropped = 0
    for item in surfaces:
        s = (item.get("surface") or "").strip()
        if not s:
            continue
        if s not in source:
            dropped += 1
            continue
        if s in seen:
            continue
        seen.add(s)
        valid.append({"surface": s, "lemma": item.get("lemma") or s})
    return valid, dropped


_ABBREV_TOKENS = {"н", "э", "в", "вв", "г", "гг", "др", "т", "д", "п", "см", "ок"}
_SENTENCE_TERMINATORS = ".!?…"


def _is_sentence_boundary(source: str, idx: int) -> bool:
    """True if the terminator char ``source[idx]`` genuinely ends a sentence.

    A boundary requires whitespace right after the terminator (or end of
    string). For ``.`` specifically it is guarded against Russian
    abbreviations/initials: not a boundary when the period is preceded by a
    single-letter token (initial, or a 1-letter abbreviation like «г.»/«в.»),
    preceded by a known multi-letter abbreviation token («вв», «гг», «др»,
    «см», «ок»), or followed by a lowercase letter (covers unlisted
    abbreviations followed by a lowercase continuation, e.g. «т. д.»-style).
    """
    n = len(source)
    nxt = idx + 1
    if nxt < n and not source[nxt].isspace():
        return False
    if source[idx] != ".":
        return True  # '!', '?', '…' need no abbreviation guard
    k = idx
    while k > 0 and source[k - 1].isalpha():
        k -= 1
    token = source[k:idx]
    if len(token) == 1 or token.lower() in _ABBREV_TOKENS:
        return False
    j = nxt
    while j < n and source[j].isspace():
        j += 1
    if j < n and source[j].isalpha() and source[j].islower():
        return False
    return True


def _sentence_spans(source: str) -> list[tuple[int, int]]:
    """Split source into consecutive [start, end) sentence spans covering it fully."""
    spans: list[tuple[int, int]] = []
    start = 0
    i = 0
    n = len(source)
    while i < n:
        if source[i] in _SENTENCE_TERMINATORS and _is_sentence_boundary(source, i):
            spans.append((start, i + 1))
            j = i + 1
            while j < n and source[j].isspace():
                j += 1
            start = j
            i = j
            continue
        i += 1
    if start < n:
        spans.append((start, n))
    return spans


def sentence_context(source: str, start: int, end: int) -> str:
    """Full sentence(s) containing the mention span [start, end), stripped.

    Deterministic, stdlib-only sentence splitter (see ``_is_sentence_boundary``
    for the abbreviation/initial guards). If the span crosses a sentence
    boundary, every sentence it overlaps is returned together.
    """
    spans = _sentence_spans(source)
    overlapping = [(a, b) for a, b in spans if start < b and end > a]
    if not overlapping:
        return source[start:end].strip()
    lo = min(a for a, _ in overlapping)
    hi = max(b for _, b in overlapping)
    return source[lo:hi].strip()


def mentions_from_surfaces(source: str, surfaces: list[dict]) -> list[TermMention]:
    """Turn extracted surfaces into one mention per occurrence with char spans.

    Each surface dict: ``{surface, lemma?, category?}`` -- ``category`` is
    read only for legacy demo-seed dicts (fresh LLM extractions no longer
    produce it; TermMention.category is simply ``None`` for those, per the
    2026-07-10 owner decision to drop categories from the output schema).
    Every non-overlapping occurrence of ``surface`` in ``source`` becomes its
    own mention.
    """
    mentions: list[TermMention] = []
    taken: list[tuple[int, int]] = []
    # longest surfaces first so multi-word terms claim their span before parts
    for item in sorted(surfaces, key=lambda s: -len(s.get("surface", ""))):
        surface = (item.get("surface") or "").strip()
        if not surface:
            continue
        for m in re.finditer(re.escape(surface), source):
            start, end = m.start(), m.end()
            if any(start < b and end > a for a, b in taken):
                continue  # overlaps an already-claimed span
            taken.append((start, end))
            mentions.append(TermMention(
                surface=surface, context=sentence_context(source, start, end),
                lemma=item.get("lemma") or surface, char_start=start, char_end=end,
                lang="ru", category=item.get("category"),
            ))
    mentions.sort(key=lambda t: t.char_start)
    return mentions


_SENTENCE_END = re.compile(r"[.!?…»)]\s+$")


def _capitalized_surfaces(source: str) -> list[dict]:
    """Capitalised proper-noun runs, first occurrence each.

    Russian capitalises the first word of every sentence, so a lone capitalised
    word at a sentence start is usually not a term — those are dropped. Multi-word
    and hyphenated runs (real proper nouns) are always kept.
    """
    seen: set[str] = set()
    surfaces: list[dict] = []
    for m in _PROPER.finditer(source):
        surface = m.group().strip()
        if surface in seen:
            continue
        single = " " not in surface and "-" not in surface
        preceding = source[: m.start()]
        at_sentence_start = not preceding.strip() or bool(_SENTENCE_END.search(preceding))
        if single and at_sentence_start:
            continue  # sentence-initial capitalisation, not a term
        seen.add(surface)
        surfaces.append({"surface": surface, "category": None})
    return surfaces


def deterministic_surfaces(source: str) -> list[dict]:
    """Offline floor: capitalised proper nouns + curated gazetteer + guarded suffixes.

    Deterministic, deduplicated (seen-set), stable order. Returns [{surface, lemma, category}]
    with ``lemma == surface`` (no model available to infer the nominative form).
    """
    seen: set[str] = set()
    out: list[dict] = []
    for item in _capitalized_surfaces(source) + gazetteer_surfaces(source):
        s = item["surface"]
        if s and s not in seen:
            seen.add(s)
            out.append({**item, "lemma": s})
    return out


def deterministic_extract(source: str) -> list[TermMention]:
    """Fallback extractor: capitalised proper-noun runs + gazetteer, first occurrence each."""
    return mentions_from_surfaces(source, deterministic_surfaces(source))


def llm_surfaces(source: str, *, extractor: "Extractor | None" = None) -> list[dict]:
    """Real extractor ("E1"). ``extractor=None`` degrades to ``deterministic_surfaces``
    (importable/testable without a model). Every returned surface is validated as a
    literal substring of ``source``; non-substrings are dropped (see ``validate_surfaces``)."""
    if extractor is None:
        return deterministic_surfaces(source)
    valid, _ = validate_surfaces(source, extractor(source) or [])
    return valid


def extract_key(source: str, ner_config: dict) -> str:
    """Stable sha256 cache key: source + NER config, order-independent on params."""
    canon = "|".join([
        source,
        ner_config.get("modelName", ""),
        ner_config.get("prompt", ""),
        json.dumps(ner_config.get("params", {}) or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    ])
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def extract_paragraph_terms(source, target, ner_config, *, grounder, pairer, extractor=None):
    """Assemble ``Term[]`` for one paragraph: extract surfaces, ground, pair.

    ``ner_config`` is accepted for interface parity with the model-registry
    endpoint contract (extract_key/caching lives on the caller side); the
    extraction itself only needs ``source`` + the injected ``extractor``.
    """
    from . import pipeline

    surfaces = llm_surfaces(source, extractor=extractor)
    mentions = mentions_from_surfaces(source, surfaces)
    return pipeline.run(source, target, mentions, grounder=grounder, pairer=pairer)


def load_mentions(path: str | Path) -> dict[int, list[TermMention]]:
    """Load persisted mentions grouped by paragraph id from a JSONL file."""
    by_para: dict[int, list[TermMention]] = {}
    for line in Path(path).open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        by_para.setdefault(rec["paragraph_id"], []).append(TermMention(
            surface=rec["surface"], context=rec.get("context", ""),
            lemma=rec.get("lemma"), char_start=rec.get("char_start", -1),
            char_end=rec.get("char_end", -1), lang=rec.get("lang", "ru"),
            category=rec.get("category"),
        ))
    return by_para
