"""Mode B Stage-2 paragraph-flat translator.

Reads a markdown file (one paragraph per line), translates each non-picture
paragraph independently via LLMClient, writes a 1:1 line-aligned EN file.
The translate_per_paragraph function is the importable core; scripts/02_translate.py is
a thin typer CLI on top.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from tqdm.asyncio import tqdm

from .llm.client import LLMClient
from .paths import PROMPTS

_TAG_RE = re.compile(r'<p id="(\d+)">(.*?)</p>', re.DOTALL)


class ProgressLog:
    """Append-only JSONL log of completed translation units inside a run dir.

    Lets translate_chunked / translate_per_paragraph survive crashes (dropped
    API connection, killed process): each successful unit is fsynced before the
    task returns, and a subsequent run loads the file and skips done units.
    Failed units are deliberately NOT persisted — re-running retries them.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    def load(self) -> tuple[dict[str, dict[int, str]], dict[int, str]]:
        """Return (done_chunks, done_paragraphs).

        done_chunks maps chunk_id -> {paragraph_id: translation} (chunked mode).
        done_paragraphs maps paragraph_id -> translation (per-paragraph mode).
        A truncated trailing line (mid-write crash) is silently dropped.
        """
        if not self.path.exists():
            return {}, {}
        done_chunks: dict[str, dict[int, str]] = {}
        done_paragraphs: dict[int, str] = {}
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "chunk":
                    done_chunks[rec["chunk_id"]] = {
                        int(k): v for k, v in rec["translations"].items()
                    }
                elif rec.get("type") == "paragraph":
                    done_paragraphs[int(rec["id"])] = rec["translation"]
        return done_chunks, done_paragraphs

    async def append_chunk(self, chunk_id: str, translations: dict[int, str]) -> None:
        await self._append({
            "type": "chunk",
            "chunk_id": chunk_id,
            "translations": {str(k): v for k, v in translations.items()},
        })

    async def append_paragraph(self, paragraph_id: int, translation: str) -> None:
        await self._append({
            "type": "paragraph",
            "id": paragraph_id,
            "translation": translation,
        })

    async def _append(self, rec: dict) -> None:
        line = json.dumps(rec, ensure_ascii=False)
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())


@dataclass(frozen=True, slots=True)
class ChunkValidation:
    """Result of parsing + validating a chunked LLM response.

    `parsed` is the id -> translation map on success, None on any failure.
    `reason` is None on success, otherwise one of:
    parse_failed, duplicate_ids, missing_ids, extra_ids, empty_content.
    `returned_ids` lists ids the LLM produced (in response order, with duplicates).
    """

    parsed: dict[int, str] | None
    reason: str | None
    returned_ids: list[int]


@dataclass(frozen=True, slots=True)
class ChunkFailure:
    """Diagnostic record for a chunk that failed validation after all retries.

    The two trailing fields carry the exact strings sent to the LLM. They are
    dumped to `failure_debug/chunk_<id>/` for inspection but stripped from
    `failures.jsonl` (whose readers expect a stable schema).
    """
    chunk_id: str
    range: list[int]            # [a, b] inclusive, as in chunking JSON
    ru_paragraph_ids: list[int] # payload_ids actually sent to LLM (excludes pictures)
    reason: str
    expected_ids: list[int]
    returned_ids: list[int]
    attempts: int
    last_response: str
    system_prompt: str = ""
    rendered_user_prompt: str = ""


_DEBUG_ONLY_FIELDS = ("system_prompt", "rendered_user_prompt")


def _parse_and_validate(response: str, expected_ids: list[int]) -> ChunkValidation:
    matches = _TAG_RE.findall(response)
    if not matches:
        return ChunkValidation(parsed=None, reason="parse_failed", returned_ids=[])
    returned_ids = [int(i) for i, _ in matches]
    if len(set(returned_ids)) != len(returned_ids):
        return ChunkValidation(parsed=None, reason="duplicate_ids", returned_ids=returned_ids)
    expected_set = set(expected_ids)
    returned_set = set(returned_ids)
    if expected_set - returned_set:
        return ChunkValidation(parsed=None, reason="missing_ids", returned_ids=returned_ids)
    if returned_set - expected_set:
        return ChunkValidation(parsed=None, reason="extra_ids", returned_ids=returned_ids)
    parsed = {int(i): " ".join(t.split()) for i, t in matches}
    if any(not v for v in parsed.values()):
        return ChunkValidation(parsed=None, reason="empty_content", returned_ids=returned_ids)
    return ChunkValidation(parsed=parsed, reason=None, returned_ids=returned_ids)


