# Stage 03 — Scoring (Оценка)

Up-link: [docs/pipeline.md](../pipeline.md). Контракт путей: [pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md).

## Purpose

Оценить переводы из Stage 02 N одно-criterion LLM-промптами на каждого судью (5 критериев: accuracy, terminology, cultural, fluency, style — consistency убран в `_legacy/`). Factcheck выключен по умолчанию (`FactcheckConfig.enabled = False`); включается явным `enabled: true` в конфиге. Множественные судьи поддерживаются; в стартовой батарее — только `gpt-5.5-low`.

## Design decisions

Полный список решений — в [specs/2026-05-14-scoring-subsets-and-output-design.md](../superpowers/specs/2026-05-14-scoring-subsets-and-output-design.md) (S1-S10). Краткий дистиллят:

- **S1-S3 — Paragraph subset**: `ScoringConfig.paragraph_subset: str | None`. Если задано — оцениваются только параграфы из `data/pilot/scoring_subsets/<name>.json`. Compact → full переход работает через idempotent resume (уже сделанное не пере-оценивается).
- **S5 — consistency в `_legacy/`**: `prompts/03_scoring/_legacy/consistency.md` — вне любого variant'а; dispatcher видит только 5 файлов в `v1/`. Исторические JSONL не трогаются.
- **S6 — Factcheck off by default**: `FactcheckConfig.enabled = False`. Из YAML'ов секция удалена (отсутствие = false). Функционал не удалён — `enabled: true` работает.
- **S7 — Variant в пути**: `<run>/<variant>/<judge>/...` вместо `<run>/<judge>/...`. Factcheck вне variant'а: `<run>/factcheck/`.
- **S8 — Два derived-артефакта**: `comparison.jsonl` (judges side-by-side) + `reports/<judge>.jsonl` (full llm_report). `merged_scores.jsonl` и top-level `scores.json` удалены.
- **Usage / cost tracking**: каждая строка `*_scores.jsonl` несёт сырой `usage` от провайдера (OpenAI / CloseRouter — `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`; Anthropic — `input_tokens`, `output_tokens`). `meta.json` агрегирует `totals` (суммы токенов и `cost_usd`) по всем criterion'ам — пересчитывается на каждом запуске, idempotent на resume. Маркеры / `[TRANSLATION FAILED]` / terminal-null строки имеют `usage: null`.
- **Config-driven**: список судей, список run'ов, `prompts_variant`, опциональный `paragraph_subset` — всё в YAML.
- **Filename-driven variant discovery** (D1): `load_prompts(prompts_root, variant)` делает `glob('*.md')` в `prompts_root/variant/`. Имя файла без расширения = имя criterion'а.
- **Гибрид structured-output** (D3 + D16): JSON-инструкция в каждом промпте как provider-agnostic база; сверху, если у судьи `supports_structured_output: true`, scoring пробрасывает `response_format={"type":"json_object"}` в [LLMClient](../../src/palimpsest/llm/client.py). OpenAI-compat провайдеры получают параметр напрямую; Anthropic-судьи маршрутизируются через native `/messages` endpoint (см. Subtleties → Provider routing) и параметр коэрсится в forced tool-call с judge-схемой.
- **Idempotent resume**: повторный запуск пропускает `id`'ы, уже записанные в criterion-JSONL.
- **Fail-fast + terminal null** (D12-D13): parse fail = `JudgeParseError`, raw → `parse_failures.jsonl`; после 3 fail'ов на одну `(id, criterion)` — terminal `score: null` без дальнейших API-вызовов.
- **Atomic writes** (S8): derived-builders пишут в `.jsonl.tmp`, по завершении — `tmp.replace(out_path)` (`os.rename`, атомарен в пределах одной FS).

## Interface

```python
from pathlib import Path
from palimpsest.config import load_scoring
from palimpsest.scoring import run_scoring

cfg = load_scoring(Path("configs/scoring/large-low.yaml"))
await run_scoring(cfg)
```

CLI:

```bash
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml --force
python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml --max-paragraphs 5
```

Пример конфига (без factcheck; с опциональным subset):

```yaml
base_dir: data/pilot
prompts_variant: v1
max_concurrency: 64
judges:
  - model: gpt-5.5-low
# paragraph_subset: complex_150   # раскомментировать для subset-прогона
runs:
  - large/qwen_par_by_par
```

Для боевого прогона с retry-on-crash есть шелл-обёртка `scripts/03_scoring_resume.sh` — запускает large-low и small-low параллельно, каждый с `MAX_RETRIES` повторами и логом в `data/pilot/evaluation/<profile>.log`.

