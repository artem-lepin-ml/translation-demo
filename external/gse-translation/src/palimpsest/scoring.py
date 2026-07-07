from __future__ import annotations

from typing import Final, Literal
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from .config import JudgeConfig, ScoringConfig, load_models
from .llm.client import LLMClient, LLMConfig
from .paths import (
    _split_run,
    comparison_jsonl,
    criterion_jsonl,
    evaluation_run_dir,
    factcheck_dir,
    factcheck_jsonl,
    judge_dir,
    parse_failures_jsonl,
    report_jsonl,
    translation_md,
)
from .factcheck.extractor import FactExtractor
from .factcheck.overlap import FactOverlap
from .scoring_subsets import load_subset
from tqdm.asyncio import tqdm as async_tqdm


class JudgeParseError(Exception):
    """Raised when an LLM response cannot be parsed into a valid judge payload.

    Carries the raw response and a categorical reason so the dispatcher can
    persist diagnostic info to <judge>/parse_failures.jsonl before escalation.
    Reasons: "empty" | "json_decode" | "missing_score" | "score_out_of_range".
    """

    def __init__(self, criterion: str, raw: str, reason: str):
        self.criterion = criterion
        self.raw = raw
        self.reason = reason
        super().__init__(f"{criterion}: {reason}")


ParagraphKind = Literal["normal", "marker", "translation_failed"]


def classify_paragraph(source: str) -> ParagraphKind:
    """Classify a paragraph before dispatch.

    Markers (`* * *`, `picture`) → skipped, score null.
    `[TRANSLATION FAILED]` → skipped with warning, score null.
    """
    stripped = source.strip()
    if stripped == "[TRANSLATION FAILED]":
        return "translation_failed"
    if stripped == "* * *":
        return "marker"
    if "picture" in source.lower():
        return "marker"
    return "normal"


_JSON_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


