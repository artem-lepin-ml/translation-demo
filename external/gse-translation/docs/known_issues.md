# Известные проблемы и грабли

Up-link: [CLAUDE.md](../CLAUDE.md).

Сюда фиксируем грабли проекта (баги, неочевидные ограничения провайдеров, проблемы воспроизводимости) — чтобы не наступать дважды. Формат записи: краткое описание → симптомы → причина → текущее решение → когда пересмотреть.

---

## 1. JSON output — через промпт, не через `response_format`

**Симптомы.** Часть провайдеров (Anthropic API, некоторые маршруты OpenRouter) не поддерживают параметр `response_format={"type":"json_object"}` или молча его игнорируют. При попытке унифицировать вызовы между судьями — рассинхронизация поведения, у одного судьи JSON жёстко, у другого — drift.

**Причина.** Structured-output поддержка варьируется: у OpenAI она каноническая (gpt-5.x), у Anthropic native API нет такого параметра, у Gemini есть `responseSchema`, OpenRouter частично проксирует — но не всегда. Кросс-провайдерная сравнимость ломается.

**Текущее решение** (spec D3 + D16, **гибрид**). JSON-инструкция остаётся в каждом scoring-промпте (`prompts/03_scoring/v1/*.md` содержит «Respond with a valid JSON object and nothing else» + JSON-структура с `final_score`) — это provider-agnostic база. Сверху — per-model `supports_structured_output: bool` флаг в `configs/models.yaml`; когда `true`, `LLMClient._complete_openai` пробрасывает `response_format={"type":"json_object"}` в провайдер, тот pin'ит JSON на decoder-уровне. Когда `false` — параметр silently drop, prompt-driven fallback. Capability matrix queryable из `https://openrouter.ai/api/v1/models` (поле `supported_parameters` содержит `response_format`/`structured_outputs`). Все cloud-судьи в нашем pool'е поддерживают; local vLLM по умолчанию `false`.

**Когда пересмотреть.** Если на конкретной модели видим JSON drift несмотря на флаг — отключить флаг в YAML, fallback на prompt-engineering (см. лесson 6). Если хотим переход на json_schema strict mode — писать schemas per criterion в `prompts/03_scoring/<variant>/<criterion>.schema.json` и менять `_JUDGE_RESPONSE_FORMAT` в [scoring.py](../src/palimpsest/scoring.py).

---

## 2. Параллельность: `max_concurrency` per-client, не глобально

**Симптомы.** При батарее из нескольких параллельных scoring-процессов начинают вылетать `429 RateLimitError` от провайдера, хотя `cfg.max_concurrency` стоит, скажем, 64.

**Причина.** Семафор живёт внутри одного `LLMClient` (constructor-injected `asyncio.Semaphore`). v2 sequential dispatch держит runs/judges последовательно **внутри одного процесса**. Но `scripts/03_scoring_resume.sh` запускает `large-low` и `small-low` **двумя параллельными процессами**, у каждого свой `LLMClient`, каждый со своим semaphore'ом. Плюс умножение на число criterion'ов: на v1 один параграф = 6 одновременных API-вызовов. Реальная нагрузка на провайдер ≈ (параллельных процессов) × (max_concurrency) × (criteria per paragraph).

**Текущее решение.** При планировании батареи считать кратность. При первых 429 — снижать `max_concurrency` в конфиге (с 64 на 32, например). `LLMClient` уже умеет retry с экспоненциальным backoff на `RateLimitError`, так что разовые 429 не критичны; критично когда они становятся систематикой.

**Когда пересмотреть.** Если переход на больший pilot (>1000 параграфов) или multi-judge battery с 3+ моделями начинает упираться в провайдерские лимиты — ввести глобальный rate-limit gate (per-provider, per-model) на уровне `LLMClient.complete` через shared semaphore по `model_name`.

---

## 3. Стохастичность LLM-багов

**Симптомы.** Smoke прогон на 50 параграфах ловит 49/50 fail для одного критерия. Rerun на ОДНОМ из этих 50 параграфов даёт валидный ответ. Кажется, что баг «починился» — на самом деле он стохастический.

**Причина.** `temperature=1.0` (как у Gemini 3.x — обязательно, и у gpt-5.x — рекомендуется для естественности) даёт распределение ответов. Баги вида «модель путает формат» имеют вероятность срабатывания на конкретном параграфе, скажем, 90% — но на single-paragraph repro попадаешь в 10% хвоста и думаешь, что всё ок.

**Текущее решение.** Если smoke ловит регрессию — **фиксировать список paragraph_idx из smoke** (например, в `data/pilot/evaluation_smoke/<run>/<judge>/parse_failures.jsonl`), не уходить на N=1 single-paragraph repro без подтверждения, что баг даёт ≥80% воспроизводимости.

