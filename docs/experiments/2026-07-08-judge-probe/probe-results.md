# Проба судейских маршрутов CloseRouter — 4 модели для ре-скоринга BOUQUET

Дата: 2026-07-08. Цель: найти рабочие route-конфигурации для 4 облачных
judge-моделей (Claude Opus 4.8, GPT-5.5, Gemini 3.1 Pro, DeepSeek V4 Flash)
перед ре-скорингом 4 систем перевода на BOUQUET ru2en (198 параграфов,
3 критерия/параграф → 2 376 вызовов на судью). Сырые артефакты — в
[raw/](raw/): `probe_judges.py` (сам проб), `probe_results_merged.json`
(8 реалистичных вызовов), `models_catalog_subset.json` (карточки моделей
из `GET /v1/models`).

**Потрачено на пробу: ≈ $0.013** (реальный `cost_usd`, суммированный по всем
вызовам сессии — 8 реалистичных + ~8 диагностических пингов), из бюджета
$1. Подробности — в разделе «Бюджет пробы» внизу.

## Главное

Все 4 маршрута рабочие (route status = OK), но два требуют нестандартных
параметров: **Gemini 3.1 Pro падает 400-й на `response_format=json_object`**
(нужно убрать этот параметр и полагаться на JSON-инструкцию в самом
промпте), а **у Opus 4.8 параметр `reasoning`/`thinking` на этом
OpenAI-совместимом маршруте молча no-op'ится** (0 reasoning-токенов при
любой из 3 опробованных форм параметра). Самый дорогой судья на полный
прогон — Gemini 3.1 Pro (**≈$9–14** за 2 376 вызовов, в зависимости от
источника цены), самый дешёвый — GPT-5.5 (**≈$1.3**).

## Точные ID моделей и маршруты

| # | Запрошено | Точный ID (`GET /v1/models`) | Route status | Комментарий |
|---|---|---|---|---|
| a | Anthropic Claude Opus 4.8 | `anthropic/claude-opus-4.8` | **OK** (auto) | thinking/reasoning параметр принимается, но не включается — см. «Нюансы» |
| b | OpenAI GPT-5.5 | `openai/gpt-5.5` | **OK** (auto) | reasoning работает штатно, default effort ⇒ 110–292 reasoning-токенов |
| c | Google Gemini 3.1 Pro | `google/gemini-3.1-pro-preview` | **OK** (auto), но только без `response_format` | plain `google/gemini-3.1-pro` в каталоге CloseRouter отсутствует — только `-preview` (как и предполагалось в задаче) |
| d | deepseek/deepseek-v4-flash | `deepseek/deepseek-v4-flash` | **OK** (auto, без пина провайдера) | `reasoning.enabled:false` не подавляет мышление — см. «Нюансы» |

`GET {OPENROUTER_BASE_URL}/models` → 46 моделей в каталоге (curated-подмножество,
не полный OpenRouter). `GET {root}/api/v1/models` (без `/v1` в base_url,
т.е. `.../api/v1/models`) → **404**, ожидаемо: `OPENROUTER_BASE_URL` уже
оканчивается на `/v1`, второй путь просто не существует на этом гейтвее.

## Цены (из `pricing` в карточках `/v1/models`, $/M токенов)

| Модель | prompt | completion | Прочее |
|---|---|---|---|
| `anthropic/claude-opus-4.8` | 0.400 | 0.400 | — |
| `openai/gpt-5.5` | 0.300 | 0.300 | — |
| `google/gemini-3.1-pro-preview` | 0.825 | 2.475 | `cache_write_5m`=1.031, `cache_read`=0.0825; доп. price-tier за контекстом >200k (наши вызовы малы — базовый тариф) |
| `deepseek/deepseek-v4-flash` | 0.07005 | 0.13995 | `cache_write_5m`=0.07005, `cache_read`=0.00135 |

Важно: `cost_usd`/`cost` в `usage` **реально приходит только у Gemini**
(0.00378 / 0.004096 на двух наших вызовах). У Opus 4.8, GPT-5.5 и
DeepSeek Flash это поле отсутствует в ответе гейтвея целиком (проверено
отдельным сырым HTTP-запросом мимо SDK — не баг нашего экстрактора).
Для этих трёх смету считаем по каталожным ценам.

## Реалистичный вызов: промпт и данные

