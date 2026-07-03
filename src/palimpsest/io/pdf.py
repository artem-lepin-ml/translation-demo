"""Post-processing helpers for parser markdown output."""
from __future__ import annotations

import re

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_images_to_placeholder(markdown: str) -> str:
    """Replace Markdown image refs with `<picture>` placeholders.

    Used before paragraph-splitting so that image blocks don't become paragraphs.
    """
    return _IMAGE_RE.sub("<picture>", markdown)
