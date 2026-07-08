# Stage 02 — Translate

Up-link: [docs/pipeline.md](../pipeline.md).

## Purpose

Translate `data/pilot/pilot_original.md` (RU) into EN, line-aligned with the source — one EN line per paragraph id. Chunking strategy from `data/pilot/chunking/for_translation/<chunk_name>.json` decides how paragraphs are batched into LLM calls.

## Design decisions

- LLM access goes through `palimpsest.llm.client.LLMClient` (Hard Invariant #6 in CLAUDE.md). The client is OpenAI-compatible (vLLM, cloud) and Anthropic.
- Two code paths in `src/palimpsest/translate.py`, dispatched by user-prompt placeholder:
  - `{paragraph}` → `translate_per_paragraph` — one LLM call per paragraph; picture/dinkus markers pass through without an LLM call. This is the historic baseline used with `par_by_par`.
  - `{chunk}` → `translate_chunked` — one LLM call per chunk wrapped in `<p id="N">…</p>` tags; picture-id excluded from the LLM payload and reattached at assembly. Validation requires the response to contain exactly the input ids; one retry; failed chunks become `[TRANSLATION FAILED]` sentinel lines and a record in `failures.jsonl`.
- Run artifacts under `data/pilot/translating/<run_name>/`: `translation.md` (line-aligned with source), `config.json` (run snapshot with inlined prompt text), `failures.jsonl` and `failure_debug/chunk_<id>/` (both only when ≥1 chunk failed), `progress.jsonl` (append-only resume log). Contract: [docs/pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md).
- Crash-safe resume: `progress.jsonl` holds one fsynced line per successfully translated unit (chunk or paragraph). Re-running the CLI on the same `<run_name>` pre-fills those units and only calls the LLM for what's missing. Failures stay out of the log so they retry on the next run.

## Interface

[src/palimpsest/translate.py](../../src/palimpsest/translate.py):

```python
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
) -> None: ...


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
) -> tuple[list[str], list[ChunkFailure]]: ...


def write_run_artifacts(
    *, out_dir: Path, results: list[str],
    failures: list[ChunkFailure], config: dict,
) -> None: ...


def dispatch_mode(user_prompt_path: Path) -> str: ...

def load_prompt(relative_path: str) -> str: ...
```

CLI driver: [scripts/02_translate.py](../../scripts/02_translate.py).

## Subtleties

- Validation order in `translate_chunked`: `parse_failed` → `duplicate_ids` → `missing_ids` → `extra_ids` → `empty_content`. The first matching condition becomes the failure reason.
- Picture markers (`"picture"` substring case-insensitive, or `"* * *"`) are excluded from the chunked LLM payload and pass through unchanged at assembly. They count as 1 line in the output but consume zero LLM calls.
- All-picture chunks skip the LLM call entirely; the chunk has no `ChunkFailure` even though no translation happened.
- `dispatch_mode` raises if the user-prompt file contains both `{paragraph}` and `{chunk}` placeholders (or neither).
- Exit code: 0 if all chunks succeeded, 1 if `failures.jsonl` was written.
- Per failed chunk, `failure_debug/chunk_<id>/` carries `system_prompt.md`, `user_prompt.md` (with `{chunk}` already substituted), `response.md` (last raw model output), and `meta.json` (chunk_id, range, expected_ids, returned_ids, reason, attempts). These strings live only on disk — they are stripped from `failures.jsonl`.
- `scripts/02_translate.py` accepts `--bucket {small,large,local}`. Output dir becomes `data/pilot/translating/<bucket>/<run_name>/`. Empty `--bucket` (default) keeps the legacy flat layout for backward compatibility with scripts that don't pass the flag.
- `progress.jsonl` lines are `{"type":"chunk","chunk_id":...,"translations":{...}}` or `{"type":"paragraph","id":...,"translation":...}`. The loader silently drops a truncated trailing line (mid-write crash). Concurrent appends are serialized through an `asyncio.Lock` and each write is fsynced before the producing task returns. To start from scratch, delete the run directory.
- `OPENROUTER_BASE_URL` (optional env var) transparently overrides the OpenRouter base URL at runtime for every yaml entry with `base_url: https://openrouter.ai/api/v1`. The yaml URL stays the source of truth for cache-marker dispatch (`or_style` flag on `LLMConfig`). The script prints both yaml and resolved endpoints to stderr at startup as a safeguard against accidental misrouting.

## Status

Chunked path and per-paragraph path both implemented. CLI emits `translation.md`, `config.json`, `progress.jsonl`, and `failures.jsonl` (when applicable) under `data/pilot/translating/<bucket>/<run_name>/`. `par_by_par` baseline works with the historic prompts in `prompts/02_translate/{system,user}.md`. Chunked strategies (`by_chapter`, `by_subchapter`, `by_5_par`, `by_10_par`) work with `prompts/02_translate/chunked_{system,user}.md`; active pilot experiments use `par_by_par`, `by_5_par`, `by_10_par`.

## Prompt caching

The LLM client picks caching strategy from `base_url`:

- **OpenAI direct** (`api.openai.com`): automatic prefix caching for prompts > 1024 tokens. No code-level marker. 24-hour TTL. 50% discount on cached input tokens.
- **OpenRouter** (`openrouter.ai`): explicit `cache_control: {"type": "ephemeral"}` marker on the system message. Honored by Anthropic-via-OR directly; Gemini-via-OR and Qwen-via-OR best-effort (OR pass-through). 5-minute TTL on cached blocks.
- **Other endpoints** (local vLLM, direct anthropic): no caching marker; client sends plain string content.

Field `cache_strategy` in `config.json` records which strategy was applied.

## Run naming

`run_name` = `<model-yaml-key>_<chunking-name>`, e.g. `claude-haiku-4.5_par_by_par`.

Model key uses provider-style slugs with dots and dashes (matches OR-style identifier).
Chunking name comes from the artifact filename (`par_by_par`, `by_10_par`, etc.).
