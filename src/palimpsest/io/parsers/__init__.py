"""Registry of PDF parsers. Heavy ML deps (docling, mineru) are lazy-imported
so that `uv sync` without optional extras still works on a plain Mac."""
from __future__ import annotations

from importlib import import_module

from .base import PDFParser, ParseResult

_REGISTRY: dict[str, str] = {
    "pymupdf": "palimpsest.io.parsers.pymupdf:PyMuPDFParser",
    "docling": "palimpsest.io.parsers.docling:DoclingParser",
    "mineru": "palimpsest.io.parsers.mineru:MinerUParser",
}


def get_parser(name: str) -> PDFParser:
    if name not in _REGISTRY:
        raise KeyError(f"unknown parser {name!r}; available: {available_parsers()}")
    module_path, cls_name = _REGISTRY[name].split(":")
    return getattr(import_module(module_path), cls_name)()


def available_parsers() -> list[str]:
    return list(_REGISTRY)


__all__ = ["PDFParser", "ParseResult", "get_parser", "available_parsers"]