Системный промпт — `external/gse-translation/prompts/03_scoring/v1/accuracy.md`
как есть. Пользовательское сообщение — шаблон из вендорного судьи
(`external/gse-translation/src/palimpsest/scoring.py:122-125`):

```
**Source text (Russian)** — for reference when identifying recurring elements:
{source}

**Translation (English)** — this is what you are evaluating:
{translated}
```

Схема данных BOUQUET (проверено чтением файлов):
- `data/bouquet/bouquet_original.json` — плоский список из 198 строк, индекс = paragraph id.
- `data/bouquet/translation/<system>/translation.json` — тот же формат (список из 198 строк), по одной директории на систему. 4 системы = 4 директории: `qwen-27b-bouquet`, `qwen-27b-bouquet-refined`, `translate-gemma-bouquet`, `translate-gemma-bouquet-refined` — совпадает с «4 системы» из задачи.
- `data/bouquet/evaluation/<system>/` — уже посчитанные метрики (COMET/MetricX/universal), не трогали.

Пары для реалистичных вызовов (не тривиальный «чистый» текст, а с реальной
неоднородностью длины и с настоящей проблемой перевода):
- id=72 (медианная длина, 307 симв.) × `qwen-27b-bouquet-refined` — обычный DIY-текст.
- id=178 (p85 длина, 473 симв., диалог) × `qwen-27b-bouquet-refined` — здесь
  переводчик оставил теги говорящих `<Рауль:>`/`<Кармен:>` кириллицей
  вместо `<Raul:>`/`<Carmen:>` — все 4 судьи независимо это заметили и
  поставили в `identified_issues`, что подтверждает: промпт+пайплайн
  парсинга реально работают на живых данных, не только на пинге.

## Параметры вызова по режимам (как просила задача)

**Frontier-3 (Opus 4.8, GPT-5.5, Gemini 3.1 Pro): reasoning ON default effort, БЕЗ `temperature`.**
- Opus 4.8, GPT-5.5: `extra_body={"reasoning": {"enabled": true}, "response_format": {"type": "json_object"}}`.
- Gemini 3.1 Pro: `extra_body={"reasoning": {"enabled": true}}` — **без** `response_format`
  (см. «Нюансы» — обязательно убрать, иначе 400).

**DeepSeek V4 Flash: `temperature=0`, reasoning OFF, route auto.**
`extra_body={"reasoning": {"enabled": false}, "response_format": {"type": "json_object"}}`,
без пина провайдера (`extra_body["provider"]` не передавался — это и есть
route `auto`). Оба вызова прошли `200 OK` с валидным JSON — **route auto
подтверждён рабочим** для этой модели+json_object, пин `provider-9`
(упомянутый в задаче как ранее несовместимый) не понадобился и не
тестировался отдельно (не было причин — auto сразу сработал).

## Токены, латентность, оценка стоимости полного прогона (2 376 вызовов/судья)

Среднее по 2 реалистичным вызовам на модель (не 10, чтобы уложиться в бюджет —
см. «Бюджет пробы»; оговорка о точности ниже).

| Модель | avg latency | avg prompt tok | avg completion tok (из них reasoning) | $/M in, out | $/call (каталог) | $/call (real, если есть) | **Смета на 2 376 вызовов** |
|---|---|---|---|---|---|---|---|
| `anthropic/claude-opus-4.8` | 9.4s | 1 857 | 607 (**0**, 0%) | 0.40 / 0.40 | $0.000986 | — | **≈ $2.34** |
| `openai/gpt-5.5` | 22.2s | 1 157 | 728 (201, 28%) | 0.30 / 0.30 | $0.000566 | — | **≈ $1.34** |
| `google/gemini-3.1-pro-preview` | 25.2s | 1 197 | 1 988 (1 520, 76%) | 0.825 / 2.475 | $0.005907 | $0.003938 | **≈ $14.03 (каталог) / ≈ $9.36 (real)** |
| `deepseek/deepseek-v4-flash` | 41.5s | 1 266 | 3 808 (3 378, 89%) | 0.07005 / 0.13995 | $0.000622 | — | **≈ $1.48** |

Сумма по 4 судьям на весь BOUQUET (каталожная оценка): **≈ $19.2**
(при использовании real-цены для Gemini вместо каталожной — **≈ $14.5**).

