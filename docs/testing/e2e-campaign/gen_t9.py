"""Deterministic generator for the T9 limits scenario (e2e mega-campaign).

Produces, next to itself:
  t9-ru-source.txt          exactly 40 paragraphs, paragraph #21 exactly 4000 chars
  t9-en-translation.txt     40 aligned English paragraphs
  t9-neg-41para-ru.txt /-en.txt      41 paragraphs -> must be rejected (maxParagraphs=40)
  t9-neg-4001char-ru.txt /-en.txt    one paragraph of 4001 chars -> must be rejected

No randomness: rerunning always yields byte-identical files (provenance
requirement of docs/testing/e2e-data.md).
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent

RULERS = [
    ("Саргон Аккадский", "Sargon of Akkad"), ("Нарам-Суэн", "Naram-Suen"),
    ("Ур-Намму", "Ur-Nammu"), ("Шульги", "Shulgi"), ("Хаммурапи", "Hammurabi"),
    ("Самсу-илуна", "Samsu-iluna"), ("Гудеа", "Gudea"), ("Риму́ш", "Rimush"),
]
CITIES = [
    ("Аккад", "Akkad"), ("Ур", "Ur"), ("Урук", "Uruk"), ("Лагаш", "Lagash"),
    ("Ниппур", "Nippur"), ("Мари", "Mari"), ("Эшнунна", "Eshnunna"),
    ("Сиппар", "Sippar"), ("Ларса", "Larsa"), ("Исин", "Isin"),
]


def para_ru(i: int) -> str:
    ruler_ru, _ = RULERS[i % len(RULERS)]
    city_ru, _ = CITIES[i % len(CITIES)]
    city2_ru, _ = CITIES[(i + 3) % len(CITIES)]
    return (f"Абзац {i + 1}. В правление {ruler_ru} город {city_ru} оставался "
            f"важным центром Южной Месопотамии. Писцы {city_ru} вели учёт "
            f"зерна, скота и серебра, а храмовые хозяйства обменивались "
            f"товарами с {city2_ru}. Годовые формулы этого правителя "
            f"упоминают строительство каналов и оборонительных стен.")


def para_en(i: int) -> str:
    _, ruler_en = RULERS[i % len(RULERS)]
    _, city_en = CITIES[i % len(CITIES)]
    _, city2_en = CITIES[(i + 3) % len(CITIES)]
    return (f"Paragraph {i + 1}. During the reign of {ruler_en} the city of "
            f"{city_en} remained an important center of southern Mesopotamia. "
            f"The scribes of {city_en} kept accounts of grain, livestock and "
            f"silver, while the temple estates traded with {city2_en}. The "
            f"year-names of this ruler mention the construction of canals "
            f"and defensive walls.")


def pad_to(text: str, n: int) -> str:
    filler = (" Хозяйственные таблички фиксируют выдачи ячменя работникам, "
              "поступления шерсти в храмовые склады и списки свидетелей при "
              "сделках с полями и садами.")
    while len(text) < n:
        text += filler
    return text[:n]


def main() -> None:
    ru = [para_ru(i) for i in range(40)]
    en = [para_en(i) for i in range(40)]
    ru[20] = pad_to(ru[20], 4000)          # boundary paragraph: exactly 4000 chars
    assert len(ru[20]) == 4000
    (HERE / "t9-ru-source.txt").write_text("\n\n".join(ru) + "\n", encoding="utf-8")
    (HERE / "t9-en-translation.txt").write_text("\n\n".join(en) + "\n", encoding="utf-8")

    ru41 = ru + [para_ru(40)]
    en41 = en + [para_en(40)]
    (HERE / "t9-neg-41para-ru.txt").write_text("\n\n".join(ru41) + "\n", encoding="utf-8")
    (HERE / "t9-neg-41para-en.txt").write_text("\n\n".join(en41) + "\n", encoding="utf-8")

    over = pad_to(para_ru(0), 4001)
    assert len(over) == 4001
    (HERE / "t9-neg-4001char-ru.txt").write_text(over + "\n", encoding="utf-8")
    (HERE / "t9-neg-4001char-en.txt").write_text(pad_to(para_en(0), 4001) + "\n", encoding="utf-8")
    print("t9 files written")


if __name__ == "__main__":
    main()
