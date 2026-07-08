# Translation Comparison Viewer — Design

Up-link: [docs/superpowers/](../) · [CLAUDE.md](../../../CLAUDE.md)

## Purpose

Веб-инструмент для эксперта, чтобы проверять параграф-в-параграф переводы LLM большой Советской энциклопедии и решения LLM-as-a-judge. Заменяет чтение длинных JSONL и markdown-вьюх.

Не коммерческий продукт. Single-user, разворачивается на личном сервере под своим доменом, HTTPS. Источник истины — `data/pilot/evaluation/<run>/<variant>/`. Viewer ничего не пишет, только читает.

## Scope

**MVP**:
- Сравнение двух переводов (A и B) одного абзаца по одному и тому же `gpt-5.5-low`-судье.
- 542 абзаца пилота, 5 критериев: `accuracy`, `terminology`, `fluency`, `cultural`, `style`.
- На каждый абзац: исходник RU, два перевода EN, по каждому критерию `final_score` (1–10) и `summary` (2–4 предложения).
- Подбор пары (A, B) через каталог.
- Свернутая по умолчанию правая панель с агрегатной аналитикой.

**Не MVP** (см. § Out of scope).

## Architecture

```
┌─────────────────────────────────────┐
│  Caddy (HTTPS, :443)                │   auto-Let's-Encrypt
│  reverse_proxy → viewer:8000        │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  FastAPI / uvicorn (:8000)          │
│  GET  /api/datasets                 │   catalog
│  GET  /api/dataset?a=…&b=…          │   joined LLM-Comparator JSON
│  GET  /            → index.html     │   built dist/ статика
│  GET  /static/*    → JS/CSS/svg     │
└──────────────┬──────────────────────┘
               │ reads
┌──────────────▼──────────────────────┐
│  EVAL_ROOT (default data/pilot/     │
│           evaluation/)              │
│   └── <run>/<variant>/              │
│        comparison.jsonl             │
│        reports/<judge>.jsonl        │
└─────────────────────────────────────┘
```

Один процесс FastAPI. Без БД, без кэша — read-on-demand из JSONL (542 строки × 2 файла = быстро). Корень данных конфигурируется через env var `EVAL_ROOT`. Локально работает без Caddy на `http://localhost:8000`.

## Repository layout

Viewer — самостоятельное приложение, не stage pipeline'а:

```
gse-translation/
├── src/palimpsest/          ← pipeline без изменений
├── tests/viewer/            ← pytest подбирает по корневому config'у
│   ├── fixtures/            ← мини-JSONL
│   ├── test_adapter.py
│   └── test_catalog.py
├── viewer/
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── main.py          ← FastAPI app
│   │   ├── adapter.py       ← JSONL → LLM-Comparator JSON
│   │   ├── catalog.py       ← скан EVAL_ROOT
│   │   └── paths.py         ← PathSpec parsing + validation
│   ├── frontend/            ← форк PAIR-code/llm-comparator
│   │   ├── client/          ← Lit + MobX, изменённые компоненты
│   │   ├── build.mjs
│   │   ├── package.json
│   │   └── …
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── README.md
└── …
```

### Python packaging (монорепа)

Один корневой `pyproject.toml` остаётся источником истины. `fastapi`, `uvicorn` уже в main-зависимостях (`[project] dependencies`), `pydantic` подтягивается транзитивно через fastapi — viewer ничего нового в Python-deps не добавляет.

Код viewer'а — обычный Python-пакет под `viewer/backend/` (`__init__.py`, импорт через `viewer.backend.main:app`). Корневой `pyproject.toml` должен включать `viewer` в `packages` (или эквивалент в hatchling) — добавим в плане. Никакого отдельного `viewer/backend/pyproject.toml`.

Тесты viewer'а лежат в `tests/viewer/`, общий pytest-runner их подхватывает — `testpaths = ["tests"]` уже сконфигурирован.

Данные `data/pilot/evaluation/` остаются общими: pipeline-стадии пишут, viewer читает — single source of truth. В production-контейнере viewer'а исходные jsonl монтируются как read-only volume (см. § Deployment).

## Data sources

Viewer читает строго два типа файлов из единого корня `EVAL_ROOT` (default `data/pilot/evaluation/` относительно корня репо). Файлы — продукт [Stage 03 Scoring](../../stages/03_scoring.md), формат фиксирован и описан там же.

### Что читаем

