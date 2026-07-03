# Palimpsest — Реестр моделей: дизайн-спека (v2, после /verify-spec)

Up-link: [docs/subsystems/webapp.md](../../subsystems/webapp.md) · дизайн-система: [webapp-ui-design.md](../../subsystems/webapp-ui-design.md) · контракт: [2026-06-30-demo-contracts.md](2026-06-30-demo-contracts.md)

Статус: ✅ реализовано и смержено в `dev-demo` (merge `e592be1` + калибровка Test-эндпоинта `0dc1caf`/`eb97124`). As-built описание — [docs/subsystems/webapp.md](../../subsystems/webapp.md). Этот документ — исторический дизайн (T1–T8), при расхождениях истина — webapp.md.

## Цель и скоуп

Реестр моделей в демо отрисован, но **«картонный»**: строки показываются, вызовы не работают, параметры не применяются. Оживить существующее (не строить форму создания):

1. 8 моделей (5 OpenRouter + 3 локальных vLLM) реально вызываются с **корректными для каждой** параметрами (по живому каталогу).
2. Per-model **Test** — реальный лёгкий запрос: извлечь термины из 1 абзаца → доля совпадений с эталоном.
3. **Edit** модели сразу применяется ко всем оценщикам.
4. Каждый реальный вызов **защищён бюджетом** (потолок $2) и залогирован со стоимостью.
5. Фронт **расширяет** `variant-a` (без новых токенов/классов).

**Вне скоупа:** мастер создания моделей с нуля; живые прогоны 3 локальных vLLM (сервер не поднят); смена wire-DTO; **`response_format`/structured-output и provider-dispatch** (см. «Выведено из скоупа»).

## Критерии успеха (измеримые)

- **S1.** После `seed.py` в таблице `model` есть все 8 строк с params по матрице (проверка: `SELECT count(*)=8`).
- **S2.** Test каждой из 5 OR-моделей возвращает `200 {ok, share, tokens, costUsd}` реальным вызовом через `LLMClient`; `ok = (нет ошибки запроса/парсинга) AND share ≥ 0.5`.
- **S3.** Запрос каждой модели содержит **только** поддерживаемые ею поля (проверка по JSONL-логу отправленных params); `temperature` не уходит sonnet/gpt/gemini/haiku.
- **S4.** Правка `params` модели меняет поведение ссылающихся критериев на следующем `/evaluate` (проверка по логу запроса); удаление используемой модели → 409.
- **S5.** Пустой `api_key` в строке + `OPENROUTER_API_KEY` в env → Test проходит (env-fallback работает).
- **S6.** При достижении $2 следующий реальный вызов **отклоняется до отправки** (`check_budget` → `ok:false/skip`), не после списания.
- **S7.** e2e-прогон уложился в $2; на каждый вызов записаны токены (вкл. reasoning) и `costUsd`.

## 8 моделей и матрица (живой каталог OpenRouter, 2026-07-01)

| модель | temperature | reasoning | sampling | max_tokens cap |
|---|---|---|---|---|
| `anthropic/claude-haiku-4.5` | опускаем (D3) | `{max_tokens:2048}` (effort→400) | top_k ✓ · min_p ✗ | 64k |
| `anthropic/claude-sonnet-5` | опускаем (no-op) | `{effort:<probe>}` low→max | — | 128k |
| `google/gemini-3.5-flash` | опускаем | `{effort:<probe>}` обязателен | top_k ✗ | 65k |
| `openai/gpt-5.4-mini` | опускаем | `{effort:<probe>}` (нет `minimal`) | — | 128k |
| `qwen/qwen3.6-plus` | 0.7 | `{effort:<probe>}` | top_k ✗ | 65k |
| `Qwen/Qwen3-4B-Thinking-2507` (vLLM) | 0.6 | thinking-only | `extra_body{top_k:20,min_p:0}` | 262k ctx |
| `Infomaniak-AI/vllm-translategemma-27b-it` (vLLM) | greedy | нет | — (спец-формат) | ~2k ctx |
| `Qwen/Qwen3.6-27B` (vLLM) | 1.0 | `extra_body{enable_thinking:true}` | `extra_body{top_k:20,min_p:0}` | 262k ctx |

`<probe>` = конкретное значение effort берём из того, что OpenRouter вернёт как default, и логируем (Stage 2), не хардкодим. Полные заметки/источники — task output `we2n7stco`.

## Задачи (numbered)

