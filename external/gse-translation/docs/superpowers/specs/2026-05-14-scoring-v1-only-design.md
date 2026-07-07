# Spec: Scoring v1-only — drop consolidated path, single-variant generic dispatcher

**Status:** Draft. **Author:** Artem + Claude. **Date:** 2026-05-14. **Up-link:** [CLAUDE.md](../../../CLAUDE.md). **Predecessor:** [2026-05-13-scoring-v2-sequential-runs.md](2026-05-13-scoring-v2-sequential-runs.md), [2026-05-13-multi-judge-scoring-design.md](2026-05-13-multi-judge-scoring-design.md).

## Контекст

Через v2-инфраструктуру (sequential dispatch + semaphore + retry + fsync) у нас работают **2 consolidated промпта** (`faithfulness` → accuracy/terminology/cultural, `english_quality` → fluency/style/consistency). На smoke 50 параграфов выяснилось: под длинным `english_quality.md` (~20 KB system prompt) `gpt-5.5-low` с `reasoning.effort=low` теряет JSON-формат и пишет markdown-эссе. Fix через `response_format={"type":"json_object"}` сработал, но:

1. `response_format` поддерживают не все провайдеры одинаково (Anthropic API не имеет нативной JSON mode; OpenRouter может проксировать молча игнорируя). Кросс-провайдерная сравнимость судей ломается.
2. Длина EQ-промпта (20 KB) — симптом того, что в одну LLM-головку упаковано **три измерения** (fluency / style / consistency) с шкалами 1–10, calque-каталогом, modality balance. Под слабым reasoning'ом attention размыт; даже когда JSON держится, есть подозрение что глубина анализа страдает (не подтверждено A/B, но риск реальный).
3. Хочется единого, простого, провайдер-агностичного контракта оценки.

**Решение**: вернуться к схеме 6 отдельных промптов (по одному на criterion), как было в `prompts/03_scoring/old/`. Каждый промпт фокусируется на своём измерении, короче, проще для модели. Никакого `response_format` — JSON-инструкция живёт в самом промпте. Чуть дороже по числу API-вызовов (6 вместо 2 per judge per paragraph), но дешевле в attention-нагрузке и портабельнее между провайдерами.

Заодно — упрощаем диспетчер: один путь, никаких consolidated/legacy веток, никаких per-judge variant overrides. Прозрачнее код, проще тесты, легче новые варианты промптов в будущем.

## Цели

- Один путь оценки в коде — single-criterion, filename-driven.
- Папка промптов задаётся в YAML как простое имя; добавление `v2/`, `v3/` с любым числом `*.md` работает без правки кода.
- Никакого `response_format` / structured-output — провайдер-агностичность.
- Aggregation (`merged_scores.jsonl`, `scores.json`) строится на динамическом criteria-списке.
- Чистка accumulated cruft: dead-code, dead-tests, устаревшие doc-секции.

## Не-цели

- Изменение JSONL-схемы или путей `evaluation/<run>/<judge>/<criterion>_scores.jsonl` — структура остаётся прежней.
- Сравнение качества v1 vs consolidated на текущих данных — это отдельный эксперимент, не часть refactor'а.
- Поддержка перемешивания variant'ов внутри одного scoring-конфига (per-judge override). Если понадобится позже — добавляется аддитивно за час.
- Перевод других стадий (translate / correction / factcheck) на новые контракты — они не трогаются.

## Решения

### D1. Filename-driven variant discovery

`load_prompts(prompts_root, variant)` делает `sorted((prompts_root / variant).glob('*.md'))` и возвращает `{filename_stem: file_text}`. Список criteria для всего scoring-run = `list(prompts.keys())`.

**Контракт**: каждый `*.md` файл в variant-папке = один criterion. Имя файла без расширения — имя criterion'а. Опечатка в имени файла = новый criterion-namespace в JSONL без предупреждения. Mitigation: pydantic field_validator проверяет существование папки на load-time (см. D7); порядок criteria детерминирован через `sorted()` для стабильных diff'ов.

### D2. Один variant на весь scoring-конфиг

Поле `JudgeConfig.variant` удаляется. Все judges в одном `ScoringConfig` используют единственный variant из `cfg.prompts_variant`. Это упрощает aggregation: schema `merged_scores.jsonl` стабильна для всего конфига, criteria-список одинаковый для всех judges.

Если нужно сравнить v1 vs v2 на тех же translations — это два отдельных scoring-конфига и две отдельные `evaluation/` директории. Pandas merge по `id` при анализе.

### D3. JSON output — через промпт + per-model `response_format` toggle

**Изначальный план** (v1/v2 спеки): никакого `response_format` нигде, JSON-инструкция только в промпте — для провайдер-агностичности.

**Финальное решение** (v3, после smoke + D16): JSON-инструкция в промпте остаётся (универсальная база), плюс `response_format={"type":"json_object"}` пробрасывается в каждый judge-вызов как **per-model toggle**. Подробнее в D16. У провайдеров с `supports_structured_output: true` decoder-level constraint pinning JSON; у остальных параметр silently drop, prompt-driven JSON работает как fallback.

