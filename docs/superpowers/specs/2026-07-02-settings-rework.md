# Спека: переработка страницы Settings (оценщики + реестр моделей) — rev-2

⚠️ **LEGACY (admin-gate removed in wave-4).** Владелец отменил admin-токен: Settings полностью открыты всем, без разлочки. Весь admin/unlock-контент этой спеки — история решения, не текущее поведение. См. [2026-07-03-wave-4.md, блок Б5](2026-07-03-wave-4.md).

Дата: 2026-07-02. Ветка: `feat/settings-rework`. Статус: **согласовано владельцем по мокапу; rev-2 после /verify-spec (5 аспектов: 2 CRITICAL, 4 HIGH закрыты правками текста)**.

**Цель одним предложением (Done when):** вкладка Settings полностью работоспособна на проде — разлочка админ-токеном, добавление/правка оценщиков и моделей из UI без единого молчаливого фейла, реестр демо очищен от мёртвых vLLM-строк.

## Проблема (диагноз по коду и проду)

1. **Мутации не работают на проде.** Фронтенд не шлёт `Authorization` вообще ([api-client.ts:250](../../frontend/src/demo/api-client.ts#L250) — только `Content-Type`), а на gse-translation.ru включён `DEMO_ADMIN_TOKEN` → каждый гейтованный POST/PUT/DELETE получает 401. Ошибки молча проглатываются: `void handleAddEvaluator()` (SettingsTab.tsx:209), `onRemoveModel(m.name)` без await/catch (SettingsTab.tsx:256), `void onUpdateCriterion(...)` в чекбоксе enabled (SettingsTab.tsx:175).
2. **UX добавления — заглушки.** «+ Add model» — `window.prompt()`; «+ Add evaluator» мгновенно создаёт фантомную строку через API.
3. **«Странные параметры».** Реестр засеян матрицей пилота ([model_matrix.py](../../src/palimpsest/webapp/model_matrix.py)): 3 vLLM-модели на `localhost:8001` (мертвы в контейнере) с параметрами под term-extraction, не под судейство.

**Фактический список admin-гейтованных рутов** (8, сверено grep'ом `_require_admin`): `POST /api/budget/reset`, `POST|PUT|DELETE /api/criteria*`, `POST|PUT|DELETE /api/models*`, `POST /api/models/{name}/test`. **Осознанное решение:** `DELETE /api/documents/{id}` (upload-delete) и `POST /api/documents/{id}/reset` (document-reset) остаются публичными — загрузки одноразовые (known_issues), reset — часть демо-путешествия. Bearer шлётся ТОЛЬКО на 8 гейтованных рутов.

## Решение

### 1. Admin unlock

- Контракт `GET /api/admin/check` (новый, с конкретным потребителем — разлочкой):
  - `DEMO_ADMIN_TOKEN` не задан → **`200 {"required": false}`** всегда (заголовок не проверяется). Фронт: dev-режим, строка разлочки не показывается, всё открыто.
  - Токен задан, валидный `Authorization: Bearer <token>` → **`200 {"required": true, "ok": true}`**.
  - Токен задан, заголовок отсутствует/неверный (включая пустой `Bearer `) → **`401 {"detail": "admin token required"}`**.
- В шапке Settings — строка: 🔒 `Settings are read-only. Unlock with admin token` + password-инпут + `Unlock`. По Unlock — `GET /api/admin/check` с введённым токеном: 200 → sessionStorage, бейдж 🔓 `Admin mode` + кнопка `Lock`; 401 → инлайн `Invalid token`.
- **Lock**: чистит sessionStorage, возвращает locked-состояние; открытые модалки закрываются.
- **401 посреди сессии** (ротация токена, рестарт): любой гейтованный вызов с 401 при наличии токена в sessionStorage → токен чистится, UI флипается в locked, инлайн `Session expired — unlock again`. Бейдж — оптимистичный кеш; единственный авторитет — пер-вызовный `_require_admin`.
- Токен: sessionStorage (умирает с вкладкой; XSS-поверхности нет — без rehype-raw/dangerouslySetInnerHTML; если появятся — пересмотреть). Токен - `openssl rand -hex 16` (128 бит) → rate-limit на check осознанно не делаем.
- Locked-режим гейтует ВСЕ мутирующие контролы: кнопки Add/Edit/Remove/Test **и чекбокс enabled** (disabled + тултип `Unlock with admin token to edit`, CSS `:hover` и `:focus-visible`[^focus-within]). Просмотр критериев и промптов остаётся открытым (витрина методологии).
- Бэкенд-мелочь: `_require_admin` переходит на `hmac.compare_digest` (LOW-хардненинг, поведение то же).

### 2. Add Evaluator — модалка вместо фантомной строки

Поля: Name, Model (select из реестра), Weight (0–1), Prompt (textarea, markdown), Color (auto из палитры, редактируемый). POST по Save; создаётся `enabled=false`.
- **Промпт задаётся один раз при создании.** У существующих критериев промпт остаётся read-only превью (инвариант «не редактируем промпты» относится к существующим; модалка создания — единственная точка ввода). Существующий инлайн-редактор (имя/цвет/модель/вес через раскрытие строки) **остаётся как есть**.
- Валидация веса: без молчаливого clamp — инлайн `Weight must be between 0 and 1` при выходе за границы, Save блокируется; сервер (`Field(ge=0, le=1)`, 422) остаётся вторым эшелоном и тоже показывается инлайн. Кросс-критериальной валидации суммы весов НЕ существует и не вводится.

### 3. Add Model — модалка вместо window.prompt

Поля: Name, Base URL (пресет `https://openrouter.ai/api/v1`), API key (password, опционально), Params (JSON textarea, плейсхолдер `{"max_tokens": 1536}`). Невалидный JSON → инлайн ошибка. Серверные ошибки → инлайн в модалке.

### 4. Курация реестра для демо

- **Прод, этой веткой: точечное удаление, БЕЗ полного ресида.** `seed()` делает `init_db(reset=True)` — сносит весь файл БД (документы, загрузки, историю, ключи в строках). Поэтому на проде выполняется ТОЛЬКО `DELETE FROM model WHERE base_url LIKE 'http://localhost%'` (3 vLLM-строки). FK-безопасность: сид-критерии ссылаются только на `openai/gpt-5.4-mini`; перед DELETE — проверка `SELECT COUNT(*) FROM criterion WHERE model_name IN (…)` = 0, иначе остановка. **Supersession (2026-07-03):** деплой [seed-refresh](2026-07-02-seed-refresh.md) — единственное разрешённое исключение (данные меняются целиком: 15 абзацев, реальные baseline'ы и термины); он же закрывает курацию vLLM-строк через `PALIMPSEST_SEED_DEMO=1`. После него точечная политика возвращается.
- **Сид для будущих ресидов:** env-флаг `PALIMPSEST_SEED_DEMO=1` (конвенция `PALIMPSEST_*`), при установке vLLM-строки (`is_openrouter=False`) не сеются. По умолчанию (не задан) — текущее поведение, все 8 строк: локальные тесты и e2e-доки с `count(*)=8` не ломаются. pytest на ОБЕ ветки: demo=1 → 5 строк + FK критериев резолвится; без флага → 8 строк.
- Отображение params в таблице — бейдж `N params`, разворот по клику: каждый бейдж независим, можно раскрыть несколько, состояние не переживает refetch списка.

### 5. Ошибки мутаций — видимые

Единый инлайн-паттерн (стиль `va-inspector-warning`) под секцией + в модалках. Убираются ВСЕ молчаливые вызовы: `handleAddEvaluator`, `onRemoveModel`, чекбокс `enabled`. Формулировки ошибок — канонические английские, единые для обеих модалок.

### 6. Ops rollout / rollback

1. Ветка мержится в dev-demo после verify-pr → `npm run build` → `docker build -t gse-demo .` на сервере (rsync бандла как в первом деплое) → `docker rm -f gse-demo` → `docker run` с теми же аргументами (volume `/opt/gse-demo/data:/data`, `--env-file /opt/gse-demo/env` — env не меняется, `DEMO_ADMIN_TOKEN` и `OPENROUTER_API_KEY` уже там).
2. Точечный DELETE vLLM-строк (см. §4) через `docker exec … python` с pre-check.
3. Rollback: предыдущий образ (`docker run` со старым image id); DELETE обратим ручным INSERT из матрицы, БД не бэкапим (сид-данные восстановимы, загрузки и так одноразовые) — но перед DELETE снимаем копию `cp /opt/gse-demo/data/demo.db …/demo.db.bak` (дёшево).

## Test-ids (для vitest/e2e)

`unlock-row`, `unlock-token-input`, `unlock-btn`, `unlock-error`, `admin-badge`, `relock-btn`, `add-evaluator-btn`, `add-evaluator-modal`, `add-evaluator-error`, `add-model-btn`, `add-model-modal`, `add-model-error`, `params-badge-{modelName}`, `params-expanded-{modelName}`.

## Не делаем (YAGNI)

- Аккаунты/роли/сессии — только Bearer-токен.
- Редактирование промптов СУЩЕСТВУЮЩИХ критериев (превью read-only); промпт нового — только при создании.
- Rate-limit на /api/admin/check (энтропия 128 бит), кросс-критериальная валидация весов, изменение логики судейства/бюджета.
- Полный ресид прода (запрещён этой спекой — см. §4).

## Критерии успеха (каждый с исполняемой проверкой)

1. **Прод с токеном:** добавить оценщик и модель из UI, Test работает, ошибки видимы. Проверка: e2e-сценарий на проде/стейдже + vitest модалок.
2. **Без токена:** всё видно, мутации недоступны, ни одного молчаливого фейла. Проверка: vitest — в locked-режиме все мутирующие контролы disabled и **ни один fetch не отправляется**; 401-путь показывает инлайн-ошибку.
3. **Реестр прода — 5 живых OpenRouter-моделей.** Проверка: `GET /api/models` на проде после DELETE; pytest сид-веток (5/8).
4. **UI — English-only.** Тесты: vitest unlock-флоу (unlock/invalid/lock/session-expired), обе модалки, чекбокс-гейтинг; pytest `GET /api/admin/check` (3 состояния контракта), `PALIMPSEST_SEED_DEMO` обе ветки, `hmac.compare_digest` регрессия.

## Зафиксированные follow-up (вне скоупа, кандидаты в known_issues)

- `test_model` route возвращает сырое `f"{type(e).__name__}: {e}"` без `redact_error()` — существующий LOW-долг.
- Путь судьи не использует env-fallback ключа при пустой строке в БД (шлёт пустой Bearer) — неактуально при заполненных строках, но грабля.

[^focus-within]: Реализация вешает `:focus-within` на обёртку `.va-disabled-tt`, а не `:focus-visible` на сам контрол — потому что обёрнутый `input`/`button` в locked-режиме `disabled`, а disabled-элемент по спеке DOM физически не может получить фокус, так что `:focus-visible` на нём никогда не сработает. Но `:focus-within` смотрит на фокусируемых потомков той же обёртки, а внутри неё нет других потомков (сам disabled-контрол — единственный child) — значит для этих конкретных disabled-контролов тултип по факту раскрывается только через `:hover`, клавиатурного пути нет. Известное ограничение, не закрыто в этой ветке. См. [variant-a.css:1483-1484](../../../frontend/src/demo/variant-a/variant-a.css#L1483-L1484), [SettingsTab.tsx:261](../../../frontend/src/demo/variant-a/SettingsTab.tsx#L261).
