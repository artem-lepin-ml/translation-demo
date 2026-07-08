# Соглашения по интерфейсам пайплайна

Контракт на расположение файлов и форматы артефактов между стадиями. Источник истины для именования путей и JSON-схем входов/выходов.

Всё, что описано ниже, относится к **пилоту** (3 главы первого тома). Production-paths для полных томов оформим отдельным контрактом.

## Общие соглашения

- **Абзац** — атомарная единица перевода. Меньше абзаца не берём.
- **Глава** — максимальная единица перевода. Больше главы не берём.
- Внутри этих границ всё идентифицируется через **id параграфа** = 0-indexed номер строки в `data/pilot/pilot_original.md`.
- Все артефакты пилота лежат под `data/pilot/`.

Дерево артефактов пилота:

```
data/pilot/
├── pilot_original.md
├── chunking/
│   ├── for_translation/
│   │   └── <chunk_name>.json  # 5 разных вариантов
│   └── for_evaluation/
│       └── <NN>_<chapter_slug>.json  # по подглавам
├── translating/
│   ├── small/
│   │   └── <run_name>/
│   │       ├── translation.md
│   │       ├── config.json
│   │       ├── progress.jsonl      # append-only resume log
│   │       ├── failures.jsonl      # only when ≥1 chunk failed
│   │       └── failure_debug/      # only when ≥1 chunk failed
│   ├── large/
│   │   └── <run_name>/             # same layout as /small/
│   └── local/
│       └── <run_name>/             # same layout
└── evaluation/
    ├── <run_name>/
    │   ├── <judge>/
    │   │   ├── accuracy_scores.jsonl
    │   │   ├── terminology_scores.jsonl
    │   │   ├── cultural_scores.jsonl
    │   │   ├── fluency_scores.jsonl
    │   │   ├── style_scores.jsonl
    │   │   ├── consistency_scores.jsonl
    │   │   └── meta.json
    │   ├── factcheck/
    │   │   ├── factcheck_scores.jsonl
    │   │   └── meta.json
    │   └── merged_scores.jsonl
    └── scores.json
```

## 00 Парсинг (PDF → Markdown)

Внешний этап (уже зафиксирован).

**Output:** `data/pilot/pilot_original.md`.

**Формат файла:**

- Одна строка = один параграф. Пустых строк нет.
- Заголовки подглав записаны UPPERCASE на отдельной строке и тоже считаются параграфами со своим id.
- id параграфа = номер строки (0-indexed).

**Примеры заголовков** (из текущего `pilot_original.md`):

- Строка 1 (id 0) — `ДРЕВНИЙ ЕГИПЕТ (IV–II тысячелетия до н.э.)`.
- Строка 33 (id 1) — `РАННЕЕ ЦАРСТВО: ЭПОХА АРХАИКИ (около 3000–2686 гг. до н.э.)`.

**Статус для пилота:** **зафиксировано**. 3 главы первого тома, всё лежит в одном `pilot_original.md`.

## 01 Распределение параграфов по запросам

Текст не дробим на новые файлы — формируем артефакт «список списков id параграфов».

**Семантика:** dict, где ключ — id запроса (string, начиная с `"0"`, без пропусков), значение — `[left, right]` инклюзивный диапазон id параграфов в 0-индексации. Один элемент на строку — для читаемых diff'ов.

**Формат файла** (`.json`):

```json
{
  "0": [0, 109],
  "1": [110, 184],
  "2": [185, 306]
}
```

Для ясности: *Две независимые поддиректории — два независимых артефакта:*

### `data/pilot/chunking/for_translation/<chunk_name>.json`

Вход для Stage 03. Описывает стратегию нарезки для перевода.

`<chunk_name>` — slug стратегии. Поддерживаемые стратегии (все валидны для перевода, будет перебирать их):