Парсинг через `parse_judge_response` (поддерживает ```json fence + plain JSON) — без изменений.

**Почему гибрид**: provider-agnostic prompt + opt-in decoder enforcement. Сохраняет cross-provider портабельность, но даёт твёрдую гарантию формата там где провайдер позволяет. Источник capability matrix — OpenRouter `/models` endpoint.

### D4. Имена папок промптов

- `prompts/03_scoring/old/` → переименовать в `prompts/03_scoring/v1/`. Содержимое не трогать (6 файлов: accuracy, terminology, cultural, fluency, style, consistency).
- `prompts/03_scoring/full/` → удалить целиком.
- `prompts/03_scoring/compact/` → удалить целиком.

Будущие наборы промптов = `prompts/03_scoring/v2/`, `v3/`, или с осмысленными суффиксами типа `v1_short/`.

### D5. Aggregation на динамическом criteria-списке

`build_merged_jsonl` и `build_aggregate_scores` принимают аргумент `criteria: list[str]` вместо хардкоженного `LEGACY_CRITERIA`. Constants `LEGACY_CRITERIA` и `CONSOLIDATED_PROMPTS` удаляются.

`merged_scores.jsonl` row schema (после D12 — никаких `-1`):
```jsonc
{
  "id": <int>,
  "source": "...", "translated": "...",
  "<criterion_1>": {"avg": <float|null>, "by_judge": {<judge>: <int 1-10>}},
  ...
  "<criterion_N>": {"avg": ..., "by_judge": ...},
  "factcheck": {"f1": ..., "p": ..., "r": ..., "judge": ...}  // если включён
}
```

`<criterion>_scores.jsonl` row schema: `score: int 1-10` (валидная оценка) или `score: null` (sentinel terminal skip — marker / `[TRANSLATION FAILED]` / persistent parse failure). Никакого `-1`. Имена ключей зависят от variant-папки; для v1 — те же 6 критериев. Существующие данные в `data/pilot/evaluation/qwen_par_by_par/gpt-5.5-low/*.jsonl` (v2 формат) совместимы, но **могут содержать строки `-1` из старых прогонов** — `load_existing_ids` сразу после refactor'а станет их трактовать как done, что НЕправильно. Mitigation см. в D12.

### D6. Pre-load promptов один раз в `run_scoring`

Сейчас `_score_run_for_judge` грузит promptы заново на каждый (run × judge). После refactor'а все judges используют один variant — грузим один раз на верхнем уровне:

```python
async def run_scoring(cfg, *, max_paragraphs=None):
    prompts = load_prompts(cfg.prompts_root, cfg.prompts_variant)
    criteria = list(prompts.keys())  # стабильный порядок, sorted() in load_prompts
    ...
    for run in cfg.runs:
        for judge in cfg.judges:
            await _score_run_for_judge(cfg, run, judge, prompts, criteria, ...)
    ...
    for run in cfg.runs:
        build_merged_jsonl(run_dir, judges=[...], criteria=criteria, ...)
    build_aggregate_scores(..., criteria=criteria, ...)
```

`_score_run_for_judge` / `build_merged_jsonl` / `build_aggregate_scores` получают `prompts` (или `criteria`) через аргумент. Никакого внутреннего IO для каждого judge.

### D7. Soft-warning validator для variant-папки

В `ScoringConfig` добавить `@model_validator(mode='after')`, который **печатает warning в stderr** если `(self.prompts_root / self.prompts_variant)` не существует или пуст. **Не raise** — реальная ошибка вылезет позже в `load_prompts` с понятным `FileNotFoundError`. Soft-mode выбран чтобы не ломать тесты, которые конструируют `ScoringConfig` с относительным `prompts_root` из subdirectory pytest'а (например, `tests/test_scoring_config.py:test_scoring_config_defaults_and_required`).

`prompts_variant` тип: `str` (а не `Literal[...]`) с дефолтом `"v1"`.

### D8. Новый файл `docs/known_issues.md`

Создаётся **новый top-level doc** на русском, фиксирующий грабли проекта. Четыре записи на старт:

1. **JSON через промпт vs `response_format`** — почему сейчас prompt-driven (D3), какие симптомы триггерят возврат к structured output, что для какого провайдера работает.
2. **Параллельность: `max_concurrency` per-client, не глобально** — у каждого `LLMClient` свой semaphore. v2 sequential dispatch держит runs/judges последовательно внутри одного процесса, но `scripts/03_scoring_resume.sh` запускает `large-low` и `small-low` параллельными процессами → каждый со своим `max_concurrency`. Реальная нагрузка на провайдер = (число параллельных process'ов) × `max_concurrency` × (число critериев per paragraph). При планировании batterу — считать кратность; при первых 429 — снижать `max_concurrency` (см. D12 verification).
3. **Стохастичность LLM-багов** — баги с малой долей сбоев (>5%) могут не воспроизвестись на N=1 параграфе из-за `temperature=1.0`. Если smoke ловит регрессию — фиксировать paragraph_idx и rerun-проверка идёт на этом же индексе; не редуцировать до single-paragraph repro без подтверждения.
4. **Soft-fallback `score=-1` на parse fail — антипаттерн** — исторически failed-to-parse писало row с `score: -1` и `llm_report: "missing criterion X"` (затирая raw'). Соблазн: «row есть → resume увидит → перепробует». Реальность: aggregation должен помнить о sentinel'е и фильтровать, диагностика теряется, а row в JSONL **семантически путает аналитика**. После D12: parse fail → exception, raw уходит в отдельный `parse_failures.jsonl`, criterion-JSONL остаётся чистым (только real scores + null sentinels).

Формат записи: краткое описание → симптомы → причина → текущее решение → когда пересмотреть.

В [CLAUDE.md](../../../CLAUDE.md) Routing-таблица получает строку:
```
| Известные проблемы и грабли | [docs/known_issues.md](docs/known_issues.md) |
```

В Conventions → Documentation секция добавляется правило: «Грабли проекта (баги, неочевидные ограничения провайдеров, проблемы воспроизводимости) фиксируем в [docs/known_issues.md](docs/known_issues.md) — добавлять новую запись когда столкнулись и согласовали решение».

### D9. Удаление `response_format` plumbing

В [src/palimpsest/llm/client.py](../../../src/palimpsest/llm/client.py) убираются 4 строки в `_complete_openai`, которые подхватывают `response_format` из overrides (добавлены в commit `5f46128`). Без caller'а это dead code.

### D10. Удаление `_score_paragraph` тонкого wrapper'а

`_score_paragraph` сейчас содержит только `if variant == "old" → score_legacy else score_consolidated`. После убирания consolidated пути это thin wrapper над `score_paragraph` (бывший `score_legacy`). Удаляется; caller `_score_run_for_judge` вызывает `score_paragraph` напрямую.

### D11. Переименование `score_legacy` → `score_paragraph`

Имя `legacy` теряет смысл, так как это единственный путь. `score_paragraph(client, source, translated, prompts) → dict[str, dict]` — fires N промптов параллельно через `asyncio.gather`, возвращает `{criterion: parsed_dict}`.

### D12. Никакого `-1` sentinel — fail-fast на parse error

**Проблема (нашёл Artem 2026-05-14)**: текущий код пишет `score: -1` в criterion-JSONL при любом сбое парсинга (malformed JSON, missing criterion key, отсутствие `final_score`). Это soft fallback — row создан, но семантика «не оценено». Кроме того, `score_consolidated` при missing-criterion **затирает raw-ответ** сообщением `"missing criterion X in Y response"` — диагностика теряется.

**Новый контракт**:

- `score: int 1-10` — реальный валидный score.
- `score: null` — terminal skip (markers / `[TRANSLATION FAILED]` / persistent parse failure, см. D13).
- **`-1` исключается из схемы.** Если LLM вернул не-JSON / неполный JSON / score вне диапазона — exception, **никакой row не пишется в criterion-JSONL**, raw уходит в `<judge>/parse_failures.jsonl`.

**Реализация**:

1. Новый класс в [scoring.py](../../../src/palimpsest/scoring.py):
   ```python
   class JudgeParseError(Exception):
       def __init__(self, criterion: str, raw: str, reason: str):
           self.criterion = criterion
           self.raw = raw
           self.reason = reason  # "empty" | "json_decode" | "missing_score" | "score_out_of_range"
           super().__init__(f"{criterion}: {reason}")
   ```

2. `parse_judge_response(raw: str, criterion: str) -> dict` — raise `JudgeParseError` вместо `return {"final_score": -1, ...}`. Дополнительно валидирует, что `parsed["final_score"]` — `int` в `[1, 10]`.

3. `score_paragraph` делает **inline retry** до `_MAX_PARSE_ATTEMPTS = 2` (1 + 1 повтор) перед escalation. Между попытками — короткий `tqdm.write` warning с `criterion` и `reason`. Если оба провала — пробрасывает последний `JudgeParseError`.

4. `_score_run_for_judge._process` ловит `JudgeParseError`:
   - Аппендит row в `<judge>/parse_failures.jsonl` (отдельный файл, не криterion-JSONL):
     ```jsonc
     {"id": <int>, "criterion": "...", "reason": "...", "raw": "<full LLM response>",
      "source": "...", "translated": "...", "judge": "...", "variant": "v1", "ts": <unix>}
     ```
   - Пробрасывает дальше → `failures` counter в `_score_run_for_judge` → задача упадёт в конце с `raise failures[0]` (текущий v2 контракт). Shell-wrapper рестартует, на следующей попытке `load_existing_ids` НЕ видит paragraph в этом criterion-JSONL → пробует заново.

5. `load_existing_ids` упрощается — удаляется ветка `if row.get("score") == SCORE_LLM_FAIL: continue`. Row в JSONL = done. Period.

6. `_avg_excluding_nulls` упрощается — фильтр `v != -1` удаляется (только `v is not None`).

7. Константа `SCORE_LLM_FAIL: Final[int] = -1` удаляется из [scoring.py](../../../src/palimpsest/scoring.py).

**Back-compat со старыми данными**: в `data/pilot/evaluation/qwen_par_by_par/gpt-5.5-low/fluency_scores.jsonl` могут лежать строки с `score: -1` из v2 прогонов. После refactor'а `load_existing_ids` начнёт их трактовать как done, что неправильно. Перед smoke-verification — **разовая утилита очистки**: одноразовый скрипт `scripts/03_cleanup_minus_one.py` (или просто `jq` one-liner) удаляет все строки с `score: -1` из существующих `*_scores.jsonl` файлов. Описать в плане как explicit step перед verification.

### D13. Persistent failure threshold → terminal `score: null`

**Защита от бесконечного retry-loop'а**: если параграф P попал в `parse_failures.jsonl` ≥ `_PERSISTENT_FAILURE_THRESHOLD = 3` раз для одного и того же criterion, на следующей попытке `_score_run_for_judge` **записывает terminal-null row** в criterion-JSONL вместо очередного API-вызова:

```jsonc
{"id": P, "source": "...", "translated": "...",
 "judge": "gpt-5.5-low", "variant": "v1",
 "score": null,
 "llm_report": "persistent_parse_failure_after_3_attempts; see parse_failures.jsonl"}
```

Логика: на старте `_score_run_for_judge` читается `parse_failures.jsonl`, считается `defaultdict[(id, criterion), int]`. Если ≥ threshold — пропустить вызов и записать null. Это **terminal**: aggregation его исключит (как любой null), resume его пропустит (row есть = done). Но в `parse_failures.jsonl` лежат все 3 raw'а — есть что разобрать руками.

Threshold = 3 берётся эмпирически (1 раз = transient bad sampling; 2 раза = подозрительно; 3 раза = модель этот параграф не вытягивает). Tunable константой в [scoring.py](../../../src/palimpsest/scoring.py).

### D14. Per-criterion failure isolation (post-smoke fix)

**Проблема (обнаружена на первом smoke 2026-05-14)**: исходная реализация `score_paragraph` использовала `asyncio.gather(*coros)` без `return_exceptions=True`. Когда `_one(criterion)` raised `JudgeParseError`, gather пробрасывал первое исключение и **отменял in-flight siblings**. На smoke 50 параграфов × 6 criteria: 49/50 fluency-фейлов → каждый paragraph дропал успешные результаты accuracy/terminology/cultural/style/consistency. Wasted API calls + 0 валидных score rows on disk.

**Контракт после фикса**:

- `score_paragraph(...) -> dict[str, dict | JudgeParseError]` — больше **не raise**. Each `_one` catches its own `JudgeParseError` после `_MAX_PARSE_ATTEMPTS` и возвращает экземпляр исключения как значение в result map.
- `_score_run_for_judge._process` итерирует results: если value — `JudgeParseError` → append в `parse_failures.jsonl`; если value — dict → append в criterion-JSONL. **После** записи всех valid rows — re-raise первый exception для escalation в task-level failures counter (запускает shell-wrapper restart → resume подбирает отсутствующие criterion rows).

Это сохраняет valid sibling work и в то же время держит контракт D12 (присутствие row = done, отсутствие = retry). Изменение чисто внутреннее в score_paragraph и dispatcher — внешний контракт JSONL не меняется.

### D15. Hard JSON-only header для упрямых criterion-промптов

**Наблюдение из smoke**: `gpt-5.5-low` дрейфовал в markdown «translation review essay» на `fluency.md` 49/50 раз, несмотря на стандартный JSON-only хвост («Respond with a valid JSON object and nothing else»). Другие 5 criterion-промптов работали стабильно. Гипотеза: содержание fluency.md priming'ует модель в «evaluator critic» жанр сильнее, чем хвостовая инструкция способна перекрыть.

**Mitigation**: для промптов, на которых наблюдается drift, добавлять **в самом начале файла** жёсткий header:

```
# OUTPUT CONTRACT — READ FIRST

Your response MUST be a single valid JSON object matching the schema in the "Output Format" section at the end of this prompt. No prose introduction. No markdown headings. No "## Overall assessment" sections. Start your reply with `{` and end with `}`.

If you have observations that don't fit the JSON schema, drop them. The schema is the complete contract. Failure to emit valid JSON means the response is discarded.

---

<original prompt content...>
```

Первые токены, на которые модель направляет attention — constraint, не role description. После применения к `prompts/03_scoring/v1/fluency.md`: smoke ушёл с 49/50 fails на 0/50 fails. Apply pattern reactively to any prompt that exhibits drift.

**Обновление 2026-05-14 (см. D16)**: после введения per-model SO toggle (json_object на decoder-уровне) header в fluency.md удалён — все 6 critеrion-промптов снова симметричны. D15 остаётся в спеке как fallback-паттерн для провайдеров без structured-output support.

### D16. Per-model structured-output toggle

**Проблема**: D15 header в fluency.md решил drift, но создал асимметрию между criterion-промптами — один файл начинается с OUTPUT CONTRACT, остальные 5 нет. Cross-criterion comparability страдает: prompts должны быть структурно идентичны, отличаться только содержанием.

**Решение**: вернуть `response_format={"type":"json_object"}` обратно в `LLMClient` как **per-model toggle**, не как blanket-off (D3 теперь обновлён). Каждый model entry в [configs/models.yaml](../../../configs/models.yaml) имеет флаг `supports_structured_output: bool`; `LLMClient._complete_openai` пробрасывает `response_format` в провайдер только когда флаг True.

**Контракт**:

- `ModelConfig.supports_structured_output: bool = False` — default opt-in (новое поле).
- `LLMConfig.supports_structured_output: bool` — mirror, заполняется через `from_model_config`.
- В [scoring.py](../../../src/palimpsest/scoring.py) — `_JUDGE_RESPONSE_FORMAT = {"type": "json_object"}` пробрасывается в **каждый** judge-вызов через kwarg `response_format=`. Translate / correction / factcheck не трогаем.
- В `_complete_openai`: `if overrides.get("response_format") and self.config.supports_structured_output: kwargs["response_format"] = ...`. Для провайдеров без поддержки — silently drop.

**Capability matrix** (см. OpenRouter `/models` endpoint, поле `supported_parameters`):

- ✅ OpenAI `gpt-5.x` (включая `gpt-5.4-mini`)
- ✅ Anthropic Claude 4.5+ (Sonnet 4.6, Opus 4.5+, Haiku 4.5)
- ✅ Google Gemini 3.x (Pro Preview, Flash Lite, Flash Lite Preview)
- ✅ Qwen 3.6 (flash / plus)
- ✅ DeepSeek v4-pro
- ✅ Z.ai GLM 5.1
- ⚠️ Local vLLM (qwen3-4b, gemma-27b, qwen3.6-27b) — зависит от launch flags `--guided-decoding-backend outlines`. Default off → флаг в YAML оставляется по умолчанию `false`. Когда vLLM сервер запускается с guided-decoding — менять флаг в YAML вручную.

**Где источник истины**: для cloud моделей — `GET https://openrouter.ai/api/v1/models` (атрибут `supported_parameters` содержит `response_format` и/или `structured_outputs`). Для local — operator решает по launch flags.

**Применение к D15**: с включённым SO для `gpt-5.5-low` drift не воспроизводится без OUTPUT CONTRACT header в fluency.md. Header удалён, все 6 criterion-промптов **симметричны** (одинаковая структура: role → definition → criteria → output format в хвосте).

**Future**: если будем добавлять json_schema strict mode (а не json_object) — потребуется писать schemas per criterion, файлы лягут рядом с промптами: `prompts/03_scoring/<variant>/<criterion>.schema.json`. Сейчас не нужно — json_object режим достаточен для текущего pool'а судей.

## Поверхность изменений в коде

### [src/palimpsest/scoring.py](../../../src/palimpsest/scoring.py)

**Удаляется:**
- `LEGACY_CRITERIA` константа (строки ~80–87)
- `CONSOLIDATED_PROMPTS` константа (строки ~89–92)
- `_JUDGE_RESPONSE_FORMAT` константа (строка ~121)
- `SCORE_LLM_FAIL: Final[int] = -1` константа (строка ~77) — больше не используется (D12)
- `score_consolidated` функция целиком (строки ~146–170)
- `_resolve_variant` функция (строки ~273–276)
- `_score_paragraph` функция (строки ~295–302)
- `response_format=...` параметр из вызова `client.complete(...)` в `score_legacy`
- Фильтр `v != -1` в `_avg_excluding_nulls`
- Ветка `if row.get("score") == SCORE_LLM_FAIL: continue` в `load_existing_ids`

**Добавляется:**
- Класс `JudgeParseError(Exception)` с атрибутами `criterion`, `raw`, `reason` (D12).
- Константа `_MAX_PARSE_ATTEMPTS: int = 2` (inline retry budget в `score_paragraph`).
- Константа `_PERSISTENT_FAILURE_THRESHOLD: int = 3` (D13).
- Функция `_load_parse_failure_counts(path: Path) -> dict[tuple[int, str], int]` — читает `parse_failures.jsonl` и считает попытки per (paragraph_id, criterion). Используется в `_score_run_for_judge` на старте.
- В `_score_run_for_judge._process`: ветка catch `JudgeParseError` → append в `<judge>/parse_failures.jsonl`, raise дальше для escalation в `failures` counter.
- В `_score_run_for_judge` на верхнем уровне: проверка `fail_counts[(i, criterion)] >= _PERSISTENT_FAILURE_THRESHOLD` → пропуск API-вызова, запись terminal-null row.

**Изменяется:**
- `load_prompts(prompts_root: Path, variant: str)`: упрощается до filename-driven discovery через `sorted(glob('*.md'))`. Docstring переписать.
- `parse_judge_response(raw: str, criterion: str) -> dict`: сигнатура получает обязательный `criterion`. Поведение: raise `JudgeParseError` при пустом/невалидном ответе или невалидном `final_score`. Никакого fallback dict.
- `score_legacy` переименовывается в `score_paragraph`; обвязывает каждый `client.complete` цикл inline-retry до `_MAX_PARSE_ATTEMPTS`.
- `_score_run_for_judge` принимает `prompts: dict[str, str]` и `criteria: list[str]` как аргументы (вместо чтения через `_resolve_variant + load_prompts`). Все упоминания `LEGACY_CRITERIA` внутри функции заменяются на `criteria`.
- `build_merged_jsonl` сигнатура: добавить `criteria: list[str]`, заменить хардкод `LEGACY_CRITERIA` на параметр.
- `build_aggregate_scores` сигнатура: добавить `criteria: list[str]`, заменить хардкод.
- `run_scoring` грузит promptы один раз через `load_prompts`, выводит `criteria`, протягивает в каждый вызов.

### [src/palimpsest/config.py](../../../src/palimpsest/config.py)

**Удаляется:**
- Поле `JudgeConfig.variant: Literal[...] | None` (строка ~56)

**Изменяется:**
- `ScoringConfig.prompts_variant: Literal["old","compact","full"] = "full"` → `prompts_variant: str = "v1"`.
- Добавляется `@model_validator(mode='after')` с проверкой `(prompts_root/prompts_variant).is_dir() and len(list(... .glob('*.md'))) > 0`.

### [src/palimpsest/llm/client.py](../../../src/palimpsest/llm/client.py)

**Удаляется** в `_complete_openai`:
```python
# Per-call JSON mode (OpenAI/OpenRouter standard). ...
response_format = overrides.get("response_format")
if response_format is not None:
    kwargs["response_format"] = response_format
```
(добавлено в commit `5f46128`; теперь dead code без вызывающего)

### Прочее

- Никаких изменений в [src/palimpsest/translate.py](../../../src/palimpsest/translate.py), [src/palimpsest/correction.py](../../../src/palimpsest/correction.py), [src/palimpsest/factcheck/](../../../src/palimpsest/factcheck/) — они не трогали variant/consolidated.

## Изменения конфигов

Все 9 файлов в `configs/scoring/*.yaml`:
- `prompts_variant: full|compact` → `prompts_variant: v1`

Список:
- `configs/scoring/01-top-vs-baseline.yaml`
- `configs/scoring/02-large-chunking.yaml`
- `configs/scoring/03-small-anchor.yaml`
- `configs/scoring/04-small-chunking.yaml`
- `configs/scoring/05-family-and-alt.yaml`
- `configs/scoring/06-reasoning-low.yaml`
- `configs/scoring/large-low.yaml`
- `configs/scoring/small-low.yaml`
- `configs/scoring/smoke.yaml`

Если в judges перечислены `variant:` overrides — удалить эти поля.

## Изменения промптов

```
prompts/03_scoring/
├── compact/         ← DELETE
├── full/            ← DELETE
└── old/             ← RENAME → v1/
    ├── accuracy.md
    ├── consistency.md
    ├── cultural.md
    ├── fluency.md
    ├── style.md
    └── terminology.md
```

**Verification step**: открыть каждый из 6 `prompts/03_scoring/v1/*.md` файлов и убедиться, что в хвосте есть **явная JSON-output инструкция** (фраза «return a valid JSON object», JSON-структура в коде fenced, требование `final_score`). Если в каком-то файле инструкция размыта — починить в этом же refactor'е (отдельный commit `prompts(scoring): tighten JSON output instruction in <criterion>.md`).

## Изменения тестов

7 файлов:

| Файл | Действие | Заметка |
|---|---|---|
| [tests/conftest.py](../../../tests/conftest.py) | Переписать | Удалить `consolidated_engq_response` и `consolidated_faith_response`; добавить `single_criterion_response(score=8, summary="ok", issues=[])` helper |
| [tests/test_scoring_strategy_consolidated.py](../../../tests/test_scoring_strategy_consolidated.py) | Delete | Тесты для удалённой функции |
| [tests/test_scoring_strategy_legacy.py](../../../tests/test_scoring_strategy_legacy.py) | Rename → `test_scoring_strategy.py` | Импорт `score_legacy` → `score_paragraph`; убрать ссылки на legacy. Добавить тесты для D12: `test_score_paragraph_raises_on_malformed_json`, `test_score_paragraph_raises_on_missing_score`, `test_score_paragraph_inline_retries_then_succeeds`, `test_score_paragraph_exhausts_retries_raises`. Удалить `test_score_legacy_propagates_parse_error` (старая семантика soft -1) |
| [tests/test_scoring_dispatcher.py](../../../tests/test_scoring_dispatcher.py) | Переписать mock | `mock_llm_client._complete` сейчас различает FAITH/ENGQ — теперь всегда single-criterion mock |
| [tests/test_scoring_resume.py](../../../tests/test_scoring_resume.py) | Переписать mock | Использует тот же `consolidated_*` import → новый single-criterion. Добавить `test_resume_after_parse_failure_retries_paragraph` (D12: первый прогон валится на парсе → второй прогон видит отсутствие row в criterion-JSONL → вызывает снова и записывает валидный score) и `test_persistent_parse_failure_writes_terminal_null` (D13: 3 неудачные попытки → row с `score: null`) |
| [tests/test_scoring_prompts.py](../../../tests/test_scoring_prompts.py) | Переписать | Удалить тесты `LEGACY_CRITERIA` / `CONSOLIDATED_PROMPTS` / `load_prompts_full_variant`; добавить test_load_prompts_filename_driven (положили 4 файла → получили 4 криеria), test_load_prompts_sorted_order, test_load_prompts_rejects_empty_dir |
| [tests/test_scoring_config.py](../../../tests/test_scoring_config.py) | Обновить | Удалить `test_judge_config_with_overrides`, `test_judge_config_rejects_unknown_variant`, `j.variant is None` assertion; добавить `test_scoring_config_rejects_missing_variant_dir`; default `cfg.prompts_variant == "v1"` |

После refactor'а **все 128 текущих тестов должны проходить**, минус тесты для удалённых функций; должны добавиться новые для filename-driven discovery и validator'а.

## Изменения документации

### [docs/stages/03_scoring.md](../../../docs/stages/03_scoring.md)

Полная переработка Purpose и Subtleties:
- Purpose: «На один параграф — N одно-criterion промптов (по умолчанию 6: accuracy, terminology, cultural, fluency, style, consistency) на каждого судью плюс один factcheck-вызов фиксированной моделью».
- Design decisions: убрать упоминания consolidated; добавить filename-driven discovery, single variant per config, no structured output.
- Interface: код signature без изменений (`run_scoring(cfg)`), но обновить пример конфига на `prompts_variant: v1`.
- Subtleties: удалить пункт про `{full,compact}/{faithfulness,english_quality}.md`; удалить пункт про JSON mode (D9); добавить пункт про filename-driven discovery и pre-loading promптов в `run_scoring`.

### [docs/pipeline.md](../../../docs/pipeline.md)

- Stage 03 нарратив: убрать «2 consolidated LLM calls per judge per paragraph»; заменить на «N одно-criterion вызовов per judge per paragraph (по умолчанию 6)».
- Таблица промптов: убрать строки про `english_quality.md` и `faithfulness.md`; добавить (или восстановить) строки с одним промптом на criterion.

### [docs/known_issues.md](../../../docs/known_issues.md) (NEW)

Создаётся, три записи (см. D8).

### [CLAUDE.md](../../../CLAUDE.md)

- Routing-таблица: добавить строку с known_issues.md.
- Conventions → Documentation: добавить правило про known_issues.md как место для граблей.

### [README.md](../../../README.md)

Verification step: проверить pitch на наличие фраз про consolidated / 2 calls / 6 criteria. Если есть — обновить на «N single-criterion calls» язык. Если нет — без изменений.

### Старые spec/plan файлы

[docs/superpowers/specs/2026-05-13-multi-judge-scoring-design.md](2026-05-13-multi-judge-scoring-design.md), [docs/superpowers/plans/2026-05-13-multi-judge-scoring.md](../plans/2026-05-13-multi-judge-scoring.md), [docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md](2026-05-13-scoring-v2-sequential-runs.md), [docs/superpowers/plans/2026-05-13-scoring-v2-sequential-runs.md](../plans/2026-05-13-scoring-v2-sequential-runs.md) — это исторические документы (запись прошлых решений). НЕ редактируются. Текущая спека (этот файл) перекрывает их.

[docs/experiments/2026-05-13-pilot-evaluation.md](../../experiments/2026-05-13-pilot-evaluation.md) — исторические заметки эксперимента. НЕ редактируются.

## Скрипты и CLI

Verification step:
- Прочитать [scripts/03_translation_scoring.py](../../../scripts/03_translation_scoring.py): убедиться, что нет CLI-флагов про variant. Если есть hardcoded `prompts_variant="full"` — обновить.
- Прочитать [scripts/03_scoring_exprs.sh](../../../scripts/03_scoring_exprs.sh), [scripts/03_scoring_smoke.sh](../../../scripts/03_scoring_smoke.sh): убедиться, что не упоминают `full`/`compact`/`old` как variant names. Обновить если есть.

**Новый одноразовый скрипт** [scripts/03_cleanup_minus_one.py](../../../scripts/03_cleanup_minus_one.py) (создаётся для D12 verification step 0):
- Принимает `--root` (по умолчанию `data/pilot/evaluation_smoke`).
- Рекурсивно проходит по всем `*_scores.jsonl`, читает построчно, оставляет только строки с `score != -1` (включая `null`), перезаписывает файл.
- Логирует сколько строк удалено из каких файлов.
- Идемпотентный: повторный запуск — no-op.

## Порядок исполнения (свар́м)

После approval спеки → план через `superpowers:writing-plans` → 4 параллельно-исполняемых задачи:

- **Агент A — prompts + configs + scripts**: `mv old → v1`, удалить `full/` и `compact/`, обновить 9 YAML конфигов, проверить scripts/. Низкий риск, изолированные правки.
- **Агент B — core code refactor**: [scoring.py](../../../src/palimpsest/scoring.py) + [config.py](../../../src/palimpsest/config.py) + [client.py](../../../src/palimpsest/llm/client.py). Самая большая работа. От него зависят сигнатуры для тестов.
- **Агент C — tests**: 7 файлов (см. таблицу). **Старт после B** — нужны новые сигнатуры.
- **Агент D — docs**: stages + pipeline + новый known_issues + CLAUDE.md routing + README check. Параллельно с B.

Порядок: A и D стартуют сразу; B параллельно с D; C ждёт B. После всех — pytest + smoke на v1.

## Verification

0. **Pre-step (одноразовая чистка существующих JSONL от `-1` рядов)**: запустить `scripts/03_cleanup_minus_one.py` (создаётся в плане) на `data/pilot/evaluation_smoke/` и `data/pilot/evaluation/` чтобы выкорчевать все строки с `score: -1` из старых v2-прогонов. Без этого `load_existing_ids` после refactor'а воспримет такие строки как done.
1. `pytest tests/` зелёный (все 128+ тестов после переработки).
2. Smoke прогон через `scripts/03_scoring_smoke.sh` (или эквивалент) на v1 с `gpt-5.5-low` судьёй: 50 параграфов, **в criterion-JSONL допустимы только `int 1-10` и `null` (sentinel skips)**. Никаких `-1` быть не должно. Если на каком-то параграфе случилась парс-неудача — она лежит в `gpt-5.5-low/parse_failures.jsonl`, и при resume получит retry до 3 раз; на 3-ю — terminal null.
3. `data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/meta.json` содержит `"variant": "v1"`.
4. `merged_scores.jsonl` имеет 6 ключей-критериев, схема стабильна.
5. **API нагрузочный sanity**: первые ~10 параграфов прогона smoke не дают 429 на `gpt-5.5-low`. Если дают — снизить `cfg.max_concurrency` с 64 на 32 в `configs/scoring/smoke.yaml` (см. урок 2 в [docs/known_issues.md](../../known_issues.md)).

## Rollback plan

Refactor мерджится одним PR (или серией коммитов в одной ветке `feat/scoring-v2-sequential`). Если smoke падает — `git revert` каждого коммита по очереди до восстановления зелёного состояния. Старые промпты в `old/` восстанавливаются из git history через `git checkout HEAD~N -- prompts/03_scoring/old/`.

Существующие данные на диске (`data/pilot/evaluation/*`) **не трогаются и совместимы** — JSONL-схема не меняется back-compat.

## Changelog спеки

- **2026-05-14 v1**: initial draft (D1–D11). Согласовано: filename-driven discovery, single variant per config, no `response_format`, drop `_score_paragraph`, rename `score_legacy → score_paragraph`.
- **2026-05-14 v2**: добавлены D12 (no `-1` sentinel, fail-fast on parse error, `parse_failures.jsonl` для диагностики) и D13 (`_PERSISTENT_FAILURE_THRESHOLD = 3` → terminal null). D7 ослаблен до soft-warning. Доб. урок 4 в [known_issues.md](../../known_issues.md). Доб. cleanup-скрипт `scripts/03_cleanup_minus_one.py`.
- **2026-05-14 v3**: после первого smoke прогона обнаружены 2 бага: (a) `score_paragraph` через `asyncio.gather` бросал первое исключение и **отменял успешные результаты сиблингов** — wasted API calls, lost data; (b) `gpt-5.5-low` дрейфовал в markdown эссе на `fluency.md` промпте (49/50 fails) несмотря на JSON-only инструкцию в хвосте. Исправления: **D14** — per-criterion failure isolation: `score_paragraph` возвращает `dict[criterion, dict | JudgeParseError]` без raise, dispatcher расщепляет успехи/неудачи на криterion-JSONL и parse_failures.jsonl независимо. **D15** — для упрямых криterion'ов добавлять hard `# OUTPUT CONTRACT — READ FIRST` header в начало `*.md` промпта (приоритет attention над role priming). Доб. урок 5 в known_issues.md. Smoke после фикса: 50/50 на всех 6 criteria, 0 parse failures, distributions осмысленные (mean 7.6-9.2, range 7-10).
- **2026-05-14 v4** (этот файл): D3 переосмыслен — `response_format` возвращается, но как **per-model toggle**, не blanket. **D16** добавлен: `ModelConfig.supports_structured_output: bool` флаг в `configs/models.yaml`; `LLMClient._complete_openai` пробрасывает `response_format` в провайдер только когда флаг True. Для cloud-моделей через OpenRouter всё True (capability matrix queryable из OR `/models` endpoint). После включения SO для `gpt-5.5-low` — drift не воспроизводится без D15 header в fluency.md → header удалён, все 6 criterion-промптов снова симметричны. `docs/llm_models.md` удалён как ненужный (информация queryable из `/models`).

## Open questions

Нет. Если что-то всплывёт во время плана/исполнения — добавляется в Changelog как v3+.