```
EVAL_ROOT/
  └── <run_name>/                          ← напр. "qwen_edited_par_by_par"
        └── <variant>/                     ← напр. "v1", "v2"
              ├── comparison.jsonl         ← обязательно
              ├── reports/
              │     └── <judge>.jsonl      ← обязательно (≥ 1 файл)
              ├── <judge>/                 ← raw, viewer не читает
              │     ├── accuracy_scores.jsonl
              │     ├── …
              │     └── meta.json
              └── parse_failures.jsonl     ← raw, viewer не читает
```

`<run_name>` — имя translation-run'а (содержит модель и режим chunking'а). `<variant>` — версия scoring-промптов. `<judge>` — модель-судья. Возможные значения этих токенов viewer не валидирует против белого списка — берёт всё, что найдёт через glob.

### Что НЕ читаем (важно для безопасности и YAGNI)

- `data/pilot/translating/<model>/translation.md` — полная markdown-простыня перевода. **Не нужна**: `comparison.jsonl` уже содержит `source` и `translated` пара-по-параграфу.
- `data/raw/` — запрещено по [CLAUDE.md](../../../CLAUDE.md#hard-invariants) (Hard Invariant #7, #10).
- `data/interim/` — большие markdown-книги, не нужны.
- `<run>/<variant>/<judge>/*_scores.jsonl` — сырой output Stage 03 по критериям. Те же данные доступны через `reports/<judge>.jsonl` (derived-сводка, уже объединённая).
- `<run>/<variant>/<judge>/meta.json` — промпты, токены, cost. На MVP не используем (можем добавить в каталог "scored at" / "cost" позже).
- `<run>/factcheck/factcheck_scores.jsonl` — отдельная стадия, не показываем.

### Схема `comparison.jsonl`

Тонкий per-paragraph join. Одна строка = один параграф. Используется для: source RU, translated EN, быстрый доступ к score'ам без чтения тяжёлого rationale.

```json
{
  "id": 0,
  "source": "МЕСОПОТАМИЯ",
  "translated": "Mesopotamia",
  "scores": {
    "gpt-5.5-low": {
      "accuracy":    10,
      "cultural":    10,
      "fluency":     10,
      "style":        9,
      "terminology": 10
    }
  }
}
```

- `id: int` — индекс параграфа (0-based, монотонный).
- `source: str` — оригинал на русском, markdown.
- `translated: str` — перевод на английский, markdown. Если scoring упал, может быть `"[TRANSLATION FAILED]"` или содержать sentinel-маркеры.
- `scores: dict[judge_name, dict[criterion, int | null]]` — итоговый final_score 1–10 на каждый критерий. `null` = terminal-null после 3 retry'ев в Stage 03.

### Схема `reports/<judge>.jsonl`

Толстый per-paragraph rationale от одного судьи. Одна строка = один параграф. Используется для: rationale summary (на MVP — только `summary` и `final_score`).

```json
{
  "id": 0,
  "source": "МЕСОПОТАМИЯ",
  "translated": "Mesopotamia",
  "accuracy": {
    "identified_issues": [],
    "criteria_assessment": {
      "factual_integrity":      "…",
      "proper_nouns":           "…",
      "completeness":           "…",
      "semantic_fidelity":      "…",
      "terminological_accuracy":"…"
    },
    "summary": "The translation accurately renders the Russian title…",
    "final_score": 10
  },
  "cultural":    { "cultural_inventory": [...], "criteria_assessment": {...},
                   "summary": "…", "final_score": 10, … },
  "fluency":     { "source_structure_note": "…", "criteria_assessment": {...},
                   "summary": "…", "final_score": 10, … },
  "style":       { "criteria_assessment": {...}, "summary": "…", "final_score": 9, … },
  "terminology": { "identified_terms": [...], "criteria_assessment": {...},
                   "summary": "…", "final_score": 10, … }
}
```

Для каждого критерия структура слегка отличается (у `cultural` есть `cultural_inventory`, у `fluency` — `source_structure_note`, у `terminology` — `identified_terms`), но три ключа гарантированы во всех пяти:
- `summary: str` — 2–4 предложения. На MVP — единственное rationale-поле, попадающее в UI.
- `final_score: int | null` — 1–10 либо `null`.
- `criteria_assessment: dict[subkey, str]` — субкритерии, **на MVP не читаем**.

### Конкретный пример пути для тестового прогона

```
data/pilot/evaluation/qwen_edited_par_by_par/v1/comparison.jsonl       ← 542 строки
data/pilot/evaluation/qwen_edited_par_by_par/v1/reports/gpt-5.5-low.jsonl
data/pilot/evaluation/qwen_edited_par_by_par/v2/comparison.jsonl       ← 542 строки (с улучшенными prompt'ами)
data/pilot/evaluation/qwen_edited_par_by_par/v2/reports/gpt-5.5-low.jsonl
data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/comparison.jsonl
data/pilot/evaluation/claude-opus-4.7_par_by_par/v1/reports/gpt-5.5-low.jsonl
```

`PathSpec` для UI и API — `<run>/<variant>/<judge>`. Пример сравнения:
- `a = qwen_edited_par_by_par/v1/gpt-5.5-low`
- `b = claude-opus-4.7_par_by_par/v1/gpt-5.5-low`

### Path resolution и безопасность

`PathSpec`-параметры в URL приходят от пользователя → потенциальная атака `../../etc/passwd`. Валидация **строгая**:

1. Каждый сегмент `PathSpec` матчится регулярке `^[A-Za-z0-9_.\-]+$`. Сегменты разделены `/`.
2. Должно быть ровно три сегмента: `run / variant / judge`.
3. После резолва (`(EVAL_ROOT / run / variant).resolve()`) проверяем, что путь стартует с `EVAL_ROOT.resolve()` — защита от symlink-побега и `..`.
4. Файлы `comparison.jsonl` и `reports/<judge>.jsonl` должны существовать; иначе 400.
5. Никаких glob'ов на user-input. `<judge>.jsonl` строится конкатенацией valid'ированного `judge` сегмента + `.jsonl`.

### File I/O политика

- **Чтение полностью в память.** `comparison.jsonl` ~542 строки × <1KB = <600KB; `reports/<judge>.jsonl` ~542 × ~20KB = ~12MB. По два таких файла на запрос. Стрим не нужен, json-parse строки за строкой через `json.loads(line)`.
- **Малформенная строка** → log error с `id` (если удалось распарсить) и `path`, **пропускаем строку**, не падаем. После полной обработки — если в финальном JSON < N/2 параграфов, возвращаем 500 с описанием.
- **Кодировка** — UTF-8 строго; `errors='strict'`. Файлы pipeline'а гарантированно UTF-8 (см. Stage 03).
- **Кэш** — нет. На каждый GET читаем JSONL заново. 542 параграфа × 2 файла парсятся ≤ 200ms на средней машине, для single-user OK. Добавим LRU-кэш по `(path_a, path_b, mtime_a, mtime_b)`, если будут жалобы на скорость — это будущая итерация, не MVP.

### Catalog refresh

`GET /api/datasets` сканирует `EVAL_ROOT` glob'ом `*/v*/comparison.jsonl` на каждый запрос. Каталог маленький (десятки entry'ев), скан < 50ms, кэш не нужен. Это позволяет добавить новый прогон scoring'а без рестарта сервиса.