**Когда пересмотреть.** Если появится возможность зафиксировать seed (некоторые провайдеры поддерживают `seed` параметр) — для regression tests'ов это снимет головную боль. Сейчас не реализовано.

---

## 4. Soft-fallback `score = -1` на parse fail — антипаттерн

**Симптомы.** При неудаче парсинга LLM-ответа (malformed JSON, missing key, score out-of-range) writer писал в criterion-JSONL row с `score: -1` и `llm_report: "missing criterion X in Y response"`. Aggregation должен был помнить про этот sentinel и фильтровать (`v != -1`). Raw-ответ модели **затирался** сообщением — диагностика терялась.

**Причина.** Соблазн «row есть — resume увидит — перепробует»: семантически у тебя выходит, что параграф **обработан**, но score «недействителен». Аналитик читает JSONL, видит row, думает «ок, оценка есть», смотрит в report — а там административное сообщение. Дезориентирует.

**Текущее решение** (spec D12 + D13). Никакого `-1` на диске. parse fail = `JudgeParseError` exception, никакого row в criterion-JSONL не пишется; raw уходит в отдельный `<judge>/parse_failures.jsonl` (append-only diagnostic log). После 3 escalation'ов для одного `(paragraph, criterion)` — записывается terminal `score: null` с указателем на `parse_failures.jsonl`. Aggregation теперь фильтрует только `None`, никаких specials.

**Когда пересмотреть.** Если parse-failure rate станет систематически >10% на любой модели — это сигнал что либо промпт слишком жёсткий для модели, либо JSON-инструкцию надо усилить, либо в самом деле временно вернуть `response_format=json_object` для этого судьи (см. запись 1). До того — fail-fast и расследовать через `parse_failures.jsonl`.

---

## 5. `asyncio.gather` отменяет сиблинг-таски при первом исключении

**Симптомы.** Сценарий: 6 параллельных criterion-вызовов через `asyncio.gather`, один криterion падает в `JudgeParseError`, gather пробрасывает первое исключение, остальные 5 уже-в-полёте корутин **отменяются**. На smoke 50 paragraphs × 6 criteria получили 0 валидных rows в criterion-JSONL вместо 250 ожидаемых (5 успешных × 50 paragraphs), несмотря на то что 5/6 criteria не имели проблем с парсингом.

**Причина.** Default behaviour of `asyncio.gather(*coros)`: при первом необработанном исключении gather raises и **cancel'ит** остальные in-flight tasks. Coroutines that already returned a value still have that value buffered in gather, but it's discarded together with the raise. Net effect: один битый criterion = весь paragraph «не оценён», даже если другие criterion-coroutines уже успешно вернулись.

**Текущее решение** (spec D14). `score_paragraph` теперь **не raise** наружу. Каждая `_one(criterion)` coroutine ловит свой собственный `JudgeParseError` после исчерпания retry и **возвращает экземпляр исключения как значение** в result map. `asyncio.gather` собирает гибридный список `[dict | JudgeParseError]` без отмен. Caller (`_score_run_for_judge._process`) расщепляет: dicts → criterion-JSONL, exceptions → `parse_failures.jsonl`. После записи всех valid rows — re-raise первого исключения для task-level escalation.

**Когда пересмотреть.** Если когда-нибудь захочется fail-fast (e.g., бюджет на API очень ограничен и нет смысла продолжать оценивать paragraph если criteria уже фейлятся) — добавить флаг в `score_paragraph`. Сейчас YAGNI.

**Альтернативный паттерн** для будущих parallel-LLM-call сценариев: `asyncio.gather(..., return_exceptions=True)` (стандартная idiom) — но в нашем случае мы хотели контролировать формат return value (tuple vs Exception), так что explicit catch цикл оказался чище.

---

## 6. Хвостовая JSON-инструкция в промпте не всегда побеждает role priming

**Симптомы.** На smoke 2026-05-14: `gpt-5.5-low` на `fluency.md` промпте дрейфовал в markdown эссе («The translation is generally accurate, fluent...») 49 из 50 параграфов. У 5 других criterion-промптов (accuracy, terminology, cultural, style, consistency) — 0 дрейфов на том же smoke. Все промпты имели **идентичный JSON-only directive в хвосте** («Respond with a valid JSON object and nothing else», CRITICAL RULES, JSON skeleton).

**Причина.** Содержимое `fluency.md` (роль «expert translator and linguist», задача «evaluate fluency») priming'ует gpt-5.5-low в режим «translation review essay» сильнее, чем хвостовая инструкция способна перекрыть. Attention к началу промпта дороже attention к концу: модель формирует план ответа задолго до того, как доходит до «Output Format» секции в самом конце 76-строчного промпта.

