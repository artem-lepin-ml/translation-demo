# Multi-judge scoring pipeline — design

Up-link: [CLAUDE.md → Workflow](../../../CLAUDE.md), [pipeline.md](../../pipeline.md).
Контракт путей: [docs/pilot_interfaces_agreement.md](../../pilot_interfaces_agreement.md).

## Контекст

После Stage 03 в `data/pilot/translating/<bucket>/<run_name>/` лежат переводы от ~60 разных моделей и конфигураций. Stage 04 («Оценка») должен:

- Прогнать каждый `run_name` через **N судей** одновременно (config-driven).
- На один параграф делать максимум 3 LLM-вызова per судья: `faithfulness` + `english_quality` + `factcheck` — против старой схемы из 6 однокритериевых промптов.
- Поддерживать **три варианта промптов**: `old/` (legacy, 6 промптов), `compact/` (для маленьких/локальных моделей, <1k токенов), `full/` (для крупных, ~3k).
- Писать сырые per-judge JSONL (для resume и дебага) + один сводный `merged_scores.jsonl` (для аналитики).

Текущая [src/palimpsest/scoring.py](../../../src/palimpsest/scoring.py) работает с одним судьёй и сломанными путями в [configs/scoring.yaml](../../../configs/scoring.yaml) (ссылается на `03_scoring/accuracy.md` — файл переехал в `old/`). Refactor неизбежен.

## Решения

### Architecture

**One stage = one module** ([CLAUDE.md Hard Invariant](../../../CLAUDE.md)). Переписать `scoring.py` как диспатчер `(judge × run × paragraph) → strategy`, где стратегий три:

- `legacy` — variant=old: 6 параллельных LLM-вызовов на параграф, по одному ответу на критерий.
- `consolidated` — variant=compact|full: 2 LLM-вызова (faithfulness, english_quality), парсим JSON, маршрутизируем 3+3 критерия в JSONL-файлы.
- `factcheck` — отдельный шаг с фиксированной моделью (не зависит от списка `judges`), использует `FactExtractor`+`FactOverlap` из [src/palimpsest/factcheck/](../../../src/palimpsest/factcheck/).