## Backend API

### `GET /api/datasets`

Скан `EVAL_ROOT/<run>/<variant>/` (правила и safety — см. § Data sources). Возвращает что доступно — для каталога-пикера.

```json
{
  "runs": [
    {
      "name": "qwen_edited_par_by_par",
      "variants": [
        {"variant": "v1", "judges": ["gpt-5.5-low"], "n_paragraphs": 542},
        {"variant": "v2", "judges": ["gpt-5.5-low"], "n_paragraphs": 542}
      ]
    },
    {
      "name": "claude-opus-4.7_par_by_par",
      "variants": [{"variant": "v1", "judges": ["gpt-5.5-low"], "n_paragraphs": 542}]
    }
  ]
}
```

Правила скана:
- В каталог попадает (run, variant), у которого есть `comparison.jsonl` И хотя бы один `reports/<judge>.jsonl`.
- `judges` — список файлов в `reports/*.jsonl`.
- `n_paragraphs` — количество строк в `comparison.jsonl`.
- Папки без `comparison.jsonl` (in-progress translation) игнорируются.

### `GET /api/dataset?a=<run>/<variant>/<judge>&b=<run>/<variant>/<judge>`

Принимает два `PathSpec`-параметра одинакового вида (run/variant/judge). Возвращает готовый LLM-Comparator JSON. Подробности трансформации — § Data adapter; правила валидации пути — § Data sources › Path resolution.

