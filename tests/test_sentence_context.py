"""Unit tests for extract.sentence_context: full-sentence judge context (spec
2026-07-10-wiki-eval-experiment-v2.md Р4/§4.3). CONTEXT_PAD/_context() are gone;
this is the deterministic stdlib-only replacement.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimpsest.terminology.extract import sentence_context


def test_mention_mid_paragraph_gets_exactly_its_full_sentence():
    source = "Первое предложение здесь. Саргон правил Аккадом уверенно. Третье предложение тут."
    start = source.index("Саргон")
    end = start + len("Саргон")
    assert sentence_context(source, start, end) == "Саргон правил Аккадом уверенно."


def test_do_n_e_abbreviation_does_not_split_sentence():
    source = "Событие произошло в 3200 году до н. э. и изменило историю региона. Позже всё изменилось."
    start = source.index("региона")
    end = start + len("региона")
    assert sentence_context(source, start, end) == (
        "Событие произошло в 3200 году до н. э. и изменило историю региона."
    )


def test_v_do_n_e_style_combo_does_not_split_sentence():
    source = "Это случилось в 5 в. до н. э. в Афинах. Другое событие описано позже."
    start = source.index("Афинах")
    end = start + len("Афинах")
    assert sentence_context(source, start, end) == "Это случилось в 5 в. до н. э. в Афинах."


def test_initials_not_split():
    source = "Об этом писал А. С. Пушкин в своих заметках. Мы рассмотрим это ниже."
    start = source.index("Пушкин")
    end = start + len("Пушкин")
    assert sentence_context(source, start, end) == "Об этом писал А. С. Пушкин в своих заметках."


def test_mention_in_first_sentence_of_paragraph():
    source = "Первое предложение здесь. Второе предложение тут. Третье предложение там."
    start = source.index("Первое")
    end = start + len("Первое")
    assert sentence_context(source, start, end) == "Первое предложение здесь."


def test_mention_in_last_sentence_of_paragraph():
    source = "Первое предложение здесь. Второе предложение тут. Третье предложение там."
    start = source.index("там")
    end = start + len("там")
    assert sentence_context(source, start, end) == "Третье предложение там."


def test_mention_spanning_sentence_boundary_returns_both_sentences():
    source = "Первое. Второе."
    # span deliberately straddles the period between the two sentences
    start = source.index("рвое")
    end = source.index("торое") + len("торое")
    assert sentence_context(source, start, end) == "Первое. Второе."


def test_single_sentence_paragraph_without_trailing_period():
    source = "Это единственное предложение без точки"
    start = source.index("предложение")
    end = start + len("предложение")
    assert sentence_context(source, start, end) == source
