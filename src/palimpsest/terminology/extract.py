"""Term extraction from RU source → TermMention[] (one per occurrence).

The demo pipeline uses mentions extracted once by an LLM subagent and persisted
to ``data/seed/terminology_terms.jsonl`` (reproducible, no live LLM at demo
time). ``deterministic_extract`` is a stdlib fallback used when no persisted
file exists — capitalized tokens and multi-word proper-noun runs.
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

CATEGORIES = {"person", "place", "people", "title", "social", "institution", "dynasty", "culture", "event"}

DEFAULT_NER_PROMPT = """## Роль
Ты — историк-источниковед и лингвист. Ты размечаешь русский академический
исторический текст (Древний мир: Египет, Месопотамия, античность, Древний
Китай/Индия) и извлекаешь ТЕРМИНЫ и ИМЕНА СОБСТВЕННЫЕ, чей перевод на английский
стоит проверить.

## Задача
Из <source> извлеки ВСЕ исторические сущности-термины ВНЕ зависимости от регистра.
Русский пишет СТРОЧНЫМИ целые классы важных терминов (народы, титулы, соц. слои) —
извлекай их так же тщательно, как имена с заглавной. Это главная цель разметки.

## Категории
<categories>
- person      — лица: Хаммурапи, Саргон, Кадашман-Харбе
- place       — города/страны/реки/области: Лагаш, Евфрат, Вавилония
- people      — народы/племена/этносы (ЧАСТО строчные): амореи, кутии, касситы, шумеры
- title       — титулы/должности/адм. единицы (ЧАСТО строчные): лугаль, энси, претор, ном
- social      — социальные слои (строчные): авилум, мушкенум, вардум
- institution — институты/своды законов/объединения: Законы Хаммурапи, принципат, клерухия
- dynasty     — династии: III династия Ура, Чжоу
- culture     — культуры/периоды: старовавилонский период
- event       — битвы/войны/договоры/реформы: битва при Кадеше
</categories>

## Чего НЕ извлекать
<do_not_extract>
- Обычные слова и роли в общем смысле, не являющиеся именем/термином: город, царь, война,
  страна, знать, люди, вещи, дороги, имущество, гражданство, глава, магистрат, молодцы, бойцы.
- Описательные и бюрократические словосочетания («государственные поставки продовольствия»,
  «военное дело», «малая семья») — извлекай только устойчивый термин внутри, если он есть.
- Отдельные прилагательные и глаголы (докерамический, доземледельческий, завоёванный).
- Отдельные даты/годы/числа.
- Принцип: извлекай КОНКРЕТНЫЕ термины (имена, титулы, народы, соц. слои, институты, культуры),
  а не общие понятия. Если это общее слово в описательном смысле — пропусти.
</do_not_extract>

## Правила
- surface — ТОЧНАЯ подстрока из <source>, в той форме и падеже, как в тексте
  (например «Лагаше», а не «Лагаш»). НЕ нормализуй, НЕ переводи, НЕ придумывай.
- lemma — согласованная ИМЕНИТЕЛЬНАЯ форма термина: для одного слова — именительный
  падеж («Лагаше» → «Лагаш»); для словосочетания — ВСЕ слова согласуются в
  именительном («династии Цин» → «династия Цин», «авилумов» → «авилум»).
  Если surface уже стоит в именительном падеже — lemma совпадает с surface
  («Лагаш» → lemma «Лагаш»).
- Одна запись на каждый УНИКАЛЬНЫЙ surface (повторы не дублируй).

## Хороший пример
<example>
<source>В Лагаше, одном из номов, правитель-лугаль опирался на авилумов, тогда как амореи наступали с запада.</source>
<output>[{"surface":"Лагаше","lemma":"Лагаш","category":"place"},{"surface":"номов","lemma":"ном","category":"title"},{"surface":"лугаль","lemma":"лугаль","category":"title"},{"surface":"авилумов","lemma":"авилум","category":"social"},{"surface":"амореи","lemma":"амореи","category":"people"}]</output>
</example>

## Плохой пример (так НЕ делать)
<bad_example>
<source>В Лагаше правитель опирался на воинов.</source>
<bad_output>[{"surface":"правитель","lemma":"правитель","category":"title"},{"surface":"воинов","lemma":"воин","category":"people"},{"surface":"Lagash","lemma":"Lagash","category":"place"}]</bad_output>
<why_bad>«правитель»/«воинов» — обычные слова, не термины; «Lagash» — перевод, а surface обязан быть русской подстрокой «Лагаше».</why_bad>
</bad_example>

## Формат вывода
Только JSON-массив объектов {surface, lemma, category}. Без пояснений и без markdown-ограды.

<source>
{{source}}
</source>
"""

CONTEXT_PAD = 40
# A run of Capitalised Cyrillic words (optionally hyphenated), e.g. "Кадашман-Харбе".
_PROPER = re.compile(r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)*(?:\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)*)*")


def _context(source: str, start: int, end: int) -> str:
    return source[max(0, start - CONTEXT_PAD): end + CONTEXT_PAD].strip()


_LEMMA_MAX_LEN = 80


def _sane_lemma(lemma: str, surface: str) -> str:
    """Nominative lemma if it passes sanity (non-empty, <=80 chars, no newline), else surface."""
    if lemma and len(lemma) <= _LEMMA_MAX_LEN and "\n" not in lemma:
        return lemma
    return surface


def parse_surfaces(raw: str) -> list[dict]:
    """Parse an LLM JSON reply into [{surface, lemma, category}]; tolerant of ``` fences."""
    text = (raw or "").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[dict] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        surface = (item.get("surface") or "").strip()
        category = (item.get("category") or "").strip()
        lemma = (item.get("lemma") or "").strip()
        if surface:
            out.append({
                "surface": surface,
                "lemma": _sane_lemma(lemma, surface),
                "category": category if category in CATEGORIES else None,
            })
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
        valid.append({"surface": s, "lemma": item.get("lemma") or s, "category": item.get("category")})
    return valid, dropped


def mentions_from_surfaces(source: str, surfaces: list[dict]) -> list[TermMention]:
    """Turn extracted surfaces into one mention per occurrence with char spans.

    Each surface dict: ``{surface, lemma?, category?}``. Every non-overlapping
    occurrence of ``surface`` in ``source`` becomes its own mention.
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
                surface=surface, context=_context(source, start, end),
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