1. `by_chapter` — целиком главой: `[[0, 1, ..., 548]]`.
2. `by_subchapter` — по подглавам (пока руками).
3. `par_by_par` — по одному параграфу: `[[0], [1], ..., [548]]`.
4. `by_k_par` — по k подряд идущих параграфов (например, `by_5_par`).
5. `smart_llm_split` — LLM делит на независимые части. Пока не делаем

**Инвариант для `by_k_par`:** чанк не пересекает границы глав. Каждая глава режется независимо; последний чанк главы укорачивается до её последнего параграфа (так что чанки на хвостах глав могут быть короче `k`).

### `data/pilot/chunking/for_evaluation/<NN>_<chapter_slug>.json`

Артефакт для **post-hoc per-subchapter анализа** поверх per-paragraph JSONL из Stage 03. Только разбиение по подглавам. Префикс `NN` (с `00`) — для сортировки.

Stage 03 (scoring) сам этот файл не читает (оценка идёт по параграфам, см. ниже), но скрипты аналитики используют его, чтобы свернуть per-paragraph оценки в средние по подглавам.

## 02 Перевод

**Input:**

- `data/pilot/pilot_original.md`
- `data/pilot/chunking/for_translation/<chunk_name>.json`

**Output:** `data/pilot/translating/<bucket>/<run_name>/` — до трёх файлов (`failures.jsonl` появляется только при провалах chunk'ов, см. ниже).

`<bucket>` ∈ `{small, large, local}` — где запускалась модель:

- `small` — закрытые быстрые/дешёвые облачные модели (haiku, gpt-5-mini, gemini-flash и т.п.).
- `large` — закрытые большие облачные модели (sonnet, opus, gpt-5, gemini-pro).
- `local` — модели, запущенные локально (qwen, gemma и др.).

Bucket влияет только на путь и удобство аналитики; формат всех артефактов внутри одинаков. `run_name` уникален в пределах всего `translating/`, поэтому стадия оценки определяет bucket по run_name автоматически (или принимает явный аргумент).

### `translation.md`

**Line-aligned** относительно исходника:

- Ровно столько же строк, сколько в `pilot_original.md`.
- Строка `i` — перевод строки `i` исходника.
- Пустых строк нет, разрывов внутри параграфа нет.

### `config.json`

Воспроизводимая копия запуска:

```json
{
  "run_name": "claude-haiku-4.5_par_by_par",
  "chunking_name": "par_by_par",
  "model_key": "claude-haiku-4.5",
  "model_name": "anthropic/claude-haiku-4.5",
  "endpoint": "https://openrouter.ai/api/v1",
  "prompt_path": "02_translate/system.md",
  "user_prompt_path": "02_translate/user.md",
  "prompt_text": "...полный текст системного промпта на момент запуска...",
  "user_prompt_text": "...полный текст user-промпта на момент запуска...",
  "hyperparameters": {
    "temperature": 0.0,
    "top_p": null,
    "top_k": null,
    "min_p": null,
    "reasoning_effort": null,
    "max_tokens": 16384,
    "extra_body": null
  },
  "cache_strategy": "openrouter_ephemeral",
  "created_at": "2026-05-12T12:34:56Z",
  "failures": {"chunks": 0, "paragraphs": 0}
}
```

- `run_name` / `chunking_name` — slug запуска и стратегии нарезки.
- `model_key` — yaml-key из `configs/models.yaml`.
- `model_name` — slug провайдера (например `anthropic/claude-haiku-4.5`).
- `endpoint` — base_url, через который реально шёл запрос.
- `prompt_path` / `user_prompt_path` — пути относительно `prompts/`.
- `prompt_text` / `user_prompt_text` — инлайн-копии содержимого промпт-файлов на момент запуска. Делает run воспроизводимым даже если файлы в `prompts/` потом изменятся.
- `hyperparameters` — snapshot всех полей `ModelConfig` кроме credentials. `null` для тех, что не отправлялись провайдеру.
- `cache_strategy` ∈ `{"openrouter_ephemeral", "openai_auto", "none"}` — какая стратегия prompt caching использовалась.
- `failures` — суммарные счётчики провалов; детали в `failures.jsonl`.

### Partial-success and `failures.jsonl`

Если LLM возвращает невалидный chunk (не те id, дубликаты, пустое содержимое, парсинг провалился) — Stage 03 делает один retry. Если retry тоже не прошёл, **остальные chunk'и продолжают переводиться независимо**. На failed-chunk'ах строки в `translation.md` заполняются sentinel'ом `[TRANSLATION FAILED]` (по одной на каждый id внутри failed-chunk'а), инвариант 1:1 с `pilot_original.md` сохраняется.