Ошибки:
- 400 — `PathSpec` не валидируется регулярке `^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+){2}$`, либо `..`-сегмент, либо после `resolve()` путь не внутри `EVAL_ROOT`.
- 404 — нет `comparison.jsonl` или `reports/<judge>.jsonl` по указанному `PathSpec`.
- 422 — в A и B судьи разные (для MVP enforced: судья должен совпасть).
- 500 — malformed JSONL: в адаптере отвалилось > 50% строк (вернётся `{"detail": "…", "skipped_ids": [...]}`).

## Data adapter

Функция `build_dataset(a: PathSpec, b: PathSpec) -> dict` в `viewer/backend/adapter.py`. Подаёт на вход уже валидированные пути (см. § Data sources › Path resolution).

### Шаги

1. **Resolve пути** к конкретным файлам:
   ```
   path_a_comparison = EVAL_ROOT / a.run / a.variant / "comparison.jsonl"
   path_a_reports    = EVAL_ROOT / a.run / a.variant / "reports" / f"{a.judge}.jsonl"
   path_b_comparison = EVAL_ROOT / b.run / b.variant / "comparison.jsonl"
   path_b_reports    = EVAL_ROOT / b.run / b.variant / "reports" / f"{b.judge}.jsonl"
   ```
2. **Загрузка в память** (см. § Data sources › File I/O):
   ```python
   comp_a:    dict[int, dict] = {r["id"]: r for r in iter_jsonl(path_a_comparison)}
   comp_b:    dict[int, dict] = {r["id"]: r for r in iter_jsonl(path_b_comparison)}
   reports_a: dict[int, dict] = {r["id"]: r for r in iter_jsonl(path_a_reports)}
   reports_b: dict[int, dict] = {r["id"]: r for r in iter_jsonl(path_b_reports)}
   ```
   Малформенные строки пропускаются с warning'ом.
3. **Inner join** по `id`: `common_ids = comp_a.keys() & comp_b.keys() & reports_a.keys() & reports_b.keys()`. `id`'ы из симметричной разности логируются и в JSON не попадают.
4. Для каждого `id` строит `Example`:
   - `input_text` = `comp_a[id]["source"]`. Если `comp_b[id]["source"] != comp_a[id]["source"]` — log warning, берём A (chunking должен совпадать; если не совпал — баг pipeline'а, не задача viewer'а).
   - `output_text_a` = `comp_a[id]["translated"]`
   - `output_text_b` = `comp_b[id]["translated"]`
   - `score` — см. § Score formula ниже.
   - `tags` = `[]`
   - `individual_rater_scores` = `[]`
   - `rationale_list` = `[]`
   - `custom_fields`: по 4 ключа на каждый из 5 критериев (см. § Извлечение per-criterion).
5. `metadata.custom_fields_schema` — фиксированная схема:

```json
[
  {"name": "accuracy",              "type": "per_model_number"},
  {"name": "terminology",           "type": "per_model_number"},
  {"name": "fluency",               "type": "per_model_number"},
  {"name": "cultural",              "type": "per_model_number"},
  {"name": "style",                 "type": "per_model_number"},
  {"name": "Δ accuracy",            "type": "number"},
  {"name": "Δ terminology",         "type": "number"},
  {"name": "Δ fluency",             "type": "number"},
  {"name": "Δ cultural",            "type": "number"},
  {"name": "Δ style",               "type": "number"},
  {"name": "accuracy rationale",    "type": "per_model_text"},
  {"name": "terminology rationale", "type": "per_model_text"},
  {"name": "fluency rationale",     "type": "per_model_text"},
  {"name": "cultural rationale",    "type": "per_model_text"},
  {"name": "style rationale",       "type": "per_model_text"}
]
```

6. `models` — `[{name: human_label(a)}, {name: human_label(b)}]`. `human_label("qwen_edited_par_by_par/v1/gpt-5.5-low")` → `"qwen / par_by_par (edited, v1)"` — алгоритм компактного имени уточним в writing-plans.

### Извлечение per-criterion

Из `reports_a[id]` (и симметрично `reports_b[id]`) для каждого `crit in ("accuracy", "terminology", "fluency", "cultural", "style")`:
- `reports_a[id][crit]["final_score"]` → `custom_fields[crit][0]` (A); из `reports_b` → `[1]` (B).
- `reports_a[id][crit]["summary"]` → `custom_fields[f"{crit} rationale"][0]` (A); из `reports_b` → `[1]` (B).
- `Δ {crit}` = `final_score_a - final_score_b`. Если любой операнд `null` — Δ тоже `null`.

`identified_terms`, `cultural_inventory`, `identified_issues`, `criteria_assessment` **в адаптере игнорируются**. Если позже понадобится — добавим в JSON опциональный rich-blob, фронт раскроет тогглом.