def _build_tagged_chunk(payload_ids: list[int], paragraphs: list[str]) -> str:
    """Wrap each paragraph in `<p id="N">...</p>` and join with blank lines."""
    return "\n\n".join(f'<p id="{i}">{paragraphs[i]}</p>' for i in payload_ids)


def _is_picture_or_dinkus(text: str) -> bool:
    """Picture marker lines pass through Mode B without translation.

    Detected by the literal substring 'picture' (case-insensitive). Russian
    source has no such word; markers like ``==> picture [W x H] <==``, ``* * *`` and
    placeholder caption ``Picture text`` are caught.
    """
    return "picture" in text.lower() or text == "* * *"


def _collect_context_indices(paragraphs: list[str], i: int, k: int) -> list[int]:
    """Return up to k indices of non-picture paragraphs immediately preceding i.

    Walking backwards skips picture markers — their Mode B output is the
    Russian original, which would poison the EN context.
    """
    if k <= 0 or i <= 0:
        return []
    picked: list[int] = []
    j = i - 1
    while j >= 0 and len(picked) < k:
        if not _is_picture_or_dinkus(paragraphs[j]):
            picked.append(j)
        j -= 1
    picked.reverse()
    return picked


def _build_context_block(items: list[str]) -> str:
    """Format the [CONTEXT] block for the user message; empty when no items."""
    if not items:
        return ""
    return "[CONTEXT]\n" + "\n\n".join(items) + "\n\n"


async def translate_chunked(
    *,
    paragraphs: list[str],
    chunks: dict[str, list[int]],
    client: LLMClient,
    system_prompt: str,
    user_prompt: str,
    semaphore: asyncio.Semaphore,
    max_retries: int = 1,
    progress_log: ProgressLog | None = None,
) -> tuple[list[str], list[ChunkFailure]]:
    """Translate paragraphs in chunks. One LLM call per chunk; retry on
    invariant violation; failed chunks become `[TRANSLATION FAILED]` lines and
    a ChunkFailure record. Returns (results, failures).

    `max_retries=1` means one retry after the initial attempt (2 LLM calls per
    chunk maximum).

    When `progress_log` is given, already-completed chunks are pre-filled from
    its on-disk record and skipped; each successful chunk in this run is
    appended (fsynced) before the task returns.
    """
    n = len(paragraphs)
    results: list[str] = [""] * n
    failures: list[ChunkFailure] = []

    done_chunks: dict[str, dict[int, str]] = {}
    if progress_log is not None:
        done_chunks, _ = progress_log.load()
        for translations in done_chunks.values():
            for i, t in translations.items():
                results[i] = t

    async def process_chunk(chunk_id: str, span: list[int]) -> None:
        if chunk_id in done_chunks:
            return
        a, b = span
        ids = list(range(a, b + 1))
        for i in ids:
            if _is_picture_or_dinkus(paragraphs[i]):
                results[i] = paragraphs[i].replace("\n", " ").strip()
        payload_ids = [i for i in ids if not _is_picture_or_dinkus(paragraphs[i])]
        if not payload_ids:
            return
        tagged = _build_tagged_chunk(payload_ids, paragraphs)
        user_msg = user_prompt.format(chunk=tagged)
        last_validation: ChunkValidation | None = None
        last_response = ""
        for _attempt in range(max_retries + 1):
            async with semaphore:
                response = (await client.complete(system_prompt, user_msg)).content
            last_response = response
            last_validation = _parse_and_validate(response, payload_ids)
            if last_validation.parsed is not None:
                for i, t in last_validation.parsed.items():
                    results[i] = t
                if progress_log is not None:
                    await progress_log.append_chunk(chunk_id, last_validation.parsed)
                return
        for i in payload_ids:
            results[i] = "[TRANSLATION FAILED]"
        assert last_validation is not None  # loop ran at least once
        failures.append(ChunkFailure(
            chunk_id=chunk_id,
            range=[a, b],
            ru_paragraph_ids=payload_ids,
            reason=last_validation.reason or "unknown",
            expected_ids=payload_ids,
            returned_ids=last_validation.returned_ids,
            attempts=max_retries + 1,
            last_response=last_response,
            system_prompt=system_prompt,
            rendered_user_prompt=user_msg,
        ))

    task_objs = [asyncio.create_task(process_chunk(cid, span)) for cid, span in chunks.items()]
    await tqdm.gather(*task_objs)
    return results, failures