LLM-доступ только через `palimpsest.llm.client.LLMClient` (CLAUDE.md Hard Invariant #6).

### Output layout

```
data/pilot/evaluation/<run_name>/
├── <judge_slug>/                        # один каталог на каждого судью
│   ├── accuracy_scores.jsonl            # сырая канонная форма
│   ├── terminology_scores.jsonl         # (для resume, дебага, пересчёта)
│   ├── cultural_scores.jsonl
│   ├── fluency_scores.jsonl
│   ├── style_scores.jsonl
│   ├── consistency_scores.jsonl
│   └── meta.json                        # variant, model_key, prompt-snapshot
├── factcheck/
│   ├── factcheck_scores.jsonl
│   └── meta.json
└── merged_scores.jsonl                  # сводный per-paragraph файл

data/pilot/evaluation/scores.json        # top-level агрегат run × criterion
```

- `<judge_slug>` = `model_key` из [configs/models.yaml](../../../configs/models.yaml) (например `claude-opus-4.7-low`).
- `<run_name>` совпадает с именем директории в `translating/<bucket>/`. Bucket в путь `evaluation/` **не входит** — `run_name` уникален в пределах всего `translating/`.

### `<criterion>_scores.jsonl` (per-judge, сырая форма)

Одна строка на параграф. Совместимо с прежним форматом, плюс поле `judge`:

```json
{"id": 42, "source": "...", "translated": "...",
 "judge": "claude-opus-4.7-low", "variant": "full",
 "score": 8, "llm_report": "...markdown report..."}
```

`score` ∈ {0..10, `null`, `-1`}, где `null` — skipped (sentinel или TRANSLATION FAILED), `-1` — LLM/parse error.

### `merged_scores.jsonl` (сводный)

Одна строка на параграф, все критерии и судьи в ширину:

```json
{
  "id": 42,
  "source": "...",
  "translated": "...",
  "accuracy":      {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 8, "gemini-3.1-pro-low": 7, "gpt-5.5-low": 8}},
  "terminology":   {"avg": 8.0, "by_judge": {...}},
  "cultural":      {"avg": 7.2, "by_judge": {...}},
  "fluency":       {"avg": 8.4, "by_judge": {...}},
  "style":         {"avg": 7.8, "by_judge": {...}},
  "consistency":   {"avg": 7.6, "by_judge": {...}},
  "factcheck":     {"f1": 0.91, "p": 0.95, "r": 0.87, "judge": "gpt-5.4-mini-low"}
}
```

- `avg` — среднее по судьям, исключая `null` и `-1`. Если все исключены — `"avg": null`.
- `merged_scores.jsonl` **всегда пересобирается** из сырых JSONL на финальном шаге — это derived view, не источник истины.

### `scores.json` (top-level агрегат)

```json
{
  "large/claude-opus-4.7-low_par_by_par": {
    "accuracy":    {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 7.5, "gemini-3.1-pro-low": 7.4, "gpt-5.5-low": 7.9}},
    "terminology": {...},
    "cultural":    {...},
    "fluency":     {...},
    "style":       {...},
    "consistency": {...},
    "factcheck":   {"f1_avg": 0.89}
  }
}
```

Ключ — `<bucket>/<run_name>` (с bucket'ом, чтобы видно было профиль). Удаление и перезапись — поведение совпадает с тем, что описано в [pilot_interfaces_agreement.md](../../pilot_interfaces_agreement.md).

### Sentinel handling

Централизованно, **до** диспатча в стратегию:

| Маркер в source | Действие | `score` | `llm_report` |
|---|---|---|---|
| `* * *` | skip, без LLM-вызова | `null` | `"skipped: marker"` |
| `picture` (case-insensitive) | skip, без LLM-вызова | `null` | `"skipped: marker"` |
| `[TRANSLATION FAILED]` | skip + warning в stderr | `null` | `"skipped: translation_failed"` |

Строка в JSONL пишется — чтобы выравнивание `id` сохранилось. В `avg` не учитывается.

### Idempotency / resume

- Если `<criterion>_scores.jsonl` уже содержит строку с заданным `id` — skip (за исключением `score == -1`, которые перетираются).
- CLI-флаг `--force` перезаписывает всё.
- `merged_scores.jsonl` всегда пересобирается из сырых JSONL.

### Failure semantics

- **Network/timeout/parse error** на одном параграфе → строка пишется с `score: -1` и `llm_report` = сырой ответ. Остальные параграфы продолжают независимо (паттерн партиал-сакцеса как в Stage 03).
- **Один судья падает целиком** (например auth-error) → пишется warning, `(run, judge)` пара пропускается, остальные судьи продолжают. В `merged_scores.jsonl` отсутствующий судья опускается в `by_judge`.
- **`factcheck.enabled: false`** → каталог `factcheck/` не создаётся; поле `factcheck` отсутствует в `merged_scores.jsonl` и `scores.json`.

### Concurrency

- Глобальный `max_concurrency` (default 64) — общий бюджет async-задач.
- Per-judge semaphore = `max_concurrency / len(judges)` по умолчанию, override через `judges[i].max_concurrency`.

Защищает от rate-limit'а одного провайдера: 5 судей делят бюджет, OpenRouter не ловит 429.

## Конфиг

### Схема

```yaml
# configs/scoring/<profile>.yaml

base_dir: data/pilot                     # все пути ниже отсчитываются отсюда
translations_subdir: translating         # base_dir / translations_subdir
evaluation_subdir: evaluation            # base_dir / evaluation_subdir
prompts_root: prompts/03_scoring         # repo-relative

prompts_variant: full                    # default: old | compact | full
max_concurrency: 64

factcheck:
  enabled: true
  judge: gpt-5.4-mini-low                # фиксированный, не из judges

judges:                                  # список model_key из configs/models.yaml
  - model: claude-opus-4.7-low
    # variant: full                      # override опционально (default = prompts_variant)
    # max_concurrency: 16                # override опционально
  - model: gemini-3.1-pro-low
  - model: gpt-5.5-low

runs:                                    # явный список <bucket>/<run_name>
  - large/claude-opus-4.7-low_par_by_par
  - large/gpt-5.5-low_par_by_par
  - large/gemini-3.1-pro-low_par_by_par
```

### Pydantic-модели

Расширить [src/palimpsest/config.py](../../../src/palimpsest/config.py):

```python
class JudgeConfig(BaseModel):
    model: str                           # ключ из models.yaml
    variant: Literal["old", "compact", "full"] | None = None
    max_concurrency: int | None = None

class FactcheckConfig(BaseModel):
    enabled: bool = True
    judge: str = "gpt-5.4-mini-low"

class ScoringConfig(BaseModel):           # ПЕРЕПИСАТЬ существующую
    base_dir: Path
    translations_subdir: str = "translating"
    evaluation_subdir: str = "evaluation"
    prompts_root: Path = Path("prompts/03_scoring")
    prompts_variant: Literal["old", "compact", "full"] = "full"
    max_concurrency: int = 64
    factcheck: FactcheckConfig = FactcheckConfig()
    judges: list[JudgeConfig]
    runs: list[str]                       # формат "<bucket>/<run_name>"
```

## Файлы

| Файл | Действие | Назначение |
|---|---|---|
| [src/palimpsest/scoring.py](../../../src/palimpsest/scoring.py) | Переписать | Public API: `run_scoring(cfg: ScoringConfig)`. Внутри — диспатчер. |
| [src/palimpsest/config.py](../../../src/palimpsest/config.py) | Расширить | Новая `ScoringConfig` + `JudgeConfig` + `FactcheckConfig`. |
| [scripts/03_translation_scoring.py](../../../scripts/03_translation_scoring.py) | Переписать | Тонкий CLI: `python -m scripts.03_translation_scoring --config configs/scoring/<profile>.yaml`. |
| configs/scoring/large-low.yaml | Создать | Профиль large-low: opus-4.7-low, gemini-3.1-pro-low, gpt-5.5-low. |
| configs/scoring/small-low.yaml | Создать | Профиль small-low: sonnet-4.6-low, gemini-3.1-flash-lite-low, gpt-5.4-mini-low. |
| configs/scoring/smoke.yaml | Создать | Smoke-тест: 1 run × 1 судья × variant=compact. |
| [tests/test_scoring.py](../../../tests/) | Создать | TDD: парсинг конфига, маршрутизация критериев, sentinel-handling, idempotency, merged builder. |
| [docs/stages/03_scoring.md](../../../docs/stages/) | Обновить | Sync rule (CLAUDE.md). |
| [docs/pilot_interfaces_agreement.md](../../pilot_interfaces_agreement.md) | Обновить | Финализировать `evaluation/<run_name>/<judge>/...` layout. |

Старый `configs/scoring.yaml` (в корне `configs/`) **удаляется** — заменяется на profile-файлы в `configs/scoring/`.

## Поток исполнения

1. CLI читает yaml → `ScoringConfig` (pydantic).
2. Resolver строит план: для каждой пары `(run, judge)` — список критериев, нужных promptов, путей в output. Plus отдельный план для factcheck (`run × factcheck-judge`).
3. Параллельно для каждой пары:
   - **legacy** (variant=old): 6 параллельных LLM-вызовов на параграф, по одному ответу на критерий.
   - **consolidated** (variant=compact|full): 2 LLM-вызова (faithfulness, english_quality), парсим JSON, маршрутизируем 3+3 критерия в соответствующие JSONL.
   - **factcheck**: `FactExtractor(ru) + FactExtractor(en) + FactOverlap.judge` → F1 в `factcheck_scores.jsonl`.
4. Sentinel-handling — централизованный, до диспатча.
5. Idempotent write: skip существующих `id` в JSONL, кроме `score == -1`.
6. После всех JSONL — пересборка `merged_scores.jsonl` + `scores.json`.

## Smoke и final-конфиги

### Smoke (`configs/scoring/smoke.yaml`)

Должен запускаться за <1 минуту, валидирует контракт перед финальным прогоном.

```yaml
base_dir: data/pilot
prompts_variant: compact
max_concurrency: 8
factcheck: { enabled: false }
judges: [{ model: claude-haiku-4.5 }]
runs: [large/claude-opus-4.7-low_par_by_par]
# CLI: --max-paragraphs 5  для ограничения скрипта
```

### Final large-low (`configs/scoring/large-low.yaml`)

3 крупных судьи в low-effort режиме. Variant=full (мощные модели справятся с 3k промптом).

```yaml
prompts_variant: full
factcheck: { enabled: true, judge: gpt-5.4-mini-low }
judges:
  - { model: claude-opus-4.7-low }
  - { model: gemini-3.1-pro-low }
  - { model: gpt-5.5-low }
runs:
  - large/claude-opus-4.7-low_par_by_par
  - large/gpt-5.5-low_par_by_par
  - large/gemini-3.1-pro-low_par_by_par
  # пользователь дополняет список под свои интересы
```

### Final small-low (`configs/scoring/small-low.yaml`)

3 маленьких судьи. Variant=compact (компактные промпты, чтобы не перегружать контекст).

```yaml
prompts_variant: compact
factcheck: { enabled: true, judge: gpt-5.4-mini-low }
judges:
  - { model: claude-sonnet-4.6-low }
  - { model: gemini-3.1-flash-lite-low }
  - { model: gpt-5.4-mini-low }
runs:
  - small/claude-haiku-4.5_par_by_par
  - small/gemini-3.1-flash-lite-low_par_by_par
  - small/gpt-5.4-mini-low_par_by_par
  - small/qwen3.6-flash_par_by_par
```

## Точки риска

- **JSON-парсинг ответов от 5+ моделей.** Каждый провайдер по-своему оборачивает в ```json или добавляет prose до/после. Существующий `parse_json_response()` в `scoring.py` надо расширить + покрыть тестами.
- **Memory/IO при 60+ runs.** `merged_scores.jsonl` строится в памяти — на 549 параграфов × 6 критериев × 5 судей это ~16k значений на run, нормально. Top-level `scores.json` собирается из всех `merged`-файлов — линейно по числу runs.
- **Snapshot промптов в `meta.json`** — чтобы прогон был воспроизводимым (как `config.json` для Stage 03). Без этого диф между прогонами с разными версиями compact-промпта не отследить.

## Status

Spec written. Implementation pending writing-plans skill invocation after user review.