- **T1. Seed.** Расширить [seed.py](../../../src/palimpsest/webapp/seed.py): вставить 8 строк `model` с `params_json` по матрице; **перенацелить seed-критерии** (`criterion.model_name` сейчас все на `openai/gpt-4o-mini` — вне матрицы) хотя бы на одну модель матрицы (дефолт — `openai/gpt-5.4-mini`; реализовано на T1 напрямую, минуя изначально предполагавшийся `qwen/qwen3.6-plus` — впоследствии подтверждено как правильный выбор коммитом `eb97124`: `qwen` слишком медленный/многословный для `EVAL_TIMEOUT`, а `gpt-5.4-mini` даёт чистый парсящийся JSON), иначе S4/Stage-3 не на чём проверять. Абзац для Test — pin `idx=1` (23 термина, максимум в seed).
- **T2. `ModelParams` + `_client_for`.** Новый pydantic `ModelParams` (в `webapp/` или `llm/`), парсится из `params_json`; поля `Optional=None`; валидатор по матрице **отбрасывает** неподдерживаемые поля (top_k у gemini, min_p у haiku/sonnet, temperature у Claude/gemini) и валидирует reasoning-юнион. Переписать [_client_for](../../../src/palimpsest/webapp/app.py) (app.py:202): строит `LLMConfig` из `ModelParams`; **env-fallback** — пустой `api_key` + OR base_url → `OPENROUTER_API_KEY` из env (сейчас возвращает `None`). `config.py::ModelConfig` не трогаем (это офлайн-YAML пайплайна, webapp его не использует).
- **T3. `LLMClient`.** Расширить [llm/client.py](../../../src/palimpsest/llm/client.py): `complete()` возвращает `LLMResult(content, usage)` (не `str`); шлёт только не-`None` поля; `top_k/min_p/reasoning/extra_body` — через `extra_body`; `usage.include` для стоимости. **Ретраи выключены** (совпадает с «без слепых ретраев» и cost-safety). Обновить вызовы (`judge.py`, /test). Anthropic SDK **не** тащим (всё OpenAI-compat).
- **T4. Бюджет-гард.** Новый модуль `budget.py`: in-process аккумулятор `spent_usd` (cap $2, env-override), `call_count` (cap 200), per-model прайс из матрицы. `estimate(model, prompt_tok, max_tok, reasoning_max_tok=None)` = worst-case; для Anthropic (reasoning **аддитивен**) = `prompt·in + (max_tok + reasoning_max_tok)·out`, у OpenAI reasoning уже внутри `max_tok` — Stage-0 юнит-ассерт на это. `check_budget(est)` перед **каждым** реальным вызовом в /test и /evaluate **атомарно резервирует** `spent += est` под `db._lock`/`asyncio.Lock` (иначе конкурентные корутины `/evaluate` через `asyncio.gather` прочитают устаревший `spent` и перепрыгнут потолок); при `spent+est > cap` или `count ≥ cap` — `BudgetExceeded`. После вызова: `spent` корректируется на `actual`, пишем JSONL-строку (модель, отправленные params, статус, токены вкл. reasoning, `costUsd`, latency). JSONL-логгер сериализует только `params`/`extra_body` (не заголовки/ключ), прогоняя через `_guard_params`.
- **T5. Эндпойнт /test** (контракт ниже).
- **T6. judge.py.** Убрать хардкод `client.complete(..., temperature=0)` (judge.py:54) — temperature решает `ModelParams`/`LLMClient` per-model; `judge_one` не передаёт override.
- **T7. Фронт.** В [SettingsTab.tsx](../../../frontend/src/demo/variant-a/SettingsTab.tsx): кнопка `Test` (`.va-btn-secondary`, в полёте `…`), статус `.va-verdict-dot`, строка результата `.va-insp-issue-card`; локальный стейт `{loading,expanded,result}` per-model. **Edit-форма** (сейчас `onClick={()=>{}}`): минимальная модалка — `baseUrl`, `apiKey` (write-only), `params` как **JSON-textarea** → `PUT /api/models/{name}`. `ParamsBagDisplay` уже делает `JSON.stringify(v)` (вложенные dict рендерит как JSON — ок).
- **T8. Doc-parity (тот же коммит).** Строку `POST /api/models/{name}/test` — в REST-таблицу [webapp.md](../../subsystems/webapp.md) и в контракт [2026-06-30-demo-contracts.md](2026-06-30-demo-contracts.md); подтвердить, что новых `va-*` классов нет (иначе — правка `webapp-ui-design.md` в том же коммите).

