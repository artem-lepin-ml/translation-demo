"""Pinned E-D6 tokenizer, shared by wiki_gt (GT side) and predict (prediction side).

See docs/superpowers/specs/2026-07-03-wiki-eval-design.md Sec.11 for the pinned
constants: BeautifulSoup(html, "lxml"); re.split(r"\\s+", ...) over
NFC+NBSP-normalized text; punctuation stays attached to its token; token
index is global (continuous across paragraphs, no per-paragraph reset).
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup
from bs4.element import Tag

_DROP_CLASS_SUBSTRINGS = ("infobox", "navbox", "reference", "mw-editsection")
_DROP_TAGS = ("table", "style", "script")

# Unicode whitespace codepoints (beyond ASCII space) that must collapse to a
# normal space before splitting, per E-D6. NBSP (U+00A0) is the common case
# in Wikipedia HTML; the rest cover the remaining Unicode Zs/format spaces.
# Built from explicit \\uXXXX escapes (never typed as literal characters) so
# the source stays unambiguous under any editor/encoding.
_UNICODE_SPACE_CODEPOINTS = "".join(
    chr(cp)
    for cp in (
        0x00A0,  # no-break space
        0x1680,  # ogham space mark
        *range(0x2000, 0x200B),  # en quad .. hair space
        0x2028,  # line separator
        0x2029,  # paragraph separator
        0x202F,  # narrow no-break space
        0x205F,  # medium mathematical space
        0x3000,  # ideographic space
        0xFEFF,  # zero width no-break space / BOM
    )
)
_UNICODE_SPACE_RE = re.compile(f"[{_UNICODE_SPACE_CODEPOINTS}]")

_SPLIT_RE = re.compile(r"\s+")


def _is_dropped(tag: Tag) -> bool:
    if tag.name in _DROP_TAGS:
        return True
    if tag.name == "sup" and "reference" in (tag.get("class") or []):
        return True
    classes = tag.get("class") or []
    class_str = " ".join(classes)
    return any(needle in class_str for needle in _DROP_CLASS_SUBSTRINGS)


def flatten(html: str) -> str:
    """Extract body `<p>` paragraph text only.

    Drops infobox/navbox/reference/table/style/script nodes before
    extraction; joins remaining paragraphs with `\\n`; normalizes to NFC and
    collapses NBSP + other Unicode spaces to a normal ASCII space.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in list(soup.find_all(True)):
        if tag.decomposed:
            continue
        if _is_dropped(tag):
            tag.decompose()

    paragraphs = [p.get_text() for p in soup.find_all("p")]

    text = "\n".join(paragraphs)
    text = unicodedata.normalize("NFC", text)
    text = _UNICODE_SPACE_RE.sub(" ", text)
    return text


def tokens(text: str) -> list[str]:
    """Split on whitespace, dropping empty tokens; punctuation stays attached."""
    return [t for t in _SPLIT_RE.split(text) if t]


def char_to_token_index(text: str, char_pos: int) -> int:
    """0-based index of the token containing/starting at char_pos, global over the whole text."""
    index = 0
    for match in _SPLIT_RE.finditer(text):
        if match.start() >= char_pos:
            break
        index += 1
    return index