### Score formula

Поле `score` в LLM Comparator должно лежать в `[-1.5, 1.5]` (positive = A лучше). Вычисление:

```python
deltas = [a - b for a, b in zip(scores_a, scores_b) if a is not None and b is not None]
if not deltas:
    score = None
else:
    score = max(-1.5, min(1.5, (sum(deltas) / len(deltas)) / 9 * 1.5))
```

Деление на 9 нормализует средний Δ из диапазона `[-9, 9]` в `[-1, 1]`, умножение на 1.5 даёт `[-1.5, 1.5]`. `clip` — защита от FP-overflow на границах. Если для абзаца все 5 критериев имеют `null` final_score, `score = null` (фронт обработает).

Это поле скрыто по умолчанию в UI (см. § Frontend), но используется движком LLM Comparator для бэйджа «A is better / B is better» и встроенной сортировки.

### Walkthrough: один параграф end-to-end

Дано — `id=0` из v1-evaluation:

`comp_a[0]` (из `qwen_edited_par_by_par/v1/comparison.jsonl`):
```json
{"id": 0, "source": "МЕСОПОТАМИЯ", "translated": "Mesopotamia",
 "scores": {"gpt-5.5-low": {"accuracy": 9, "terminology": 9, "fluency": 10, "cultural": 8, "style": 9}}}
```

`comp_b[0]` (из `claude-opus-4.7_par_by_par/v1/comparison.jsonl`):
```json
{"id": 0, "source": "МЕСОПОТАМИЯ", "translated": "Mesopotamia",
 "scores": {"gpt-5.5-low": {"accuracy": 10, "terminology": 10, "fluency": 10, "cultural": 9, "style": 9}}}
```

`reports_a[0]["accuracy"]["summary"]`: `"The translation accurately renders the Russian title…"`  
`reports_b[0]["accuracy"]["summary"]`: `"Faithful one-to-one rendering of the proper noun…"`  
(и аналогично 4 других критерия)

Финальный `Example` в выходном JSON:

```json
{
  "input_text":    "МЕСОПОТАМИЯ",
  "output_text_a": "Mesopotamia",
  "output_text_b": "Mesopotamia",
  "tags": [],
  "score": -0.1,
  "individual_rater_scores": [],
  "rationale_list": [],
  "custom_fields": {
    "accuracy":              [9, 10],
    "terminology":           [9, 10],
    "fluency":               [10, 10],
    "cultural":              [8, 9],
    "style":                 [9, 9],
    "Δ accuracy":            -1,
    "Δ terminology":         -1,
    "Δ fluency":             0,
    "Δ cultural":            -1,
    "Δ style":               0,
    "accuracy rationale":    ["The translation accurately renders the Russian title…",
                              "Faithful one-to-one rendering of the proper noun…"],
    "terminology rationale": ["…", "…"],
    "fluency rationale":     ["…", "…"],
    "cultural rationale":    ["…", "…"],
    "style rationale":       ["…", "…"]
  }
}
```

Проверка `score`: `mean([-1, -1, 0, -1, 0]) / 9 * 1.5 = -0.6/9 * 1.5 ≈ -0.1`. Знак отрицательный → бэйдж «B is slightly better».

### Edge cases

