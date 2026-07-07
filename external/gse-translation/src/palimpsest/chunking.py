"""Chunking strategies for Stage 01 (request batching).

A chunk is a half-open paragraph range expressed as inclusive
[left, right] in 0-indexed paragraph IDs (= line numbers in
pilot_original.md). Each strategy returns a dict
{request_id_str: [left, right]} with sequential string keys
starting at "0".
"""
from __future__ import annotations

import json
from pathlib import Path


Chunks = dict[str, list[int]]


def par_by_par(total_lines: int) -> Chunks:
    """One paragraph per request."""
    return {str(i): [i, i] for i in range(total_lines)}


def by_chapter(chapter_starts: list[int], total_lines: int) -> Chunks:
    """One request per chapter. `chapter_starts` is sorted, 0-indexed."""
    return _starts_to_chunks(chapter_starts, total_lines)


def by_subchapter(subchapter_starts: list[int], total_lines: int) -> Chunks:
    """One request per subchapter. `subchapter_starts` is the flat list
    of all subchapter starts across all chapters, sorted, 0-indexed."""
    return _starts_to_chunks(subchapter_starts, total_lines)


def by_k_par(k: int, chapter_starts: list[int], total_lines: int) -> Chunks:
    """K paragraphs per request, never crossing a chapter boundary.

    Each chapter is split independently into chunks of size `k`. The
    last chunk of every chapter is truncated to the chapter end (so
    chunks at chapter tails are <= k paragraphs).
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    chapter_ends = [s - 1 for s in chapter_starts[1:]] + [total_lines - 1]
    chunks: Chunks = {}
    request_id = 0
    for c_start, c_end in zip(chapter_starts, chapter_ends):
        offset = c_start
        while offset <= c_end:
            chunk_end = min(offset + k - 1, c_end)
            chunks[str(request_id)] = [offset, chunk_end]
            request_id += 1
            offset = chunk_end + 1
    return chunks


def _starts_to_chunks(starts: list[int], total_lines: int) -> Chunks:
    ends = [s - 1 for s in starts[1:]] + [total_lines - 1]
    return {str(i): [s, e] for i, (s, e) in enumerate(zip(starts, ends))}


def dump_chunks(chunks: Chunks, path: Path) -> None:
    """Write a chunk dict as JSON with one item per line.

    Standard json.dump(indent=2) explodes [left, right] onto three
    lines per entry. Hand-roll the format so each request fits on a
    single line for human-readable diffs.
    """
    items = list(chunks.items())
    lines = ["{"]
    for i, (k, v) in enumerate(items):
        sep = "," if i < len(items) - 1 else ""
        lines.append(f'  "{k}": {json.dumps(v)}{sep}')
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