async def translate_per_paragraph(
    *,
    ru_md: Path,
    output: Path,
    client: LLMClient,
    system_prompt: str | None,
    user_prompt: str,
    semaphore: asyncio.Semaphore,
    context_paragraphs: int = 0,
    progress_log: ProgressLog | None = None,
) -> None:
    """Translate every line of ``ru_md`` and write 1:1 to ``output``.

    Picture markers pass through verbatim and are excluded from the context
    window. With ``context_paragraphs > 0`` each task awaits its predecessors
    so the user message can include their EN translations under ``[CONTEXT]``.

    When `progress_log` is given, already-translated paragraphs are pre-loaded
    and skipped; each successful paragraph in this run is appended (fsynced)
    before the task returns.
    """
    paragraphs = ru_md.read_text(encoding="utf-8").splitlines()
    n = len(paragraphs)
    loop = asyncio.get_running_loop()
    futures: list[asyncio.Future[str]] = [loop.create_future() for _ in range(n)]

    done_paragraphs: dict[int, str] = {}
    if progress_log is not None:
        _, done_paragraphs = progress_log.load()

    async def translate_one(i: int) -> str:
        if i in done_paragraphs:
            cleaned = done_paragraphs[i]
            futures[i].set_result(cleaned)
            return cleaned
        paragraph = paragraphs[i]
        if _is_picture_or_dinkus(paragraph):
            cleaned = paragraph.replace("\n", " ").strip()
            futures[i].set_result(cleaned)
            return cleaned
        ctx_indices = _collect_context_indices(paragraphs, i, context_paragraphs)
        ctx_items = [await futures[j] for j in ctx_indices]
        user_msg = user_prompt.format(
            context=_build_context_block(ctx_items),
            paragraph=paragraph,
        )
        async with semaphore:
            response = (await client.complete(system_prompt, user_msg)).content
        cleaned = " ".join(response.split())
        futures[i].set_result(cleaned)
        if progress_log is not None:
            await progress_log.append_paragraph(i, cleaned)
        return cleaned

    tasks = [translate_one(i) for i in range(n)]
    results = await tqdm.gather(*tasks)
    output.write_text("\n".join(results), encoding="utf-8")


def load_prompt(relative_path: str) -> str:
    """Read a prompt file specified relative to ``prompts/``."""
    return (PROMPTS / relative_path).read_text(encoding="utf-8")


def dispatch_mode(user_prompt_path: Path) -> str:
    """Return 'per_paragraph' if the user-prompt template uses `{paragraph}`,
    'chunked' if it uses `{chunk}`. Raises ValueError otherwise.
    """
    text = user_prompt_path.read_text(encoding="utf-8")
    has_par = "{paragraph}" in text
    has_chunk = "{chunk}" in text
    if has_par and has_chunk:
        raise ValueError(
            f"{user_prompt_path}: must contain exactly one of "
            "{paragraph} or {chunk}, not both"
        )
    if has_par:
        return "per_paragraph"
    if has_chunk:
        return "chunked"
    raise ValueError(
        f"{user_prompt_path}: must contain {{paragraph}} or {{chunk}} placeholder"
    )


def write_run_artifacts(
    *,
    out_dir: Path,
    results: list[str],
    failures: list[ChunkFailure],
    config: dict,
) -> None:
    """Write translation.md, config.json, and (if failures) failures.jsonl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "translation.md").write_text(
        "\n".join(results), encoding="utf-8"
    )
    failed_paragraph_count = sum(len(f.ru_paragraph_ids) for f in failures)
    config_with_failures = {
        **config,
        "failures": {
            "chunks": len(failures),
            "paragraphs": failed_paragraph_count,
        },
    }
    (out_dir / "config.json").write_text(
        json.dumps(config_with_failures, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if failures:
        records = [
            {k: v for k, v in asdict(f).items() if k not in _DEBUG_ONLY_FIELDS}
            for f in failures
        ]
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        (out_dir / "failures.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        debug_root = out_dir / "failure_debug"
        debug_root.mkdir(exist_ok=True)
        for f in failures:
            chunk_dir = debug_root / f"chunk_{f.chunk_id}"
            chunk_dir.mkdir(exist_ok=True)
            (chunk_dir / "system_prompt.md").write_text(f.system_prompt, encoding="utf-8")
            (chunk_dir / "user_prompt.md").write_text(f.rendered_user_prompt, encoding="utf-8")
            (chunk_dir / "response.md").write_text(f.last_response, encoding="utf-8")
            meta = {
                "chunk_id": f.chunk_id,
                "range": f.range,
                "expected_ids": f.expected_ids,
                "returned_ids": f.returned_ids,
                "reason": f.reason,
                "attempts": f.attempts,
            }
            (chunk_dir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