## Output layout

```
data/pilot/evaluation/<run>/
├── v1/                                  ← variant scope
│   ├── <judge>/
│   │   ├── accuracy_scores.jsonl        ← raw, schema unchanged
│   │   ├── terminology_scores.jsonl
│   │   ├── cultural_scores.jsonl
│   │   ├── fluency_scores.jsonl
│   │   ├── style_scores.jsonl
│   │   ├── parse_failures.jsonl         ← raw, append-only diagnostic
│   │   └── meta.json                    ← prompts, paragraph_subset, totals
│   ├── reports/                         ← derived
│   │   └── <judge>.jsonl               ← full llm_report per paragraph per judge
│   └── comparison.jsonl                 ← derived: judges side-by-side
└── factcheck/                           ← outside variant (shared)
    └── factcheck_scores.jsonl
```

**Derived-артефакты пересобираются после каждого `run_scoring(cfg)`** через `build_comparison_jsonl` + `build_judge_reports`. Они всегда regenerable из raw JSONL.

Удалены: `<run>/merged_scores.jsonl` и `evaluation/scores.json`. Rollup делается вне stage 03 (Jupyter / Excel).

## Subtleties

- **Score field** в `<criterion>_scores.jsonl`: `int 1-10` (валидная оценка) или `null` (sentinel skip / persistent parse failure). Никакого `-1`.
- **`parse_failures.jsonl`** — append-only лог per judge, схема `{id, criterion, reason, raw, source, translated, judge, variant, ts}`. Не читается агрегацией.
- **`_PERSISTENT_FAILURE_THRESHOLD = 3`** — в [scoring.py](../../src/palimpsest/scoring.py). Если при старте `_score_run_for_judge` обнаруживается ≥ 3 падений на `(id, criterion)` — terminal null без API-вызова.
- **Subset filter**: применяется в начале `_score_run_for_judge` перед циклом. Id из subset'а, которых нет в run — hard error. Compact → full: добавленные параграфы добираются resume'ом.
- **Factcheck outside variant**: `factcheck/` лежит прямо под `<run>/`, не под `<run>/<variant>/`. Один factcheck на run независимо от variant'а.
- **Atomic write**: derived-builders пишут `.jsonl.tmp`, затем `Path.replace` (= `os.rename`, атомарен на одной FS). Kill-9 в середине записи оставляет либо старый полный файл, либо `.tmp` — `comparison.jsonl` никогда не бывает обрезанным.
- **Terminal null** всё так же применяется: после 3 escalation'ов параграф получает `score: null` в criterion-JSONL и больше не пытается оцениваться.
- **Sequential dispatch (v2)**: `run_scoring` обрабатывает runs строго последовательно; внутри run factcheck завершается до старта judge-тасков. `MAX_CONCURRENCY` enforced через `asyncio.Semaphore` в `LLMClient`.
- **Provider routing в `LLMClient`**: судьи c yaml-флагом `provider: anthropic` (haiku/sonnet/opus) идут через Anthropic SDK напрямую на `/messages` — CloseRouter'овский OpenAI-compat bridge для них 502'ит на forced tool-call (детали — запись 8 в [known_issues.md](../known_issues.md)). Остальные судьи (OpenAI, Gemini, Qwen, DeepSeek, GLM) идут через OpenAI SDK на `/chat/completions`. На уровне scoring разница не видна — `response_format={"type":"json_object"}` пробрасывается единообразно, клиент сам коэрсит в forced `tool_choice` на Anthropic-пути с дефолтной judge-схемой.
- **Smoke harness**: `scripts/03_scoring_smoke.sh` — scoring на 10 параграфах в `tests/.scoring_smoke/evaluation/` (gitignored, отделено от реальных pilot-данных). Запускать перед каждой большой батареей.
- **Row schema**: `{id, source, translated, judge, variant, score, llm_report, usage}`. `usage` — сырой dict провайдера (CloseRouter включает `cost` в USD за вызов и `completion_tokens_details.reasoning_tokens` для reasoning-моделей).

## Status

Реализован. Smoke на `configs/scoring/smoke.yaml` зелёный.

- v1 single-criterion + filename-driven discovery + no-`-1` policy (2026-05-14).
- v2 sequential dispatch + per-client concurrency cap + 2-retry transient guarantee.
- **Refactor 2026-05-14**: paragraph subsets + output redesign (`<run>/<variant>/` layout, `comparison.jsonl` + `reports/<judge>.jsonl`) + consistency → `_legacy/` + factcheck off by default.
- Единственный judge `gpt-5.5-low` в 01-06 priority конфигах; другие подключаются через resume.
