# Scoring — subsets, output redesign, consistency legacy, factcheck off

Up-link: [docs/pipeline.md](../../pipeline.md). Связанные: [2026-05-14-scoring-v1-only-design.md](2026-05-14-scoring-v1-only-design.md), [docs/stages/03_scoring.md](../../stages/03_scoring.md).

## Контекст

Stage 03 запустился, оценочный пайплайн рабочий. Узкое место — стоимость прогона: один перевод × 500 параграфов × 6 критериев × N судей + factcheck ≈ слишком много API-вызовов для широкого исследования.

Дополнительно по ходу первых прогонов выяснилось:
- `consistency` как per-paragraph criterion бесполезен (по самой природе — consistency осмысленна только cross-paragraph).
- Factcheck показал, что современные модели хорошо сохраняют факты — отдельная стадия дороже своей сигнальной ценности на пилоте.
- Текущий output (`<run>/<judge>/criterion.jsonl` + `merged_scores.jsonl` + top-level `scores.json`) не отделяет независимые оценки разных `prompts_variant` и не даёт reader-friendly артефакта в стиле тех, что лежат у Данила (`data/pilot/evaluation/qwen_par_by_par/scores.jsonl`).

Эта спека покрывает четыре связанных изменения и описывает их совместно, потому что output redesign трогает path-helpers, которыми пользуются и subset, и factcheck-off, и variant-split.

## Goals