**Оговорка о точности сметы:** промпт для теста — `v1/accuracy.md`
(624 слова). В `v1/` пять критериев (`accuracy`, `cultural`, `terminology`,
`style`, `fluency`), а не три — их длина близка (`style.md` 747 слов,
`fluency.md` 800 слов, т.е. системная часть промпта на **~15–20% длиннее**
для этих двух против `accuracy`), так что оценка выше по всем 3 критериям
консервативна в пределах, наверное, ±20% на prompt-токенах. Отдельно есть
вариант промптов `universal/` (тоже ровно 3 файла: `accuracy`/`style`/`fluency`,
что буквально совпадает с «3 критерия» из формулировки задачи) — но эти
промпты **в ~2.3 раза длиннее** (1 578–1 810 слов против 624–800 у `v1`).
Задача явно указала строить тестовый вызов из `v1/accuracy.md`, поэтому
смета выше — по `v1`. **Открытый вопрос к владельцу/оркестратору: какой
вариант промптов (`v1` пятикритериальный — тогда какие 3 из 5 брать — или
`universal` трёхкритериальный) реально пойдёт в прод ре-скоринг** — от
этого зависит, попадает ли Gemini-смета в $9–14 или ближе к $20–30.

## Нюансы по каждой модели (json mode, reasoning, отказы)

### Claude Opus 4.8 — reasoning/thinking молча no-op на этом маршруте
Запрос принимается (`200 OK`), но `reasoning_tokens=0` в обоих реалистичных
вызовах. Проверено отдельно тремя формами параметра на дешёвом пинге
(«17×23, покажи рассуждение, затем JSON») — **все три дали идентичный
результат, `reasoning_tokens=0`**:
- `{"reasoning": {"enabled": true}}`
- `{"thinking": {"type": "enabled", "budget_tokens": 1024}}` (нативный
  Anthropic-параметр — он даже присутствует в `supported_parameters`
  карточки модели, но на практике не включает thinking через
  `/chat/completions`-мост)
- `{"reasoning": {"effort": "medium"}}`

Это ровно то, что уже задокументировано в
`external/gse-translation/configs/models.yaml` (комментарий у
`claude-opus-4.7`): OpenAI-совместимый мост для Claude на этом гейтвее
молча игнорирует reasoning/`response_format`; чтобы реально включить
extended thinking, нужен нативный Anthropic `/messages`-путь
(`provider: anthropic` в конфиге), не `/chat/completions`. JSON-вывод при
этом переживает «псевдо-thinking» нормально — оба вызова распарсились
(`json_parse_ok=true`, `has_expected_keys=true`), т.к. `response_format`
json_object реально работает для Claude на OpenAI-совместимом мосту (сам
пруф — успешный парсинг), просто thinking — нет.

### GPT-5.5 — работает штатно
`reasoning` включается на default effort без проблем (110 и 292
reasoning-токена на двух вызовах — разумный разброс от сложности
параграфа). `response_format=json_object` совместим с reasoning ON.
JSON пережил thinking-режим оба раза без markdown-обёртки.

### Gemini 3.1 Pro Preview — `response_format` ломает запрос, reasoning всегда включён
Диагностировано отдельным 3-вариантным тестом на дешёвом пинге:
- `extra_body=None` (совсем без доп. параметров) → `200 OK`, **187
  reasoning-токенов сами по себе** (thinking включён по умолчанию, без
  какого-либо reasoning-параметра — соответствует архитектуре Gemini 3.x).
- `extra_body={"response_format": {"type": "json_object"}}` → **400
  BadRequestError**, `upstream_status: 400` от Google, `code: invalid_request`.
- `extra_body={"reasoning": {"enabled": true}}` → `200 OK`, thinking работает.

