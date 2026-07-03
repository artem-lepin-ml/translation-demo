"""Tests for the E-D6 pinned tokenizer: flatten, tokens, char_to_token_index."""
from __future__ import annotations

from palimpsest.terminology.evaluation.tokenize import (
    char_to_token_index,
    flatten,
    tokens,
)

FIXTURE_HTML = """
<html>
<body>
<table class="infobox"><tr><td>Infobox junk should not appear</td></tr></table>
<p>Первое предложение  о истории Рима, древнего города.</p>
<p>Второе предложение о падении империи.</p>
</body>
</html>
"""

EXPECTED_TOKENS = [
    "Первое",
    "предложение",
    "о",
    "истории",
    "Рима,",
    "древнего",
    "города.",
    "Второе",
    "предложение",
    "о",
    "падении",
    "империи.",
]


def test_tokens_of_flatten_matches_expected_list():
    text = flatten(FIXTURE_HTML)
    assert tokens(text) == EXPECTED_TOKENS


def test_flatten_normalizes_nbsp_to_ascii_space():
    text = flatten(FIXTURE_HTML)
    assert " " not in text


def test_tokens_collapses_multiple_spaces():
    # flatten() only normalizes NBSP/Unicode spaces (E-D6); ordinary
    # whitespace runs are collapsed by tokens()'s re.split(r"\s+").
    text = flatten(FIXTURE_HTML)
    assert "  " in text  # the fixture's double space survives flatten()
    assert all("  " not in tok for tok in tokens(text))


def test_flatten_joins_paragraphs_with_newline():
    text = flatten(FIXTURE_HTML)
    paragraphs = text.split("\n")
    assert len(paragraphs) == 2
    assert paragraphs[0].startswith("Первое предложение")
    assert paragraphs[1].startswith("Второе предложение")


def test_flatten_drops_infobox_text():
    text = flatten(FIXTURE_HTML)
    assert "Infobox junk" not in text
    assert "infobox" not in text.lower()


def test_flatten_drops_navbox_reference_and_edit_section_nodes():
    html = """
    <html><body>
    <div class="navbox">Navbox junk</div>
    <div class="mw-editsection">edit</div>
    <sup class="reference">[1]</sup>
    <p>Настоящий текст статьи.</p>
    </body></html>
    """
    text = flatten(html)
    assert "Navbox junk" not in text
    assert "edit" not in text
    assert "[1]" not in text
    assert text.strip() == "Настоящий текст статьи."


def test_flatten_drops_style_and_script_nodes():
    html = """
    <html><body>
    <style>.foo { color: red; }</style>
    <script>alert('x')</script>
    <p>Обычный абзац.</p>
    </body></html>
    """
    text = flatten(html)
    assert "color" not in text
    assert "alert" not in text
    assert text.strip() == "Обычный абзац."


def test_tokens_drops_empty_tokens():
    assert tokens("  a   b  ") == ["a", "b"]


def test_tokens_keeps_punctuation_attached():
    assert tokens("Рима, древнего города.") == ["Рима,", "древнего", "города."]


def test_char_to_token_index_round_trips_first_token():
    text = flatten(FIXTURE_HTML)
    assert char_to_token_index(text, 0) == 0


def test_char_to_token_index_round_trips_known_offset():
    text = flatten(FIXTURE_HTML)
    target_token = "Рима,"
    idx = tokens(text).index(target_token)
    char_pos = text.index(target_token)
    assert char_to_token_index(text, char_pos) == idx


def test_char_to_token_index_is_global_across_paragraph_boundary():
    text = flatten(FIXTURE_HTML)
    target_token = "падении"
    idx = tokens(text).index(target_token)
    char_pos = text.index(target_token)
    assert idx >= len(tokens(text.split("\n")[0]))
    assert char_to_token_index(text, char_pos) == idx