1. **Subset параграфов**: `ScoringConfig.paragraph_subset: str | None`. Когда задано — оцениваются только параграфы из subset'а. Subset живёт в `data/pilot/scoring_subsets/<name>.json`. Resume естественно работает: переход compact → full не пере-оценивает уже сделанное.
2. **`consistency` в `_legacy/`**: файл `prompts/03_scoring/v1/consistency.md` переезжает в `prompts/03_scoring/_legacy/consistency.md`. Dispatcher v1 видит 5 критериев. Existing JSONL не трогаем.
3. **Factcheck off by default**: `FactcheckConfig.enabled: bool = False`. Существующие 9 YAML'ов обновляются. Функционал не удаляется (`enabled: true` остаётся рабочим).
4. **Output redesign**: variant попадает в путь (`<run>/<variant>/...`). Два новых derived-артефакта: `comparison.jsonl` (judges side-by-side) и `reports/<judge>.jsonl` (full llm_report по criterion'ам). `merged_scores.jsonl` и top-level `scores.json` удаляются.

## Non-goals

- Builder-утилиту для subset'а (`scripts/03_build_subset.py`) не пишем — пользователь собирает JSON ad-hoc в Jupyter.
- Top-level rollup всех runs остаётся вне stage 03 (Excel, notebook).
- Backward-compat для старого layout — миграция явная one-shot.
- Per-judge или per-criterion subset'ы — single `paragraph_subset` field на весь run.
- Удаление факт-функционала — остаётся включаемым.
- Поддержка `_legacy/` диспетчером — папка чисто архивная.
- Изменение схемы raw `<criterion>_scores.jsonl` и `parse_failures.jsonl` — schema остаётся.

## Design

### A. Subset параграфов

**Файл `data/pilot/scoring_subsets/<name>.json`** — минимальная схема плюс free-form metadata:

```json
{
  "name": "complex_150",
  "description": "free-form: how / why this subset was built",
  "paragraph_ids": [3, 12, 18, 47, 89, 102, 156]
}
```

Любые дополнительные ключи (`source_runs`, `created_at`, `notes` и т.д.) loader пропускает (`extra="allow"`). Они для человека.

**Pydantic-модель** `Subset` (новый модуль `src/palimpsest/scoring_subsets.py` или подмодуль `palimpsest.scoring.subsets` — фикс выбираем в плане реализации):

```python
class Subset(BaseModel):
    name: str
    description: str = ""
    paragraph_ids: list[int]
    model_config = ConfigDict(extra="allow")
```

**Loader** `load_subset(name: str, base_dir: Path) -> Subset`:
- Резолвит путь `base_dir / "scoring_subsets" / f"{name}.json"`.
- Парсит через `Subset.model_validate_json(...)`.
- `FileNotFoundError` → ошибка с указанием ожидаемого пути.

**ScoringConfig** (`palimpsest.config`):

```python
class ScoringConfig(BaseModel):
    ...
    paragraph_subset: str | None = None
```

**Resume-семантика — никаких изменений в `load_existing_ids`**. В `_score_run_for_judge` пары фильтруются перед циклом:

```python
if cfg.paragraph_subset:
    subset = load_subset(cfg.paragraph_subset, cfg.base_dir)
    ids_in_run = {p.id for p in pairs}
    bad = [pid for pid in subset.paragraph_ids if pid not in ids_in_run]
    if bad:
        raise ValueError(f"subset {subset.name!r} contains ids missing in run {run!r}: {bad[:5]}...")
    keep = set(subset.paragraph_ids)
    pairs = [p for p in pairs if p.id in keep]
```

Те id, что уже на диске, пропускаются текущей `load_existing_ids` логикой. При переходе compact → full те же 150 параграфов уже там, дополнительные доберутся.

### B. consistency → `_legacy/`

Новая структура:

```
prompts/03_scoring/
├── v1/
│   ├── accuracy.md
│   ├── cultural.md
│   ├── fluency.md
│   ├── style.md
│   └── terminology.md       (5 файлов)
└── _legacy/
    └── consistency.md       (хранится, dispatcher не видит)
```

- `load_prompts(prompts_root, variant)` без изменений — работает с `prompts_root / variant`, `_legacy/` за его пределами.
- Existing `data/pilot/evaluation/<run>/<judge>/consistency_scores.jsonl` НЕ удаляются — historical record. При пересборке `comparison.jsonl` и `reports/<judge>.jsonl` они игнорируются (criterion-список = `list(prompts.keys())`).

### C. Factcheck off by default

```python
class FactcheckConfig(BaseModel):
    enabled: bool = False  # было True
    judge: str = "gpt-5.4-mini-low"
```

В существующих 9 YAML'ах (`configs/scoring/*.yaml`): либо явно `factcheck: {enabled: false}`, либо секция удаляется полностью (раз дефолт false — отсутствие = выключено). Выбор в плане — выбрать «удалить секцию» для чистоты.

`scoring.py:run_scoring` уже корректно skip'ит factcheck когда `cfg.factcheck.enabled is False` — изменений в runtime-коде не требуется (только дефолт + YAML).

### D. Output контракт

#### Layout

```
data/pilot/evaluation/<run>/
├── v1/                                  ← variant scope
│   ├── <judge>/
│   │   ├── accuracy_scores.jsonl        ← raw, schema unchanged
│   │   ├── terminology_scores.jsonl
│   │   ├── cultural_scores.jsonl
│   │   ├── fluency_scores.jsonl
│   │   ├── style_scores.jsonl
│   │   ├── parse_failures.jsonl         ← raw, schema unchanged
│   │   └── meta.json                    ← + paragraph_subset
│   ├── reports/                         ← NEW derived
│   │   └── <judge>.jsonl
│   └── comparison.jsonl                 ← NEW derived
└── factcheck/                           ← outside variant (shared check)
    └── factcheck_scores.jsonl
```

Удаляются:
- `<run>/merged_scores.jsonl` (заменён на `comparison.jsonl` с более богатой схемой).
- `evaluation/scores.json` (top-level rollup делается вне stage 03).

#### Schemas

**`<judge>/<criterion>_scores.jsonl`** — без изменений:

```jsonl
{"id": 0, "score": 10, "llm_report": {...full parsed dict...}, "ts": "..."}
{"id": 1, "score": null, "llm_report": "skipped: marker '* * *'", "ts": "..."}
{"id": 2, "score": null, "llm_report": "persistent_parse_failure: see parse_failures.jsonl", "ts": "..."}
```

**`<judge>/parse_failures.jsonl`** — без изменений.

**`<judge>/meta.json`** — расширяется полем `paragraph_subset`:

```json
{
  "judge": "gpt-5.5-low",
  "variant": "v1",
  "paragraph_subset": "complex_150",
  "criteria": ["accuracy", "cultural", "fluency", "style", "terminology"],
  "ts_start": "2026-05-14T15:30:00Z",
  "ts_end":   "2026-05-14T15:42:18Z"
}
```

`paragraph_subset: null` когда оценивали весь ран.

**`<run>/<variant>/reports/<judge>.jsonl`** (NEW):

```jsonl
{
  "id": 12,
  "source": "...",
  "translated": "...",
  "accuracy":    {"identified_issues": [...], "criteria_assessment": {...}, "summary": "...", "final_score": 8},
  "terminology": {...},
  "cultural":    {...},
  "fluency":     {...},
  "style":       {...}
}
```

- Один файл = один судья.
- Каждый criterion-блок = `llm_report` из raw JSONL row, или `null` если `score == null` (skip / terminal fail).
- Включает union всех `id`, по которым хоть один criterion JSONL row у этого судьи есть.
- Sort by `id` ascending.

**`<run>/<variant>/comparison.jsonl`** (NEW):

```jsonl
{
  "id": 12,
  "source": "...",
  "translated": "...",
  "scores": {
    "gpt-5.5-low":         {"accuracy": 8, "terminology": 9, "cultural": 7, "fluency": 9,  "style": 8},
    "claude-opus-4.7-low": {"accuracy": 7, "terminology": 9, "cultural": null, "fluency": 9, "style": 8},
    "gemini-3.1-pro-low":  {"accuracy": 9, "terminology": null, "cultural": 8, "fluency": 10, "style": 9}
  },
  "factcheck": {"score": 0.94, "errors": []}
}
```

- `scores: {judge: {criterion: int | null}}` — все judges из `cfg.judges`, все criterion'ы variant'а (`list(prompts.keys())`). `null` где параграф не оценён или terminal-null.
- `factcheck`: если `factcheck.enabled` был true — структура из `factcheck/factcheck_scores.jsonl` row для этого id; иначе ключ отсутствует. Точный shape берётся при реализации из `palimpsest.factcheck.models.FactcheckResult`.
- Включает union всех `id`, по которым хоть один судья хоть один criterion записал.
- Sort by `id` ascending.

**`<run>/factcheck/factcheck_scores.jsonl`** — без изменений, остаётся outside variant.

#### Когда пересобираются derived-артефакты

После каждого `run_scoring(cfg)` (в конце, как сейчас merged):
1. `<variant>/comparison.jsonl` — full rebuild из raw `<judge>/<criterion>_scores.jsonl` + `factcheck/factcheck_scores.jsonl`.
2. `<variant>/reports/<judge>.jsonl` — full rebuild из raw `<judge>/<criterion>_scores.jsonl` per judge.

Никакого incremental update — derived всегда regenerable из raw.

## Interface changes

### paths.py

Сигнатуры — добавляется `variant: str` к judge-уровню:

```python
def variant_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / variant

def judge_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str) -> Path:
    return variant_dir(base_dir, evaluation_subdir, run, variant) / judge

def criterion_jsonl(base_dir, evaluation_subdir, run, variant, judge, criterion) -> Path: ...
def parse_failures_jsonl(base_dir, evaluation_subdir, run, variant, judge) -> Path: ...
def reports_dir(base_dir, evaluation_subdir, run, variant) -> Path: ...
def report_jsonl(base_dir, evaluation_subdir, run, variant, judge) -> Path: ...
def comparison_jsonl(base_dir, evaluation_subdir, run, variant) -> Path: ...
```

Удаляются: `merged_jsonl`, `scores_json`.

Без изменений: `evaluation_run_dir`, `factcheck_dir`, `factcheck_jsonl`.

### scoring.py

- `_score_run_for_judge(cfg, run, judge, prompts, variant, ...)` — все path-helpers вызываются с variant'ом; `meta.json` дополняется `paragraph_subset` полем.
- Pairs-фильтрация по subset вставляется в начало `_score_run_for_judge` (см. блок кода в разделе A выше).
- `build_merged_jsonl` и `build_aggregate_scores` **удаляются**.
- Появляются `build_comparison_jsonl(cfg, run, prompts_keys)` и `build_judge_reports(cfg, run, prompts_keys)` — оба читают raw criterion JSONL, пишут derived. Sort by id ascending. Атомарная запись через `tmp + os.replace` (см. лессон в [docs/analysis.md A2/C7](../../analysis.md)).
- `run_scoring` после всех judge-tasks + factcheck:
  ```python
  for run in cfg.runs:
      build_comparison_jsonl(cfg, run, prompts_keys)
      build_judge_reports(cfg, run, prompts_keys)
  ```

### config.py

- `FactcheckConfig.enabled` default `False`.
- `ScoringConfig.paragraph_subset: str | None = None`.
- Soft-warning validator на `paragraph_subset` (если задан, но файла нет — print stderr / `warnings.warn`). Hard error поднимается в loader на этапе `_score_run_for_judge`.

## Migration

**Скрипт `scripts/03_migrate_evaluation_to_variant.py`** (one-shot, удаляется после применения):

Принимает explicit список run'ов в аргументах (чтобы не задеть Данилов archive `qwen_par_by_par/` и `qwen_pilot/`). Никакого автодискаверинга «всех run'ов под `evaluation/`».

Использование:
```bash
python scripts/03_migrate_evaluation_to_variant.py \
    --evaluation-dir data/pilot/evaluation \
    --run large/claude-opus-4.7-low_par_by_par \
    --run large/gemini-3.1-pro-low_par_by_par \
    --run large/gpt-5.5-low_par_by_par \
    --run local/qwen_par_by_par \
    ...
```

Алгоритм для каждого переданного `<run>`:
1. В `<run>/` находим subdirs, не равные `factcheck`, `v1`, `v2` — это judges под старым layout'ом.
2. `git mv <run>/<judge>/ <run>/v1/<judge>/` для каждого.
3. Если `<run>/merged_scores.jsonl` существует — `git rm`.
4. Логи в stdout.

После прохода по всем переданным run'ам — если `evaluation/scores.json` существует, `git rm` его.

Архив Данила (`evaluation/qwen_par_by_par/`, `evaluation/qwen_pilot/`) не передаётся в `--run` — остаётся нетронутым как historical reference.

После применения миграции:
- Скрипт + `scripts/03_cleanup_minus_one.py` (тоже одноразовый, с прошлой миграции) удаляются из репо в том же PR.

## Tests

Новые:
- `tests/test_scoring_subsets.py` — Subset pydantic parse, free-form metadata tolerated, missing file → FileNotFoundError, malformed JSON → ValidationError.
- `tests/test_scoring_subset_filter.py` — full → compact filter on pairs, out-of-range hard error в `_score_run_for_judge`.
- `tests/test_comparison_jsonl.py` — multi-judge build, `null` где criterion отсутствует у конкретного judge'а, factcheck включён/выключен, sort by id, idempotent rebuild.
- `tests/test_reports_jsonl.py` — full report per judge, `null` criterion-блок при `score == null`, idempotent rebuild.

Обновляются:
- `tests/test_scoring_dispatcher.py` — paths с `v1/` subpath.
- `tests/test_scoring_resume.py` — то же.
- `tests/conftest.py` — fixtures получают `variant` параметр.

Удаляется:
- `tests/test_*merged*.py` если был.

## Breaking changes (резюме)

| Что | Чем заменяется |
|---|---|
| `evaluation/<run>/<judge>/` | `evaluation/<run>/v1/<judge>/` |
| `evaluation/<run>/merged_scores.jsonl` | `evaluation/<run>/v1/comparison.jsonl` (богаче) |
| `evaluation/scores.json` | удалён (Excel/notebook вручную) |
| `factcheck.enabled: true` по умолчанию | `false` по умолчанию |
| `consistency` критерий | в `_legacy/`, не вычисляется |

## Rollout

1. Code + paths + config changes под TDD (по `superpowers:test-driven-development`).
2. Test suite зелёный (включая обновлённые dispatcher/resume).
3. Запустить `scripts/03_migrate_evaluation_to_variant.py` для существующих `evaluation/`.
4. Прогон `scripts/03_scoring_smoke.sh` на 50 параграфах для верификации нового layout.
5. Удалить migration script + `03_cleanup_minus_one.py`.
6. Обновить `docs/stages/03_scoring.md`, `docs/pipeline.md`, `docs/known_issues.md`.
7. PR в `feat/chunking-format`.

## Decisions log

- **S1**: Subset живёт в `data/pilot/scoring_subsets/<name>.json` (отдельная папка под `data/pilot/`, аналогично `chunking/`).
- **S2**: Subset shape — `{name, description, paragraph_ids}` + free-form metadata (`extra="allow"`).
- **S3**: Привязка subset'а к scoring — `paragraph_subset: <name>` или отсутствует / null. Только имя, не путь.
- **S4**: Builder для subset'ов не пишем — ad-hoc через Jupyter.
- **S5**: `consistency.md` → `prompts/03_scoring/_legacy/` (вне любого variant'а). Existing JSONL не удаляются.
- **S6**: `FactcheckConfig.enabled` default `False`. Из YAML'ов секцию удаляем (раз false = отсутствие).
- **S7**: Output получает variant subpath: `<run>/<variant>/<judge>/...`. Factcheck остаётся outside variant.
- **S8**: Два derived-артефакта на variant — `comparison.jsonl` (numeric side-by-side) + `reports/<judge>.jsonl` (full llm_report). `merged.jsonl` + top-level `scores.json` удаляются.
- **S9**: Migration через one-shot `scripts/03_migrate_evaluation_to_variant.py`, скрипт удаляется после применения.
- **S10**: Subset out-of-range — hard error при загрузке pairs. Subset с несуществующим именем — hard error в loader, soft warning в pydantic validator на момент `load_scoring`.