## Эндпойнт Test (контракт)

`POST /api/models/{name}/test` — admin-token gated (тратит реальные деньги, как прочие мутации `/api/models`).
- **Тело:** `{}` (опц. `{effort?: string}` override).
- **Коды:** `404` — неизвестное `{name}`; иначе всегда **`200`** с `{ok, ...}`. `no api key/env`, timeout (реюз `EVAL_TIMEOUT=20s`), API-исключение, ошибка парсинга JSON → `200 {ok:false, message:<причина>}` (зеркалит подход /evaluate: сбой → не 5xx). Перед вызовом — `check_budget`; превышение → `200 {ok:false, message:"budget"}`. Примечание: `EVAL_TIMEOUT` — advisory `asyncio.wait_for` таймаут на стороне хендлера; авторитетный потолок на вызов — `LLMClient`'s `timeout=30s` (client.py), который короче не бывает.
- **Реализация:** ОБЯЗАНА идти через `_client_for(conn,name)` + `LLMClient.complete()` (Invariant #6), без прямого `openai` в хендлере. Свежесть: `/test` строит клиент через `_client_for` (без кэша), Test-после-Edit сразу видит новый конфиг.
- **Ответ (happy):** `{ok, latencyMs, extracted[], reference[], matched, total, share, tokens:{prompt,completion,reasoning}, costUsd, message}`.

**Метрика (однозначно, воспроизводимо — morphology-tolerant, откалибровано на live e2e):**
1. Эталон `R`: строки `term` абзаца `idx=1`; каждая `source_surface` → `_norm` (lowercase + схлопывание пробелов, как [verdict.py](../../../src/palimpsest/terminology/verdict.py)); slash-термин (`марту/амурру`) split на элементы; порядок-сохраняющая дедупликация → **список** терминов (не множество). `total = |R|` может быть больше числа строк `term` (23) из-за slash-split → обычно 24.
2. Модель просят вернуть JSON-список терминов **в теле ответа** (толерантный парсинг, срезая ```-ограды — как `judge.py._parse_json`), **не** через `response_format` (чтобы работало на всех, включая haiku-роут). Seed-дефолты `params_json` для Test **опускают `reasoning`** на haiku/sonnet/gpt-5.4-mini/qwen (только у gemini effort обязателен на маршруте) — на этой лёгкой задаче извлечения reasoning не нужен, а на reasoning-моделях он усекал JSON-ответ и удваивал стоимость (см. комментарий в [model_matrix.py](../../../src/palimpsest/webapp/model_matrix.py)).
3. **Матч по стемам** (`app._stems`): каждое слово → префикс-4 (короткие слова целиком), так `династии`≡`династия`, `сутиев`≡`сутии` — эталон в источнике стоит в косвенном падеже, модель отвечает в именительном. Термин `r∈R` считается найденным, если ≥60% его стемов входят в объединение стемов извлечённого списка `M`. `matched` = число найденных терминов, `share = matched/total`. `ok = (нет ошибки/парсинга) AND share ≥ 0.5`. *(Прежний точный `R∩M` на `_norm` был несправедлив к русской морфологии — давал 0.29–0.33 у корректно работающих моделей; стем-матч даёт 0.67–0.83.)*

**UI:** зелёная/красная `.va-verdict-dot` у имени; строка `.va-insp-issue-card` — только статистика (OK/FAILED-бейдж + latency + доля + стоимость). Причину (`message`) показываем **только при FAILED**; на OK карточка чистая. Список извлечённых терминов в UI не рендерим (остаётся в ответе API).

## Edit → все оценщики

`_client_for` (app.py:202) читает строку `model` из БД **на каждый** `/evaluate` и `/test` — кэша устаревшего конфига нет (проверено ревью). Тест: правка `max_tokens`/`reasoning` → следующий `/evaluate` ссылающегося критерия шлёт новое (по логу). Удаление используемой модели → 409 (уже в бэке). `/test` vs конкурентный `PUT` — best-effort eventual (демо, один писатель под `db._lock`); отдельного гарда не добавляем.

## Выведено из скоупа (упрощение per «No speculative abstractions»)

- **`structured_output`/`response_format`/haiku-Vertex-pin** — ни `/evaluate` (парсит текст), ни `/test` (намеренно из текста) не шлют `response_format`. Поле было бы **мёртвой конфигурацией** с недостижимой веткой. Убираю из `ModelParams`; помечаю как отложенное (если позже оценщик захочет строгий json_schema — отдельная задача с реальным потребителем). Открытый вопрос про haiku-Vertex снят (нечем закрывать — мы не шлём `response_format`).
- **`provider`-дискриминатор как runtime-switch** — при OpenAI-compat-only (D2) он дублировал бы факт роутинга; оставляю только как **описательную метадату**, не ветку диспетчеризации.

## e2e с реальным API (стадии, enforcement, каденция)

Ключ — `worktrees/model-registry/.env` (`OPENROUTER_API_KEY`), лимит ключа **$3** (backstop), потолок прогона **$2** (T4, enforced pre-call). Все вызовы реальные, через систему.

- **Stage 0 — $0 (mock).** Unit/contract: формы запроса по матрице (S3), метрика (S2-порог), env-fallback (S5), budget-гард (S6, замоканный прайс), edit→оценщики (S4). Здесь же — проверка «`max_tokens` реально ограничивает reasoning+output per-provider» (OpenAI — совместно; Anthropic budget аддитивен) до траты денег.
- **Stage 1 — 1 вызов.** Smoke qwen3.6-plus: путь request→OR→parse→UI + подтверждение валидности ключа.
- **Stage 2 — ≤5 вызовов.** Test по разу на OR-модель; закрывает открытые вопросы (default effort, temperature-эффект, streaming, effort=none). Каждый вызов — под `check_budget`.
- **Stage 3 — браузерный e2e (`e2e-tester` + аудит).** Реальный путь: Test-кнопки + `/evaluate` с **явными `criterionIds` на 1 абзаце** (не веером по 16×5); массу держит cache-fallback. `/evaluate` тоже под `check_budget`.
- **vLLM (3)** — вне скоупа (сервер не поднят).

**Enforcement:** `check_budget` перед каждым вызовом (worst-case оценка + аккумулятор), а не пост-фактум; при $2 — стоп. **Каденция мониторинга** ([[feedback_e2e_monitoring_cadence]]): у **каждой** модели первые примеры проверяю внимательно (корректность + стоимость), затем ~раз в минуту, при долгой стабильности — реже. После каждой стадии — фактический счёт владельцу; за $2 без согласия не выхожу.

## Открытые вопросы (закрыть live probe, Stage 2)

1. Реальный default `effort` (sonnet: medium vs high) — берём то, что вернёт OR, логируем.
2. Влияет ли `temperature` на gemini/qwen (или обесценивается).
3. Стриминг gpt-5.4-mini / qwen3.6-plus.
4. `effort=none` у gpt-5.4-mini — реально ли выключает reasoning.

## Риски

- **Reasoning-токены** — биллятся как output; на OpenAI входят в `max_tokens`, на Anthropic (`reasoning.max_tokens`) **аддитивны** → оценка стоимости для Claude суммирует их отдельно (учтено в T4/Stage 0). Митигация: жёсткий `max_tokens`, отдельный лог reasoning-токенов, pre-call estimate, потолок.
- **Марджин $2↔$3** мал → `check_budget` обязан отклонять вызов, чей worst-case перепрыгнет $2, ещё **до** отправки.

## Решения (обновлены)

- **D1.** Ключ общий из `.env` (env-fallback в `_client_for`), не 5× вставка. + acceptance-check S5.
- **D2.** Расширяем демо `LLMConfig`/`LLMClient` + `_client_for`; новый `ModelParams` из `params_json`; **OpenAI-compat only**, без Anthropic SDK; ретраи выключены; `complete()`→`LLMResult(content,usage)`. `config.py` не трогаем.
- **D3.** `temperature` опускаем у всех Claude и gemini; хардкод в `judge.py` убираем.
- **D4.** Test — извлечение терминов, эталон = seed `term` (абзац idx=1), RU-источник, effort = дефолт провайдера (логируем), `ok = share ≥ 0.5 AND no error`.
- **D5.** wire-DTO не меняем; гибкость — в `ModelParams`/`_client_for`/`LLMClient`. `/test` — **новый** контракт (не изменение DTO), фиксируется в contracts-доке (T8).
- **D6.** `structured_output`/provider-dispatch — вне скоупа (нет потребителя).
- **D7.** Бюджет enforced pre-call ($2), + call-count cap; ключ $3 — backstop.

## Координация: NER-экстрактор (feat/terminology-extract)

Параллельный агент строит live NER-экстрактор; интеграция пересекает мои файлы **только по контракту** (он не правит `webapp/*`/`SettingsTab`/`client.py`, я не правлю `src/palimpsest/terminology/`). Ref: `docs/superpowers/specs/2026-07-01-terminology-extract-design.md §10` (в ветке `feat/terminology-extract`, кросс-ветка — не в этом ворктри).

**Моя сторона (строю):** `ner_config` singleton ↔ `NerConfig{modelName→registry, prompt, params, enabled?}`; `GET/PUT /api/ner-config` (на запись — `_guard_params`; дефолтный prompt — `import DEFAULT_NER_PROMPT`, не копирую). Кэш: `paragraph.extract_key TEXT` + `extracted_at TEXT`; `seed.py` (мой файл) зовёт **их** `extract_key(...)` и проставляет ключ каждому seed-абзацу. `POST /api/paragraphs/{id}/extract` (кэш-паттерн как `/evaluate`: ключ≠хранимого → их `extract_paragraph_terms(...)` → замена `term`-строк → запись key+at → `{cached:false,terms}`; иначе `{cached:true}`, 0 OR-вызовов) + опц. `POST /api/documents/{id}/reextract-stale`; **бюджет-гард = мой `budget.py` (T4)** + per-batch call-cap. UI: «Re-extract stale (N)» в Settings, ↻ в Inspector, stale-бейдж.

**Импортирую у них:** `extract_key(source,ner_config)→sha256` (стабильный, канонич. порядок params — **их** функция, не реимплементлю), `extract_paragraph_terms(source,target,ner_config,*,grounder,pairer,extractor=None)→list[Term]`, `DEFAULT_NER_PROMPT`.

**К заморозке (через владельца):** (1) сигнатура `extractor` — предлагаю callable `(system,user)→LLMResult(content,usage)` (= мой `LLMClient.complete`), чтобы считать стоимость; (2) `api_key_env=OPENROUTER_API_KEY` = пустой `api_key` строки + env-fallback (D1); (3) границы `NerConfig.params` vs params строки модели (инференс vs NER-специфика); (4) параметры per-batch cap. Общая инфра (`budget.py`, расширенный `LLMClient`, реестр, env-fallback) живёт в этой ветке — их endpoint её потребитель.

## Changelog: переработка по /verify-spec

| # | Severity | Находка | Что сделано |
|---|---|---|---|
| C1 | CRITICAL | целил в `config.py::ModelConfig` (webapp его не использует) | D2/T2: цель = `_client_for`+`LLMClient`+`ModelParams`; config.py не трогаем |
| C2 | CRITICAL | нет задачи засеять 8 моделей | T1: seed.py вставляет 8 строк |
| C3 | CRITICAL | потолок $2 без enforcement | T4: `budget.py`, pre-call `check_budget`, S6 |
| C4 | CRITICAL | `judge.py` хардкодит temperature=0 | T6: убрать override |
| H1 | HIGH | «взять production-клиент» расплывчато | D2/T3: что портируем (usage), что нет (async/retry); `LLMResult` |
| H2 | HIGH | нет порога `ok` | D4/S2: `ok = share ≥ 0.5 AND no error` |
| H3 | HIGH | /test недоспецифицирован | контракт: тело/коды/admin-gate/timeout/ошибки |
| H4 | HIGH | `complete()` теряет usage | T3: `LLMResult(content,usage)` |
| H5 | HIGH | `structured_output` — мёртвая конфигурация | D6: выведено из скоупа |
| H6 | HIGH | метрика ссылалась на несуществующий morph-key | D4: реальный `_norm` (verdict.py), phrase-level, slash-split |
| H7 | HIGH | /evaluate веером без потолка вызовов | T4 call-count cap + Stage 3 явные criterionIds |
| M | MEDIUM | env-fallback/doc-parity/richest-абзац/pre-flight/effort-default/race | T1/T2/T8, pin idx=1, ModelParams-валидация, effort=probe, best-effort race |

**Gate (ре-ревью v2, 4 аспекта):** прежние CRITICAL/HIGH подтверждены закрытыми. Новые находки применены: seed-критерии на матрицу (T1); аддитивный reasoning-бюджет в `estimate` + атомарный `check_budget` (T4); путь `verdict.py`; статус-оговорка «целевой дизайн». Находки «T1–T8 не реализованы в коде» отклонены как не-дефект спеки (реализация — шаг 5). **Гейт пройден.**