Подробности по failed-chunk'ам пишутся в `data/pilot/translating/<bucket>/<run_name>/failures.jsonl` — одна строка на failed chunk:

```json
{"chunk_id": "5", "range": [25, 29], "ru_paragraph_ids": [25,26,27,28,29],
 "reason": "missing_ids", "expected_ids": [25,26,27,28,29],
 "returned_ids": [25,26,28,29], "attempts": 2,
 "last_response": "...полный текст последнего ответа LLM..."}
```

`reason` ∈ {`parse_failed`, `duplicate_ids`, `missing_ids`, `extra_ids`, `empty_content`}. Файл не создаётся, если все chunk'и успешны.

Рядом с `failures.jsonl` появляется `failure_debug/chunk_<id>/` с полным контекстом для разбора каждого провала: `system_prompt.md`, `user_prompt.md` (с уже подставленным `{chunk}`), `response.md` (последний сырой ответ LLM) и `meta.json` (chunk_id, range, expected_ids, returned_ids, reason, attempts). Эти строки **не** входят в `failures.jsonl` — у него стабильная схема.

Stage 03 (scoring) видит sentinel-строки `[TRANSLATION FAILED]` через `classify_paragraph` и пропускает LLM-вызов (пишет `score: null`); парсинг JSONL не ломается.

### Resume и `progress.jsonl`

Append-only лог завершённых юнитов, лежит рядом с остальными артефактами. Делает запуск устойчивым к падению API или процесса: после каждого успешно переведённого chunk'а (или абзаца в `par_by_par`) одна строка fsync-ится на диск, и повторный вызов `scripts/02_translate.py` с тем же `--run-name` пропускает уже сделанное и дописывает только недостающее.

Формат:

```json
{"type": "chunk", "chunk_id": "5", "translations": {"25": "...", "26": "..."}}
{"type": "paragraph", "id": 42, "translation": "..."}
```

Провалы в лог не пишутся — на следующем прогоне они попробуются заново. Если лог получил незавершённую последнюю строку (kill во время записи), она молча отбрасывается при загрузке. Чтобы стартовать с нуля — удалить директорию `<run_name>/`.

### Соглашение по именам

- `chunk_name` — slug стратегии нарезки (`whole_chapter`, `by_subchapter`, …). Описывает **только** стратегию, не запуск.
- `run_name` — slug запуска: модель + чанкинг + опц. версия (например, `gpt5_whole_chapter`, `gemma_by_subchapter_v2`). Связь с `chunk_name` хранится в `config.json` запуска.

**Историческая заметка (effort-суффиксы в run_name).** Запуски, созданные **до 2026-05-14**, используют legacy-паттерн `<model-key>-<effort>_<chunking>` (например, `large/claude-opus-4.7-high_par_by_par`, `small/qwen3.6-flash_par_by_par`). После аудита CloseRouter (см. [known_issues.md](known_issues.md), запись 9) выяснилось, что effort-tuning через прокси для большинства провайдеров — no-op; соответствующие model-keys удалены из `configs/models.yaml`. Запуски **от 2026-05-14 и далее** используют каноничные имена без effort-суффикса (`claude-opus-4.7`, `qwen3.6-plus` вместо `qwen3.6-flash`). **Legacy-папки на диске не переименовываются** — они остаются доступными по своим архивным именам через `runs:` в scoring-конфигах; новые перетрансляции тех же пар модель/chunking лягут в каноничные папки независимо.

## 03 Оценка