**Текущее решение** (spec D15). Для упрямых criterion-промптов добавляем в **самое начало** файла жёсткий header:

```markdown
# OUTPUT CONTRACT — READ FIRST

Your response MUST be a single valid JSON object matching the schema in the "Output Format" section at the end of this prompt. No prose introduction. No markdown headings. No "## Overall assessment" sections. Start your reply with `{` and end with `}`.

If you have observations that don't fit the JSON schema, drop them. The schema is the complete contract. Failure to emit valid JSON means the response is discarded.

---

<original prompt content...>
```

После применения к `fluency.md`: smoke от 49/50 fails ушёл к **0/50 fails**, score distribution mean=9.18 range 8-10 (реальная оценка, не шаблон).

**Обновление 2026-05-14 (D16, lesson #1)**: header в `fluency.md` **удалён**. После включения per-model SO toggle и пробрасывания `response_format={"type":"json_object"}` decoder-level constraint перекрывает role-priming drift полностью — на втором smoke с SO=on и без header'а получили 0/50 fails. D15 остаётся в спеке как **fallback-pattern** для провайдеров без structured-output support (local vLLM, или новый провайдер с unknown capability). Symmetric prompts > asymmetric headers.

**Когда применять fallback header**. При подключении провайдера, у которого `supports_structured_output: false` (local vLLM без guided-decoding, или новая cloud-модель не успевшая получить флаг) — мониторить `parse_failures.jsonl` per criterion в первом smoke. Любой criterion с failure rate >10% — кандидат на header.

---

## 7. CloseRouter: алиасы провайдеров и пропавшие модели

**Симптомы.** `google/gemini-3.1-flash-lite` и `qwen/qwen3.6-flash` возвращают HTTP 404 от CloseRouter; запросы валятся ещё до отправки в провайдера.

**Причина.** В каталоге прокси этих slug'ов попросту нет: для Gemini Flash-Lite доступен только preview-вариант `google/gemini-3.1-flash-lite-preview`, для Qwen — `qwen/qwen3.6-plus` (более жирный sibling, той же серии). Имена брали из публичной документации провайдеров, у CloseRouter каталог уже.

**Текущее решение.** В `configs/models.yaml` использовать только тот name, который реально есть в `GET /v1/models`. Список валидных — см. [references/private/closerouter-param-semantics.md](../references/private/closerouter-param-semantics.md) и [references/private/models.md](../references/private/models.md). Никаких fallback-алиасов в клиенте — пусть 404 поднимается явно.

**Когда пересмотреть.** Если CloseRouter добавит недостающие slug'и (или мы сменим прокси) — обновить yaml и эту запись.

---

## 8. Anthropic через OpenAI-compat `/chat/completions` — 502 на forced tool-call

**Симптомы.** При попытке маршрутизировать `anthropic/claude-opus-4.7` (и иногда sonnet-4.6) через CloseRouter'овский `/chat/completions` с параметром `tool_choice` получали HTTP 502 от прокси; haiku-4.5 работал, но непредсказуемо.

**Причина.** Прокси использует litellm как bridge для Anthropic. На ответе, где у модели нет `text`-блока (только `tool_use`), `transform_response` падает на NoneType — bridge рассчитан на текстовые ответы, не на pure tool-call. Sonnet/Opus возвращают только `tool_use` чаще, чем haiku, поэтому крэшатся стабильнее.

**Текущее решение** (commit `1f83de6`). `LLMClient._complete_anthropic` использует Anthropic SDK напрямую против `/messages` (с `_anthropic_base_url`, отрезающим `/v1` из base_url'а). `response_format={"type":"json_object"}` коэрсится в forced `tool_choice` для tool `emit_response` с `_DEFAULT_JUDGE_SCHEMA` — это работает на всех трёх Claude'ах через native endpoint. Эмпирические данные — [references/private/closerouter-param-semantics.md](../references/private/closerouter-param-semantics.md).

**Когда пересмотреть.** Если CloseRouter обновит litellm и перестанет ронять transform_response на tool-only ответах — можно вернуть Anthropic на общий OpenAI-compat путь и упростить клиент. До того — native SDK обязателен.

---

## 9. `reasoning.effort` молча игнорируется на большинстве провайдеров через CloseRouter

**Симптомы.** Передаём `reasoning_effort: "high"` / `reasoning_effort: "low"` в configs/models.yaml, ожидаем кратной разницы в `reasoning_tokens` — а на OpenAI / Anthropic / Gemini / Qwen различия лежат в пределах ±10% от plain. Думаем, что effort крутим, а на деле получаем шум.

**Причина.** OpenRouter-style nested `reasoning.effort` body field прокси принимает (4xx не возвращает), но на upstream-провайдер не транслирует. Реально работает только в двух случаях:

- **DeepSeek (`deepseek/deepseek-v4-pro`)** — nested `reasoning.effort` ✅ (164→387→578 reasoning_t для plain/low/high).
- **GLM (`z-ai/glm-5.1`)** — top-level `reasoning_effort` ✅ (310→525 для low→high).

Для OpenAI gpt-5.x тюнинг effort'а доступен **только** через прокси-алиасы `openai/custom-gpt-5.5-{low,medium,high,xhigh}` (37→58→73→128 reasoning_t). Anthropic effort-рычага через CloseRouter нет вообще; thinking — отдельный механизм, см. ниже. Подробная матрица — [references/private/closerouter-param-semantics.md](../references/private/closerouter-param-semantics.md).

**Текущее решение.** `configs/models.yaml` объявляет `-low/-high` варианты только там, где effort реально работает (DeepSeek, GLM, gpt-5.x через custom-алиасы). Старые `-low/-high` keys для Anthropic/Gemini удалены (commit `63fefc3`).

**Когда пересмотреть.** Если CloseRouter начнёт пробрасывать `reasoning.effort` в больше провайдеров — recheck'нуть таблицу probes'ами и расширить yaml. До того — не плодить мёртвые `-low/-high` ключи.

---

## 10. Anthropic SDK 0.71 не работает на Python 3.14

**Симптомы.** `import anthropic` падает с `AttributeError: type object 'Union' has no attribute '__discriminator__'` под Python 3.14.

**Причина.** Anthropic SDK 0.71 использует runtime-инспекцию `typing.Union.__discriminator__`, которой нет в стандартной библиотеке 3.14 (изменения в typing module). Issue открыт в апстриме, фикса пока нет.

**Текущее решение.** Проект пиннит Python 3.13 локальным `.python-version` в корне (gitignored, см. `.gitignore`). `uv sync` создаёт `.venv` на 3.13; CI/коллабораторам — `uv python pin 3.13 && uv sync`.

**Когда пересмотреть.** Когда Anthropic SDK обновится до версии, совместимой с 3.14. До того — Python 3.13 обязательна.

---

## 11. Opus 4.7 заворачивает `tool_use.input` в синтетический ключ

**Симптомы.** При forced tool-call'е через `/messages` с `tool_choice={"type":"tool","name":"emit_response"}` Opus 4.7 иногда возвращает `tool_use.input` вида `{"response": {"final_score": 8, "summary": "..."}}` или `{"$PARAMETER_NAME": {...}}` вместо ожидаемого `{"final_score": 8, ...}` напрямую. parse_judge_response падает с `KeyError: 'final_score'`.

**Причина.** Спекуляция: Opus иногда «перестраховывается» и оборачивает payload в ещё один уровень, видимо, считая что input-schema описывает контейнер, а не сам объект. На haiku и sonnet не наблюдалось. Стохастично — не каждый вызов.

**Текущее решение** (commit `1f83de6`, [client.py:319](../src/palimpsest/llm/client.py)). В `_complete_anthropic` стоит unwrap-once heuristic: если `tool_use.input` — dict с ровно одним ключом, чьё значение — dict с `final_score`, разворачиваем один уровень. Срабатывание логируется в stderr как `[anthropic-unwrap] <model>: unwrapped <key>` для аудита.

**Когда пересмотреть.** Если Anthropic пофиксит обёртку (или мы перестанем использовать opus) — heuristic'у можно убрать. До того — лог покажет, как часто она срабатывает в проде.

---

## 12. Атомарная запись derived-артефактов (comparison.jsonl, reports/<judge>.jsonl)

**Симптомы.** Старый `merged_scores.jsonl` писался построчно через `open(..., "w")` — если процесс убивали в момент записи, оставалась усечённая JSONL с битой последней строкой. Следующий шаг (агрегация / чтение в Jupyter) падал на `json.JSONDecodeError`.

**Причина.** Любой POSIX `write()` неатомарен на уровне файла — только append-write < 4KB атомарен на уровне ядра. Полная перезапись (`"w"` mode) проходит через truncate-then-write, и kill-9 в середине оставляет файл в промежуточном состоянии.

**Текущее решение** (spec S8 + lesson from docs/analysis.md C7). Все derived-builders (`build_comparison_jsonl`, `build_judge_reports`) пишут в `out_path.with_suffix(".jsonl.tmp")`, после полного завершения вызывают `tmp.replace(out_path)`. `Path.replace` под капотом — `os.rename`, который атомарен в пределах одной файловой системы. Кто читает `comparison.jsonl` — либо видит полный старый файл, либо полный новый, никогда не половину.

**Когда пересмотреть.** Если derived JSONL'ы станут многогигабайтными и tmp+rename начнёт стоить заметно в IO — рассмотреть streaming write с separate checkpoint marker. До того — YAGNI.