- `final_score == null` (terminal-null после 3 fail'ов в scoring) → `null` в JSON. Фронт показывает `—`.
- `summary` отсутствует / пустой → `null` в JSON.
- `id` есть в A, нет в B (или наоборот) → не попадает в финальный JSON (inner join). Логируем warning со списком исключённых `id`.
- A и B судьи не совпали → 422 ошибка с понятным сообщением.

## Frontend — fork of PAIR-code/llm-comparator

Базируется на коде [github.com/PAIR-code/llm-comparator](https://github.com/PAIR-code/llm-comparator) (Apache-2.0, Lit 3.1 + MobX 6 + esbuild). Полный copy под `viewer/frontend/`.

### Что меняем

- **`components/dataset_selection.ts`** → переписать как `catalog-picker` (см. § Catalog picker).
- **`app.ts`** — сменить ссылки и заголовок ("Translation Comparison Viewer"); по умолчанию сайдбар свёрнут (`isShowSidebar = false`).
- **`components/score_histogram.ts`**, **`metrics_by_slice.ts`**, **`rationale_summary.ts`**, **`custom_functions.ts`**, **`charts.ts`** — заменяем на 3 новых компонента сайдбара (см. § Sidebar).
- **`components/example_details.ts`** — переделать раскладку (см. § Detail panel).
- **`components/example_table.ts`** — `score`-колонка скрыта по умолчанию (синтетика), `tags`-колонка скрыта, rationale-колонки скрыты по умолчанию. Σ Δ — новая computed-колонка (сумма `Δ <crit>` по строке).
- **Markdown-рендер** — добавляем `marked` (~30 KB) в `components/example_table.ts` (для preview source/A/B) и `components/example_details.ts` (для полного отображения). Тумблер «Render markdown / show raw» в шапке детальной панели — состояние в AppState.
- **AppState** — добавить:
  - `isRenderMarkdown: boolean = true`
  - `isShowDiff: boolean = false`
  - `catalogDataA: PathSpec | null`, `catalogDataB: PathSpec | null`

### Что оставляем без изменений

- Поиск по столбцам (лупа в шапке).
- Сортировка по любой числовой колонке.
- Видимость колонок (чеклист слева).
- Resize ячеек.
- `loadData(url)` API — просто кормим `/api/dataset?a=…&b=…`.
- `jsdifflib` подсветка различий — но только в `example_details.ts`, и **выключена по умолчанию** (тумблер).

## Detail panel

Раскладка вертикальная, без вкладок и аккордеона:

```
┌──────────────────────────────────────────────────────────┐
│  [×] Paragraph 137              [☐ markdown] [☐ diff]    │
├──────────────────────────────────────────────────────────┤
│  SOURCE (RU)        │  A: qwen…    │  B: opus-4.7…       │
│  …markdown render…  │  …MD render… │  …MD render…        │
├──────────────────────────────────────────────────────────┤
│  ACCURACY            8 │ 10   (Δ −2)                     │
│  ─────────────────────────────────────────────────────── │
│  A: summary text 2-4 sentences.                          │
│  B: summary text 2-4 sentences.                          │
├──────────────────────────────────────────────────────────┤
│  TERMINOLOGY         9 │  9   (Δ  0)                     │
│  …                                                       │
├──────────────────────────────────────────────────────────┤
│  FLUENCY, CULTURAL, STYLE — по тому же шаблону            │
└──────────────────────────────────────────────────────────┘
```

- Источник, A, B — three columns side-by-side, рендерятся как markdown по умолчанию.
- При `isShowDiff = true` — `jsdifflib` подсвечивает разности между A и B (на source не влияет).
- 5 карточек критериев — стек, без сворачивания. Каждая карточка: жирный score `A | B`, Δ-badge (зелёный, красный, серый), две summary-строки (A и B) под скорами.
- `null`-score → показ `—`; `null`-summary → пустая строка.

## Catalog picker

Заменяет `dataset_selection.ts`. Модальный диалог с дим-overlay'ем, открывается:
- по клику на «Load Data» в шапке,
- автоматически при старте, если в URL нет `?a=…&b=…` query-параметров,
- через `?picker=1` если пользователь хочет переоткрыть.

Закрывается: кнопкой `Cancel`, клавишей `Esc`, кликом на dim-overlay. Никакого `[×]`-крестика в углу.

### Layout (default / valid state)

Ширина модалки **720px**, две колонки по 320px с gap'ом 40px. ASCII-приближение:

```
┌─────────────────────────────────────────────────────────────────┐
│  Compare two translations                                       │
│                                                                 │
├──────────────────────────────────┬──────────────────────────────┤
│  Translation A                   │  Translation B                │
│                                  │                               │
│  Run                             │  Run                          │
│  ┌─────────────────────────────┐ │  ┌──────────────────────────┐│
│  │ qwen / par-by-par (edited)▼ │ │  │ claude-opus-4.7 / par… ▼ ││
│  └─────────────────────────────┘ │  └──────────────────────────┘│
│                                  │                               │
│  Variant                         │  Variant                      │
│  ┌─────────────────────────────┐ │  ┌──────────────────────────┐│
│  │ v1 · 542 paragraphs       ▼ │ │  │ v1 · 542 paragraphs    ▼ ││
│  └─────────────────────────────┘ │  └──────────────────────────┘│
│                                  │                               │
│  Judge                           │  Judge                        │
│  ┌─────────────────────────────┐ │  ┌──────────────────────────┐│
│  │ gpt-5.5-low               ▼ │ │  │ gpt-5.5-low            ▼ ││
│  └─────────────────────────────┘ │  └──────────────────────────┘│
│                                  │                               │
├──────────────────────────────────┴──────────────────────────────┤
│                          ⇄  Swap A ↔ B                          │
├─────────────────────────────────────────────────────────────────┤
│  Judge must match on both sides.                                │
│                                                                 │
│                                            [ Cancel ]  [ Load ] │
└─────────────────────────────────────────────────────────────────┘
```

### Поведение dropdown'ов

Три native `<select>` на каждую сторону. Каскад **внутри одной стороны**:

1. **Run** — всегда enabled. Опции — все `runs[].name` из `/api/datasets`, форматированы через `human_label_run()`.
2. **Variant** — disabled до выбора Run. После выбора Run — опции `runs[i].variants[*].variant`, формат: `"<variant> · <n_paragraphs> paragraphs"`.
3. **Judge** — disabled до выбора Variant. После выбора Variant — опции `runs[i].variants[j].judges[*]`, формат: имя судьи как есть.

При смене вышестоящего dropdown'а нижестоящие сбрасываются.

**Cross-side**: судья НЕ синхронизируется автоматически. Обе стороны независимо показывают свои опции; валидация (см. ниже) ловит несовпадение.

### Swap A ↔ B

Кнопка-чип под обеими колонками. Меняет местами все три значения (run/variant/judge) A и B. Полезно когда быстро понимаешь, что хотел A справа и B слева.

### Validation и состояние кнопки Load

Кнопка `Load`:
- **Disabled, серая** если: 
  - любой из 6 dropdown'ов не выбран, либо
  - `judge_a != judge_b`, либо
  - `(run_a, variant_a, judge_a) == (run_b, variant_b, judge_b)` (та же самая пара — бессмысленно).
- **Enabled, primary-цвет** иначе.
- При hover'е по disabled'у — tooltip с причиной (`"Pick a judge for B"`, `"Judges must match"`, `"A and B point to the same dataset"`).

Под кнопкой Load — статичная подсказка `Judge must match on both sides.` всегда видна. Когда `judge_a` и `judge_b` оба выбраны но различаются, к подсказке добавляется красный inline-warning `⚠ "gpt-5.5-low" ≠ "gpt-5.4-mini"`.

`Cancel` — всегда enabled. Закрывает модалку без изменений (восстанавливает прежнее состояние).

### Layout — empty / loading / error states

**Loading** (фетч `/api/datasets`):
```
┌─────────────────────────────────────────────────────────────────┐
│  Compare two translations                                       │
│                                                                 │
│                       Loading datasets…                         │
│                       ⏳                                         │
│                                                                 │
│                                            [ Cancel ]           │
└─────────────────────────────────────────────────────────────────┘
```

**Empty** (`/api/datasets` вернул `{runs: []}`):
```
┌─────────────────────────────────────────────────────────────────┐
│  Compare two translations                                       │
│                                                                 │
│  No evaluations found in EVAL_ROOT.                             │
│                                                                 │
│  Run Stage 03 Scoring to produce comparison.jsonl +             │
│  reports/<judge>.jsonl, then [Reload].                          │
│                                                                 │
│                                            [ Cancel ]           │
└─────────────────────────────────────────────────────────────────┘
```

**Error** (`/api/datasets` 5xx или сеть упала):
```
┌─────────────────────────────────────────────────────────────────┐
│  Compare two translations                                       │
│                                                                 │
│  ⚠ Failed to load catalog: <error message>                      │
│                                                                 │
│                                  [ Cancel ]   [ Retry ]         │
└─────────────────────────────────────────────────────────────────┘
```

### Pre-fill и query-параметры

При открытии модалка предзаполняется в порядке приоритета:
1. URL query-параметры `?a=<run>/<variant>/<judge>&b=…` если есть и валидны → дропы предвыбраны.
2. Иначе текущая загруженная пара (`appState.catalogDataA`, `…B`) → предвыбрана.
3. Иначе пустое состояние (все три dropdown'а на каждой стороне в placeholder'е "Select…").

При клике Load → пишет в URL `?a=…&b=…` через `history.pushState`, вызывает `appState.loadData('/api/dataset?a=…&b=…')`, закрывает модалку. URL можно скопировать и переслать — при открытии получатель окажется на той же сравнении.

### Реализация (для writing-plans)

- Новый Lit-компонент `comparator-catalog-picker` в `viewer/frontend/client/components/catalog_picker.ts` + `.css`.
- Заменяет `comparator-dataset-selection` в `app.ts`.
- Получает `appState` через `core.getService(AppState)`.
- Состояние модалки (open/closed, выбранные A/B, статус загрузки каталога) — в `AppState`.
- Каталог фетчится в `AppState.initialize()` один раз при загрузке страницы (плюс при клике `[Reload]` в empty-state'е).

## Sidebar (3 виджета)

По умолчанию **collapsed**. Чтобы развернуть — кнопка-стрелка справа.

1. **Per-criterion histograms** (5 шт.) — для каждого критерия overlay-гистограмма распределения `final_score` для A и B (10 бинов, 1–10). Заголовок: «Accuracy», под ним легенда «A: qwen…», «B: opus-4.7…». Считается на клиенте из `examples[]`.

2. **Aggregate stats table** — 5 строк (по критериям) × колонки `avg A`, `avg B`, `A wins %`, `B wins %`, `ties %`, `Δ avg`. `A wins` — доля параграфов с положительной Δ, `ties` — с нулевой.

3. **Δ-distribution histogram** — одна гистограмма «Σ Δ» (сумма Δ по 5 критериям) по всем абзацам. Узкая — модели близки; широкая / с хвостами — есть точки сильного расхождения. Клик по бину — фильтрует таблицу абзацами из этого бина.

Все три считаются из `examples[]` на клиенте, без backend round-trip.

## Deployment

```yaml
# viewer/docker-compose.yml
services:
  viewer:
    build: .
    environment:
      EVAL_ROOT: /data/pilot/evaluation
    volumes:
      - ../data/pilot/evaluation:/data/pilot/evaluation:ro
    expose: ["8000"]

  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  caddy_data:
  caddy_config:
```

```caddy
# viewer/Caddyfile (пользователь подставит свой домен)
viewer.example.com {
  reverse_proxy viewer:8000
}
```

Локально: `cd viewer/backend && uvicorn main:app --reload --port 8000`, фронт собирается отдельно через `cd viewer/frontend && npm run build`, FastAPI отдаёт `viewer/frontend/dist/` как статику.

В production: `docker compose up -d`. Caddy получит сертификат от Let's Encrypt автоматически.

## Out of scope (MVP)

- Несколько судей в одной вьюхе (схема JSON под это готова, UI добавим итерацией).
- Cross-run aggregate report (какая модель лучше в среднем) — отдельный report stage, не viewer.
- Rationale clusters (text embeddings) — для пилота не нужны.
- Авторизация — single-user, прячется за Caddy basic-auth при необходимости.
- Кэширование adapter-выхода — пока read-on-demand; добавим, если станет ощутимо медленно.
- Factcheck-данные (`<run>/factcheck/factcheck_scores.jsonl`) — игнорируем; добавим как отдельную секцию в карточке если попросят.
- Rich rationale (`identified_terms`, `cultural_inventory`, `identified_issues`, `criteria_assessment`) — игнорируем в MVP, прячем под тогглом «show full» позже.
- Markdown-эдитор / inline-аннотации эксперта — не делаем, viewer read-only.

## Testing

**Backend**:
- `tests/viewer/test_adapter.py` — fixture-jsonl (3-4 параграфа, mock summary) → expected LLM-Comparator JSON. Покрывает: inner join, null `final_score`, null `summary`, Δ-расчёт, score-normalisation.
- `tests/viewer/test_catalog.py` — fixture-tree из 2 runs × 2 variants → expected catalog. Покрывает: пропуск папок без `comparison.jsonl`, скан `reports/*.jsonl`.
- `tests/viewer/test_paths.py` — PathSpec validation: regex, `..`-rejection, escape-EVAL_ROOT-rejection.
- `tests/viewer/test_main.py` — FastAPI TestClient end-to-end на fixture-tree: 200 happy path, 400 bad PathSpec, 404 missing files, 422 mismatched judges.
- pytest, без сетевых вызовов.

**Frontend**:
- Тесты не пишем (LLM Comparator-upstream их тоже не имеет; research-grade).
- Smoke: `docker compose up`, ручная проверка на `qwen_edited_par_by_par/v1` vs `qwen_par_by_par/v1`.

## Open questions to resolve at planning

- Точный алгоритм `human_label_run(name)` / `human_label_judge(name)` — какой компактный формат отображения, как разбирать `<model>_<chunk_mode>` (например `qwen_edited_par_by_par` → `Qwen / par-by-par (edited)`, `claude-opus-4.7_by_10_par` → `Claude Opus 4.7 / by 10 par`).

---

## Status

Draft — ожидает ревью пользователя перед переходом к writing-plans.