Оценка не зависит от способа перевода: для одной и той же главы всегда работает одинаково.

Оцениваем **по параграфам**: один параграф = одна строка в каждом JSONL. Так точнее, и формат совместим с уже накопленными артефактами в `data/llm_scores/`.

7 итоговых оценок на параграф, но всего **3 вызова LLM** на параграф — шесть критериев свёрнуты в два консолидированных промпта:

- `faithfulness` (source-anchored, RU↔EN) → `accuracy`, `terminology`, `cultural`.
- `english_quality` (target-side) → `fluency`, `style`, `consistency`.
- `factcheck` — отдельный two-sided atomic-fact overlap check (см. ниже).

Каждый консолидированный промпт возвращает JSON с тремя блоками `criteria_assessment` (по одному на критерий внутри). Шкалы 1–10, поля `identified_issues` / `summary` / `final_score` и каталоги (`identified_terms`, `cultural_inventory`, `recurring_elements` и т.д.) сохранены 1:1 с прежними шестью отдельными промптами. На уровне per-paragraph JSONL ничего не меняется — по-прежнему 7 файлов `<criterion>_scores.jsonl`; стадия оценки просто маршрутизирует три критерия из `faithfulness`-ответа и три из `english_quality`-ответа в нужные файлы.

Каждый из двух консолидированных промптов существует в **двух размерах**:

- `prompts/03_scoring/full/<prompt>.md` — полная версия (~3k токенов): полный каталог MT-калек, modality vocabulary mapping, развёрнутые few-shot и Definition-секции. Для крупных оценщиков (sonnet, opus, gpt-5, gemini-pro).
- `prompts/03_scoring/compact/<prompt>.md` — компактная версия (<1k токенов): тот же JSON-контракт и тот же набор правил/few-shot, но без длинных Definition-секций и развёрнутых таблиц-шкал. Для маленьких и локальных моделей (qwen, gemma, haiku).

Выбор размера — через scoring-конфиг per-model. `prompts/03_scoring/old/` — заархивированные шесть одно-критериевых промптов, не используются в новом пайплайне; оставлены для воспроизводимости старых артефактов в `data/llm_scores/`.

### Фактчекинг

Седьмой оценщик устроен иначе. Это **two-sided atomic-fact overlap check**:

1. Из RU-параграфа независимо извлекается список атомарных фактов.
2. Из EN-параграфа независимо извлекается список атомарных фактов.
3. Single-call judge измеряет семантическое пересечение двух списков.
4. По результатам считаются **precision** (какая доля EN-фактов подтверждается в RU), **recall** (какая доля RU-фактов сохранилась в EN) и **F1** как их гармоническое среднее.

В качестве `score` в `factcheck_scores.jsonl` пишется **F1** — float в диапазоне 0..1. В `llm_report` лежит markdown-сводка: `P=… R=… F1=… |RU|=N |EN|=M`, плюс списки `unmatched_ru` (факты, потерянные в переводе) и `unmatched_en` (факты, которых в RU нет — потенциальные галлюцинации).

Подробности реализации (модели, промпты, smoke-тесты) — в [docs/factchecker.md](../docs/factchecker.md). Соглашение по интерфейсу здесь не зависит от реализации: со стороны Stage 03 это просто седьмой оценщик с тем же контрактом JSONL.

**Input:**

- `data/pilot/pilot_original.md`
- `data/pilot/translating/<bucket>/<run_name>/translation.md`

(`data/pilot/chunking/for_evaluation/<NN>_<chapter_slug>.json` Stage 03 не читает — этот артефакт хранится для post-hoc per-subchapter анализа поверх per-paragraph JSONL.)

**Output:**

### `data/pilot/evaluation/<run_name>/<judge>/<criterion>_scores.jsonl`

Сырые per-judge оценки. Один файл на каждую пару (judge, criterion). Каждая строка:

```json
{"id": 0, "source": "...", "translated": "...",
 "judge": "claude-opus-4.7-low", "variant": "full",
 "score": 8, "llm_report": "...markdown report...",
 "usage": {"prompt_tokens": 1240, "completion_tokens": 380,
           "total_tokens": 1620, "cost": 0.0072}}
```

`score`: целое от 0 до 10 для 6 промптовых критериев, F1 (float 0..1) для factcheck. Значения `null` (sentinel skip) и `-1` (ошибка парсинга/LLM) исключаются из средних.

`usage` — сырой dict от провайдера за последний LLM-вызов по этому `(id, criterion)`. Для CloseRouter / OpenAI всегда содержит `prompt_tokens`, `completion_tokens`, `total_tokens` и `cost` (USD за вызов); для reasoning-моделей дополнительно `completion_tokens_details.reasoning_tokens`. Для Anthropic — `input_tokens`/`output_tokens` без `cost`. `null` для маркерных строк (`* * *`, `picture`), `[TRANSLATION FAILED]` и terminal-null после persistent parse failure. Суммы — в `<judge>/meta.json["totals"]`.

### `data/pilot/evaluation/<run_name>/merged_scores.jsonl`

Сводная per-paragraph wide-форма (все судьи в `by_judge`, плюс factcheck). Пересобирается из сырых JSONL после каждого прогона. Пример строки:

```json
{
  "id": 0, "source": "...", "translated": "...",
  "accuracy": {"avg": 7.5, "by_judge": {"claude-opus-4.7-low": 8, "gpt-5.5-low": 7}},
  "terminology": {"avg": 8.0, "by_judge": {"claude-opus-4.7-low": 8, "gpt-5.5-low": 8}},
  "cultural": {"avg": 7.2, "by_judge": {"claude-opus-4.7-low": 7, "gpt-5.5-low": 7}},
  "fluency": {"avg": 8.4, "by_judge": {"claude-opus-4.7-low": 9, "gpt-5.5-low": 8}},
  "style": {"avg": 7.8, "by_judge": {"claude-opus-4.7-low": 8, "gpt-5.5-low": 7}},
  "consistency": {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 8, "gpt-5.5-low": 7}},
  "factcheck": {"f1": 0.91, "p": 0.95, "r": 0.87, "judge": "gpt-5.4-mini-low"}
}
```

### `data/pilot/evaluation/scores.json`

Агрегатный сводный файл — словарь `<bucket>/<run_name> → {7 критериев, каждый с avg и by_judge}`:

```json
{
  "large/claude-opus-4.7-low_par_by_par": {
    "accuracy":    {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 7.5, "gemini-3.1-pro-low": 7.4, "gpt-5.5-low": 7.9}},
    "terminology": {"avg": 8.0, "by_judge": {"claude-opus-4.7-low": 8.1, "gemini-3.1-pro-low": 7.8, "gpt-5.5-low": 8.1}},
    "cultural":    {"avg": 7.2, "by_judge": {"claude-opus-4.7-low": 7.1, "gemini-3.1-pro-low": 7.3, "gpt-5.5-low": 7.2}},
    "fluency":     {"avg": 8.4, "by_judge": {"claude-opus-4.7-low": 8.5, "gemini-3.1-pro-low": 8.2, "gpt-5.5-low": 8.5}},
    "style":       {"avg": 7.8, "by_judge": {"claude-opus-4.7-low": 7.9, "gemini-3.1-pro-low": 7.5, "gpt-5.5-low": 8.0}},
    "consistency": {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 7.7, "gemini-3.1-pro-low": 7.4, "gpt-5.5-low": 7.7}},
    "factcheck":   {"f1_avg": 0.89}
  }
}
```

Ключ верхнего уровня — `<bucket>/<run_name>`. Среднее по каждому критерию считается по всем параграфам в JSONL соответствующего оценщика, **исключая** строки со `score = -1` (маркеры ошибок оценщика). `factcheck.f1_avg` — среднее F1 по параграфам. При новом запуске Stage 03 ключи указанных в config'е runs обновляются; остальные ключи сохраняются. Удаление старых запусков — руками.