def parse_judge_response(raw: str, criterion: str) -> dict:
    """Extract a JSON object from a judge response and validate `final_score`.

    Handles markdown ```json fences and prose before/after the JSON.
    Raises JudgeParseError on any failure (empty / malformed / missing score /
    out-of-range). Caller is responsible for catching and persisting raw
    to parse_failures.jsonl before re-raising for escalation.
    """
    if not raw or not raw.strip():
        raise JudgeParseError(criterion, raw or "", "empty")
    match = _JSON_FENCE.search(raw)
    candidate = match.group(1) if match else raw
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(criterion, raw, f"json_decode: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise JudgeParseError(criterion, raw, "json_decode: not an object")
    score = parsed.get("final_score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise JudgeParseError(criterion, raw, "missing_score")
    if not 1 <= score <= 10:
        raise JudgeParseError(criterion, raw, "score_out_of_range")
    return parsed


# JSONL score field conventions (spec D12). Sentinel `None` marks terminal
# skips (markers / [TRANSLATION FAILED] / persistent parse failures). Real
# scores are ints in [1, 10]. Anything in JSONL = done; parse failures live
# in parse_failures.jsonl and are retried via load_existing_ids absence.
SCORE_SKIPPED: Final[None] = None


def load_prompts(prompts_root: Path, variant: str) -> dict[str, str]:
    """Load all `*.md` prompts from `prompts_root/variant/`.

    Each `.md` file = one criterion. Returns `{filename_stem: file_text}` with
    keys in sorted order for deterministic JSONL column ordering. Raises
    FileNotFoundError if the directory is missing or contains no `.md` files.
    """
    variant_dir = prompts_root / variant
    if not variant_dir.is_dir():
        raise FileNotFoundError(
            f"prompts variant directory not found: {variant_dir}"
        )
    files = sorted(variant_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(
            f"no *.md prompts found in {variant_dir}"
        )
    return {f.stem: f.read_text(encoding="utf-8") for f in files}


_USER_MSG_TEMPLATE = (
    '**Source text (Russian)** — for reference when identifying recurring'
    ' elements:\n{}\n\n**Translation (English)** — this is what you are evaluating:\n{}'
)


_MAX_PARSE_ATTEMPTS: int = 2  # 1 initial + 1 retry; see spec D12.

# Per-call JSON-mode constraint (OpenAI JSON mode / OpenRouter structured outputs).
# Passed uniformly to every judge call; LLMClient gates forwarding on the model's
# supports_structured_output flag — silently dropped for providers that don't
# accept this param (e.g. local vLLM without guided-decoding). See spec D16.
_JUDGE_RESPONSE_FORMAT = {"type": "json_object"}

# Anthropic-only tool input_schema for the judge contract. Mirrors what
# parse_judge_response validates (`final_score` required; extras are allowed
# per prompt variant — summary, identified_issues, criteria_assessment). The
# OpenAI path stays on `{"type":"json_object"}` because strict json_schema mode
# rejects `additionalProperties: true`. Passed via `tool_schema=` to
# LLMClient.complete — see Anthropic routing in llm/client.py.
_JUDGE_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "final_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "summary": {"type": "string"},
        "identified_issues": {"type": "array"},
        "criteria_assessment": {"type": "object"},
    },
    "required": ["final_score"],
    "additionalProperties": True,
}


async def score_paragraph(
    client: LLMClient,
    source: str,
    translated: str,
    prompts: dict[str, str],
) -> dict[str, tuple[dict | JudgeParseError, dict | None]]:
    """Fire N single-criterion prompts in parallel for one paragraph.

    Returns {criterion: (parsed_payload | JudgeParseError, usage | None)}:
    each criterion runs independently with _MAX_PARSE_ATTEMPTS inline retries;
    a criterion that exhausts retries yields a JudgeParseError without
    blocking siblings. `usage` is the provider's usage block from the LAST
    LLM call for this criterion (rows for terminal nulls / markers / skips
    set usage=None in the caller, not here). Caller (`_score_run_for_judge.
    _process`) splits: successful payloads persist to <criterion>_scores.jsonl
    with usage; failed parses append to parse_failures.jsonl and trigger
    task-level escalation.
    """
    user_msg = _USER_MSG_TEMPLATE.format(source, translated)

    async def _one(
        criterion: str, prompt: str
    ) -> tuple[str, dict | JudgeParseError, dict | None]:
        last_exc: JudgeParseError | None = None
        last_usage: dict | None = None
        for attempt in range(_MAX_PARSE_ATTEMPTS):
            result = await client.complete(
                system=prompt, user=user_msg,
                response_format=_JUDGE_RESPONSE_FORMAT,
                tool_schema=_JUDGE_TOOL_SCHEMA,
            )
            last_usage = result.usage
            try:
                return criterion, parse_judge_response(result.content, criterion), last_usage
            except JudgeParseError as exc:
                last_exc = exc
                if attempt + 1 < _MAX_PARSE_ATTEMPTS:
                    print(
                        f"warning: parse failure for {criterion} "
                        f"(attempt {attempt+1}/{_MAX_PARSE_ATTEMPTS}, "
                        f"reason={exc.reason}); retrying",
                        flush=True,
                    )
        assert last_exc is not None
        return criterion, last_exc, last_usage

    results = await asyncio.gather(*(_one(c, p) for c, p in prompts.items()))
    return {c: (payload, usage) for c, payload, usage in results}


async def _extractor_run(client: LLMClient, text: str, language: str) -> list:
    """Module-level indirection — tests patch this directly."""
    return await FactExtractor(client).run(text, language)


async def _overlap_run(client: LLMClient, facts_ru: list, facts_en: list) -> dict:
    """Module-level indirection. Returns plain dict for jsonl serialization."""
    report = await FactOverlap(client).run(facts_ru, facts_en)
    return report.model_dump() if hasattr(report, "model_dump") else dict(report)


async def score_factcheck(client: LLMClient, source: str, translated: str) -> dict:
    """Two-sided atomic-fact overlap. Returns dict ready for factcheck_scores.jsonl."""
    facts_ru, facts_en = await asyncio.gather(
        _extractor_run(client, source, "ru"),
        _extractor_run(client, translated, "en"),
    )
    report = await _overlap_run(client, facts_ru, facts_en)
    return {
        "score": report["f1"],
        "precision": report["precision"],
        "recall": report["recall"],
        "matches": report.get("matches", []),
        "unmatched_ru": report.get("unmatched_ru", []),
        "unmatched_en": report.get("unmatched_en", []),
        "llm_report": (
            f"P={report['precision']:.2f} R={report['recall']:.2f} "
            f"F1={report['f1']:.2f} |RU|={len(facts_ru)} |EN|={len(facts_en)}"
        ),
    }


def load_existing_ids(path: Path) -> set[int]:
    """Return paragraph ids already persisted to this criterion-jsonl.

    Per spec D12: presence of a row = done. No more -1 sentinel filtering;
    parse failures don't write here, they write to parse_failures.jsonl.
    """
    if not path.exists():
        return set()
    ids: set[int] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in row:
                ids.add(row["id"])
    return ids


def _load_parse_failure_counts(path: Path) -> dict[tuple[int, str], int]:
    """Count parse failures per (paragraph_id, criterion) from parse_failures.jsonl.
    Used by `_score_run_for_judge` to decide when to write a terminal-null row."""
    if not path.exists():
        return {}
    counts: dict[tuple[int, str], int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (row.get("id"), row.get("criterion"))
            if key[0] is None or key[1] is None:
                continue
            counts[key] = counts.get(key, 0) + 1
    return counts


_PERSISTENT_FAILURE_THRESHOLD: int = 3


def append_jsonl_row(path: Path, row: dict) -> None:
    """Append one JSON row to `path`, creating parent directories if needed.
    Flushes and fsyncs so a process crash can't lose the row in the page cache.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _build_client(model_key: str, max_concurrency: int = 0) -> LLMClient:
    """Build an LLMClient for a model_key in configs/models.yaml.

    Module-level indirection so tests can monkeypatch.
    """
    models = load_models()
    if model_key not in models:
        raise KeyError(f"model {model_key!r} not found in models.yaml")
    return LLMClient(
        LLMConfig.from_model_config(models[model_key]),
        max_concurrency=max_concurrency,
    )


def _read_aligned_lines(
    ru_md: Path, en_md: Path, limit: int | None = None
) -> list[tuple[str, str]]:
    ru_lines = ru_md.read_text(encoding="utf-8").splitlines()
    en_lines = en_md.read_text(encoding="utf-8").splitlines()
    if len(ru_lines) != len(en_lines):
        raise ValueError(
            f"line-count mismatch: {ru_md.name}={len(ru_lines)} vs {en_md.name}={len(en_lines)}"
        )
    pairs = list(zip(ru_lines, en_lines))
    return pairs[:limit] if limit else pairs


def _skip_payload(reason: str) -> dict:
    return {
        "final_score": SCORE_SKIPPED,
        "summary": "",
        "identified_issues": [],
        "llm_report": f"skipped: {reason}",
    }


def _compute_totals(paths: list[Path]) -> dict:
    """Sum prompt/completion/total tokens and cost across rows of `paths`.

    Reads usage dicts back from disk so totals are accurate on resume (existing
    rows + newly written rows are both counted). Anthropic responses lack `cost`
    → counted as 0; CloseRouter/OpenAI inline `cost` per call.
    """
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "rows_with_usage": 0,
    }
    for p in paths:
        if not p.is_file():
            continue
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = row.get("usage")
                if not u:
                    continue
                totals["prompt_tokens"] += int(u.get("prompt_tokens", 0) or 0)
                totals["completion_tokens"] += int(u.get("completion_tokens", 0) or 0)
                totals["total_tokens"] += int(u.get("total_tokens", 0) or 0)
                totals["cost_usd"] += float(u.get("cost", 0.0) or 0.0)
                totals["rows_with_usage"] += 1
    return totals


def _load_pairs_map(cfg: ScoringConfig, run: str) -> dict[int, tuple[str, str]]:
    """Return {id: (source, translated)} for all paragraphs in a run.

    id is the 0-based line index from _read_aligned_lines (pilot_original.md × translation.md).
    """
    if cfg.original_json:
        ru_pars = json.loads(cfg.original_json.read_text())
        en_pars = json.loads(cfg.translation_json.read_text())
        pairs = list(zip(ru_pars, en_pars))
    else:
        ru_md = cfg.base_dir / "pilot_original.md"
        en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
        pairs = _read_aligned_lines(ru_md, en_md)

    return {i: (src, tr) for i, (src, tr) in enumerate(pairs)}


async def _score_run_for_judge(
    *,
    cfg: ScoringConfig,
    run: str,
    judge: JudgeConfig,
    prompts: dict[str, str],
    criteria: list[str],
    variant: str,
    max_paragraphs: int | None = None,
) -> None:
    """Run one (run × judge) pair. Per spec D12-D13:
    - Successful paragraph: append row(s) to <criterion>_scores.jsonl.
    - Parse failure: log raw to parse_failures.jsonl; escalate via failures list.
    - After _PERSISTENT_FAILURE_THRESHOLD failures for (id, criterion):
      write terminal {"score": null, "llm_report": "persistent_parse_failure_..."}.
    """
    client = _build_client(judge.model, max_concurrency=cfg.max_concurrency)

    if cfg.original_json:
        ru_pars = json.loads(cfg.original_json.read_text())
        en_pars = json.loads(cfg.translation_json.read_text())
        pairs = list(zip(ru_pars, en_pars))
    else:
        ru_md = cfg.base_dir / "pilot_original.md"
        en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
        pairs = _read_aligned_lines(ru_md, en_md, limit=max_paragraphs)

    indexed_pairs = list(enumerate(pairs))
    if cfg.paragraph_subset:
        subset = load_subset(cfg.paragraph_subset, cfg.base_dir)
        n = len(pairs)
        bad = [pid for pid in subset.paragraph_ids if pid < 0 or pid >= n]
        if bad:
            raise ValueError(
                f"subset {subset.name!r} contains ids missing in run {run!r}: "
                f"first 5 = {bad[:5]}"
            )
        keep = set(subset.paragraph_ids)
        indexed_pairs = [(i, ru, en) for i, (ru, en) in indexed_pairs if i in keep]
    else:
        indexed_pairs = [(i, ru, en) for i, (ru, en) in indexed_pairs]

    target_paths = {
        c: criterion_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, variant, judge.model, c)
        for c in criteria
    }
    failures_path = parse_failures_jsonl(
        cfg.base_dir, cfg.evaluation_subdir, run, variant, judge.model
    )
    existing = {c: load_existing_ids(p) for c, p in target_paths.items()}
    fail_counts = _load_parse_failure_counts(failures_path)
    write_lock = asyncio.Lock()

    async def _persist_terminal_null(i: int, source: str, translated: str, criterion: str) -> None:
        row = {
            "id": i,
            "source": source,
            "translated": translated,
            "judge": judge.model,
            "variant": variant,
            "score": SCORE_SKIPPED,
            "llm_report": (
                f"persistent_parse_failure_after_{_PERSISTENT_FAILURE_THRESHOLD}_attempts; "
                f"see parse_failures.jsonl"
            ),
            "usage": None,
        }
        async with write_lock:
            append_jsonl_row(target_paths[criterion], row)

    async def _persist_failure_log(i: int, source: str, translated: str, exc: JudgeParseError) -> None:
        row = {
            "id": i,
            "criterion": exc.criterion,
            "reason": exc.reason,
            "raw": exc.raw,
            "source": source,
            "translated": translated,
            "judge": judge.model,
            "variant": variant,
            "ts": time.time(),
        }
        async with write_lock:
            append_jsonl_row(failures_path, row)

    async def _process(i: int, source: str, translated: str) -> None:
        prompts_for_this = dict(prompts)
        rows_to_write: dict[str, dict] = {}
        for c in criteria:
            if i in existing[c]:
                prompts_for_this.pop(c, None)
                continue
            if fail_counts.get((i, c), 0) >= _PERSISTENT_FAILURE_THRESHOLD:
                await _persist_terminal_null(i, source, translated, c)
                prompts_for_this.pop(c, None)
        if not prompts_for_this:
            return

        kind = classify_paragraph(source)
        if kind == "translation_failed":
            print(f"warning: [TRANSLATION FAILED] at id={i} for {run}", flush=True)
        if kind in ("marker", "translation_failed"):
            reason = "marker" if kind == "marker" else "translation_failed"
            for criterion in prompts_for_this:
                payload = _skip_payload(reason)
                rows_to_write[criterion] = {
                    "id": i,
                    "source": source,
                    "translated": translated,
                    "judge": judge.model,
                    "variant": variant,
                    "score": SCORE_SKIPPED,
                    "llm_report": payload["llm_report"],
                    "usage": None,
                }
            async with write_lock:
                for criterion, row in rows_to_write.items():
                    append_jsonl_row(target_paths[criterion], row)
            return

        results = await score_paragraph(client, source, translated, prompts_for_this)
        first_exc: JudgeParseError | None = None
        for criterion, (payload, usage) in results.items():
            if isinstance(payload, JudgeParseError):
                await _persist_failure_log(i, source, translated, payload)
                first_exc = first_exc or payload
                continue
            rows_to_write[criterion] = {
                "id": i,
                "source": source,
                "translated": translated,
                "judge": judge.model,
                "variant": variant,
                "score": payload.get("final_score"),
                "llm_report": payload,
                "usage": usage,
            }
        async with write_lock:
            for criterion, row in rows_to_write.items():
                append_jsonl_row(target_paths[criterion], row)
        if first_exc is not None:
            # Per-criterion failures don't block sibling writes (those persisted above),
            # but the task still raises so the run-level failure counter fires and the
            # shell wrapper restarts → resume sees absent rows for the failed criteria
            # and retries them (until _PERSISTENT_FAILURE_THRESHOLD).
            raise first_exc

    tasks = [_process(i, ru, en) for i, ru, en in indexed_pairs]
    failures: list[BaseException] = []
    with async_tqdm(total=len(tasks), desc=f"{run} × {judge.model}", file=sys.stderr) as bar:
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except BaseException as exc:
                failures.append(exc)
                async_tqdm.write(
                    f"warning: paragraph failed for {judge.model}: {exc!r}",
                    file=sys.stderr,
                )
            bar.update(1)

    j_dir = judge_dir(cfg.base_dir, cfg.evaluation_subdir, run, variant, judge.model)
    j_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "judge": judge.model,
        "variant": variant,
        "paragraph_subset": cfg.paragraph_subset,
        "prompts": prompts,
        "totals": _compute_totals(list(target_paths.values())),
    }
    (j_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    if failures:
        print(
            f"warning: {run} × {judge.model}: {len(failures)} paragraphs raised; "
            f"first error: {failures[0]!r}",
            file=sys.stderr,
            flush=True,
        )
        raise failures[0]


async def _score_factcheck_for_run(
    *,
    cfg: ScoringConfig,
    run: str,
    max_paragraphs: int | None = None,
) -> None:
    if not cfg.factcheck.enabled:
        return
    client = _build_client(cfg.factcheck.judge, max_concurrency=cfg.max_concurrency)

    ru_md = cfg.base_dir / "pilot_original.md"
    en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
    pairs = _read_aligned_lines(ru_md, en_md, limit=max_paragraphs)

    indexed_pairs = list(enumerate(pairs))
    if cfg.paragraph_subset:
        subset = load_subset(cfg.paragraph_subset, cfg.base_dir)
        keep = set(subset.paragraph_ids)
        indexed_pairs = [(i, ru, en) for i, (ru, en) in indexed_pairs if i in keep]
    else:
        indexed_pairs = [(i, ru, en) for i, (ru, en) in indexed_pairs]

    target = factcheck_jsonl(cfg.base_dir, cfg.evaluation_subdir, run)
    fc_dir = factcheck_dir(cfg.base_dir, cfg.evaluation_subdir, run)
    existing = load_existing_ids(target)
    write_lock = asyncio.Lock()

    async def _process(i: int, source: str, translated: str) -> None:
        if i in existing:
            return
        kind = classify_paragraph(source)
        if kind in ("marker", "translation_failed"):
            row = {
                "id": i,
                "source": source,
                "translated": translated,
                "score": SCORE_SKIPPED,
                "llm_report": f"skipped: {kind}",
            }
        else:
            fc = await score_factcheck(client, source, translated)
            row = {"id": i, "source": source, "translated": translated, **fc}
        async with write_lock:
            append_jsonl_row(target, row)

    tasks = [_process(i, ru, en) for i, ru, en in indexed_pairs]
    failures: list[BaseException] = []
    with async_tqdm(total=len(tasks), desc=f"{run} × factcheck", file=sys.stderr) as bar:
        # BaseException (not Exception) mirrors gather(return_exceptions=True):
        # siblings still fsync before CancelledError / KeyboardInterrupt propagates.
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except BaseException as exc:
                failures.append(exc)
                async_tqdm.write(
                    f"warning: factcheck paragraph failed for {run}: {exc!r}",
                    file=sys.stderr,
                )
            bar.update(1)

    fc_dir.mkdir(parents=True, exist_ok=True)
    (fc_dir / "meta.json").write_text(
        json.dumps({"judge": cfg.factcheck.judge}, ensure_ascii=False, indent=2)
    )

    if failures:
        print(
            f"warning: {run} × factcheck: {len(failures)} paragraphs raised; "
            f"first error: {failures[0]!r}",
            file=sys.stderr,
            flush=True,
        )
        raise failures[0]


def build_comparison_jsonl(
    cfg: ScoringConfig,
    run: str,
    criteria: list[str],
) -> None:
    """Rebuild <run>/<variant>/comparison.jsonl from raw criterion-JSONLs.

    Per-paragraph row: {id, source, translated, scores: {judge: {criterion: int|null}},
    factcheck: dict|None when enabled}. Sorted by id. Atomic write via tmp+rename.
    """
    variant = cfg.prompts_variant
    judges = [j.model for j in cfg.judges]

    per_judge: dict[str, dict[str, dict[int, int | None]]] = {}
    all_ids: set[int] = set()
    for judge in judges:
        per_judge[judge] = {}
        for crit in criteria:
            path = criterion_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, variant, judge, crit)
            id_to_score: dict[int, int | None] = {}
            if path.is_file():
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        row = json.loads(line)
                        id_to_score[row["id"]] = row.get("score")
                        all_ids.add(row["id"])
            per_judge[judge][crit] = id_to_score

    fc_by_id: dict[int, dict] = {}
    if cfg.factcheck.enabled:
        fc_path = factcheck_jsonl(cfg.base_dir, cfg.evaluation_subdir, run)
        if fc_path.is_file():
            with fc_path.open("r", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    fc_by_id[row["id"]] = row

    pairs_map = _load_pairs_map(cfg, run)

    out_path = comparison_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, variant)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for pid in sorted(all_ids):
            source, translated = pairs_map.get(pid, ("", ""))
            row: dict = {
                "id": pid,
                "source": source,
                "translated": translated,
                "scores": {
                    j: {c: per_judge[j][c].get(pid) for c in criteria}
                    for j in judges
                },
            }
            if cfg.factcheck.enabled:
                row["factcheck"] = fc_by_id.get(pid)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out_path)


def build_judge_reports(
    cfg: ScoringConfig,
    run: str,
    criteria: list[str],
) -> None:
    """Rebuild <run>/<variant>/reports/<judge>.jsonl per judge.

    Per-paragraph row: {id, source, translated, <criterion>: full_llm_report|null}.
    null when score is None (skip / persistent fail) OR row absent. Sorted by id.
    Atomic write via tmp+rename.
    """
    variant = cfg.prompts_variant
    pairs_map = _load_pairs_map(cfg, run)

    for judge in cfg.judges:
        judge_slug = judge.model
        per_crit: dict[str, dict[int, tuple[int | None, object]]] = {}
        all_ids: set[int] = set()
        for crit in criteria:
            path = criterion_jsonl(
                cfg.base_dir, cfg.evaluation_subdir, run, variant, judge_slug, crit
            )
            per_crit[crit] = {}
            if path.is_file():
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        row = json.loads(line)
                        per_crit[crit][row["id"]] = (row.get("score"), row.get("llm_report"))
                        all_ids.add(row["id"])

        out_path = report_jsonl(
            cfg.base_dir, cfg.evaluation_subdir, run, variant, judge_slug
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for pid in sorted(all_ids):
                source, translated = pairs_map.get(pid, ("", ""))
                row: dict = {"id": pid, "source": source, "translated": translated}
                for crit in criteria:
                    entry = per_crit[crit].get(pid)
                    if entry is None:
                        row[crit] = None
                    else:
                        score, llm_report = entry
                        row[crit] = llm_report if score is not None else None
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(out_path)


async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    """Main entry. Per spec D6: load prompts once; thread criteria through."""
    prompts = load_prompts(cfg.prompts_root, cfg.prompts_variant)
    criteria = list(prompts.keys())

    n_runs = len(cfg.runs)
    n_per_run = (1 if cfg.factcheck.enabled else 0) + len(cfg.judges)
    total = n_runs * n_per_run
    config_start = time.time()
    completed = 0
    print(
        f"[scoring] {total} tasks starting ({n_runs} runs × "
        f"({len(cfg.judges)} judges{' + factcheck' if cfg.factcheck.enabled else ''}); "
        f"criteria={criteria})",
        file=sys.stderr,
        flush=True,
    )

    failed_tasks: list[tuple[str, BaseException]] = []

    async def _run_task(task, label: str) -> None:
        nonlocal completed
        t0 = time.time()
        try:
            await task
        except BaseException as exc:
            failed_tasks.append((label, exc))
            print(f"warning: task failed: {label}: {exc!r}", flush=True)
        finally:
            completed += 1
            print(
                f"[{completed}/{total}] done in {time.time() - t0:.0f}s "
                f"(total {time.time() - config_start:.0f}s): {label}",
                file=sys.stderr,
                flush=True,
            )

    for run in cfg.runs:
        if cfg.factcheck.enabled:
            await _run_task(
                _score_factcheck_for_run(cfg=cfg, run=run, max_paragraphs=max_paragraphs),
                f"{run} × factcheck",
            )
        for judge in cfg.judges:
            await _run_task(
                _score_run_for_judge(
                    cfg=cfg, run=run, judge=judge,
                    prompts=prompts, criteria=criteria,
                    variant=cfg.prompts_variant,
                    max_paragraphs=max_paragraphs,
                ),
                f"{run} × {judge.model}",
            )

    print(
        f"[scoring] all {total} tasks done in {time.time() - config_start:.0f}s",
        file=sys.stderr,
        flush=True,
    )

    for run in cfg.runs:
        build_comparison_jsonl(cfg, run, criteria)
        build_judge_reports(cfg, run, criteria)

    if failed_tasks:
        raise RuntimeError(
            f"{len(failed_tasks)}/{total} scoring tasks raised after retries; "
            f"first: {failed_tasks[0][0]}: {failed_tasks[0][1]!r}"
        )