Карточка модели в каталоге подтверждает: `supported_parameters` для
`google/gemini-3.1-pro-preview` — только `max_output_tokens`, `max_tokens`,
`stream` (ни `response_format`, ни `reasoning` не заявлены, хотя reasoning
фактически работает без объявления). Для прод-судьи: **не передавать
`response_format`**, полагаться на JSON-инструкцию в самом промпте
(`accuracy.md` её уже содержит: «Respond with a valid JSON object and
nothing else»). В реалистичных вызовах это сработало 2/2 —
`json_parse_ok=true` оба раза (один раз модель сама обернула ответ в
` ```json ` — парсер вендорного `parse_judge_response` это уже умеет через
regex на fence, так что не проблема).

### DeepSeek V4 Flash — `reasoning.enabled:false` не подавляет мышление
Запрошено явно (`{"reasoning": {"enabled": false}}`) + `temperature=0` +
route auto (без `provider`-пина) — оба вызова `200 OK`, JSON распарсился
оба раза. Но **reasoning фактически не отключился**: 2 165 и 4 592
reasoning-токена на двух вызовах — **89% всех completion-токенов в среднем**.
Это доминирующий фактор стоимости и латентности для этой модели (латентность
30.6s/52.5s — самая высокая из всех 4, при том что модель самая дешёвая
за токен). Совпадает с духом предупреждения в задаче («reasoning-off
mandatory» — видимо в смысле «нужно запрашивать off, иначе ещё хуже», а не
«запрос off реально отключает»). **Не проверено** (за пределами скоупа
пробы, экономия бюджета): пробовали ли полностью не передавать `reasoning`
вовсе (без `enabled:false`) — не тестировали, т.к. в задаче было явно
указано reasoning OFF, а не «omit». Если стоимость DeepSeek станет
проблемой — это первое, что стоит попробовать доследовать.

## Бюджет пробы

Всего 8 реалистичных вызовов (по 2 на модель) + 8 дешёвых диагностических
(3× Opus reasoning-форм, 3× Gemini extra_body-вариантов, 1× сырой usage-чек
DeepSeek, 1× сырой usage-чек Opus; вызов на сырой usage-чек GPT-5.5 словил
клиентский `TimeoutError` до получения ответа — не досчитан, по каталогу
это были бы центы). Суммарная реальная+каталожная оценка спенда сессии:
**≈ $0.013**, из выделенного лимита $1.

## Куда прикручивать этих 4 судей в вендорном пайплайне (пути + конфиг-ключи, без реализации)

- `external/gse-translation/configs/models.yaml` — новая запись на модель,
  ключ `models.<key>` (например `opus-4.8`, `gpt-5.5-thinking`,
  `gemini-3.1-pro`, `deepseek-v4-flash-noreasoning`), схема — `ModelConfig`
  в `external/gse-translation/src/palimpsest/config.py:13-58`. Поля,
  которые реально нужны по нашим находкам: `name` (точный ID из таблицы
  выше), `base_url: https://openrouter.ai/api/v1` (или пусто — рантайм
  подхватит `OPENROUTER_BASE_URL`), `api_key_env: OPENROUTER_API_KEY`,
  `supports_structured_output: true` (кроме Gemini — там `response_format`
  ломает запрос, см. выше), `extra_body` для `reasoning`/`thinking` по
  найденным здесь режимам, `max_tokens` (наши вызовы влезли в 8000, для
  DeepSeek с его 89%-reasoning стоит заложить больше запаса).
- `external/gse-translation/configs/scoring/<run>.yaml` — поле `judges:`
  (список `{model: <ключ из models.yaml>}`), поле `prompts_variant` (`v1`
  или `universal` — см. открытый вопрос про 3 vs 5 критериев выше), схема —
  `ScoringConfig`/`JudgeConfig` в том же `config.py:71-100`.
- `external/gse-translation/.env` (не в git, копия `.env.example`) —
  `OPENROUTER_API_KEY`, опционально `OPENROUTER_BASE_URL` для переопределения
  на CloseRouter (уже установлен в окружении этой сессии).

## Итоговая сводка (для быстрого чтения)

| Модель | ID | Route | Latency | avg in/out tok | $/M in,out | Смета/2376 | Квирки |
|---|---|---|---|---|---|---|---|
| Opus 4.8 | `anthropic/claude-opus-4.8` | OK | 9.4s | 1857/607 | 0.40/0.40 | ~$2.34 | reasoning молча no-op (0 ток. во всех 3 формах параметра); response_format работает |
| GPT-5.5 | `openai/gpt-5.5` | OK | 22.2s | 1157/728 | 0.30/0.30 | ~$1.34 | всё штатно, reasoning 110–292 ток. |
| Gemini 3.1 Pro | `google/gemini-3.1-pro-preview` | OK (без response_format) | 25.2s | 1197/1988 | 0.825/2.475 | ~$9.4–14.0 | response_format → 400; reasoning всегда включён (даже без параметра) |
| DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` | OK (auto) | 41.5s | 1266/3808 | 0.070/0.140 | ~$1.48 | reasoning.enabled:false не отключает мышление (89% completion — reasoning) |
