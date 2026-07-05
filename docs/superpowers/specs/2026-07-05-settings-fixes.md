# Спека S1 — Settings: чистка, редактируемые промпты, нормальные params, честные ошибки

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x` → PR в `dev-demo`.
Контекст: подготовка демо к записи 2-минутного видео для industrial track EMLP 2026.
Связано: [2026-07-02-settings-rework.md](2026-07-02-settings-rework.md) (частично отменяется — см. §1), контракт-SSOT [2026-06-30-demo-contracts.md](2026-06-30-demo-contracts.md).

## 0. Grounding (что уже есть в коде — проверено разведкой)

- Admin-token gate **отсутствует в коде** `dev-demo` полностью: ни в одном route `app.py`, ни в `SettingsTab.tsx` (grep по `admin|token|Authorization` — пусто, кроме комментария в `budget.py:9`). Баннер «Settings are read-only. Unlock with admin token» на скриншоте владельца — это **старый билд на сервере**, собранный по спеке 2026-07-02-settings-rework §admin-unlock. Актуальный код уже без него.
- Cultural Adaptation **уже удалён** из seed (`seed.py:29-34`: 4 критерия — accuracy 0.30, fluency 0.20, style 0.15, terminology 0.20; комментарий «minus Cultural Adaptation — dropped wave-4 Б4»). Файл `prompts/scoring/cultural.md` осиротел. На проде критерий остался в **БД старого билда**.
- Промпт оценщика: колонка `criterion.prompt` (`db.py:35`), `PUT /api/criteria/{cid}` уже принимает `prompt` (`app.py:733-743`). Но UI `EvaluatorEditor` (`SettingsTab.tsx:452-457`) рендерит его как «Prompt (read-only preview)» через ReactMarkdown — textarea есть только в AddEvaluatorModal.
- Params моделей: свободный JSON `model.params_json` (`{"max_tokens":2048,"reasoning":{"effort":"low"}}`, qwen — `top_k`/`min_p`). `ModelParams.for_model()` (`model_params.py:29-58`) **молча** отбрасывает неподдерживаемые ключи и силой вставляет `seed=7`; UI-бейдж «N params» (`SettingsTab.tsx:267`) считает сырой JSON, а не эффективные параметры. Валидация backend — только «это dict» + «нет секретных ключей».
- Remove модели: `handleRemoveModel` (`SettingsTab.tsx:123-130`) — **пустой catch**, 409 (модель привязана к критерию) исчезает беззвучно. Путь Remove у критерия (`SettingsTab.tsx:201-210`) показывает `fieldError` — образец.
- Всплывающие баннеры: глобального баннера в коде нет; есть локальные `va-precompute-failed-notice` (BUG-5: precompute завершился с `succeeded===0`) и `va-inspector-warning`. Причина на проде — старый билд + отсутствие ключа/бюджета.

## 1. Цель и скоуп

Вкладка Settings в состоянии «можно показывать на видео»: без админ-гейта, без Cultural Adaptation, промпт каждого оценщика редактируется на месте, params моделей читаемы и валидируются, каждая кнопка либо работает, либо честно объясняет отказ. Причины «висячих табличек» устранены в корне.

**Отмена куска старой спеки:** admin-unlock из 2026-07-02-settings-rework.md §перми снят решением владельца (скрин 1). Спека 07-02 в этой части считается superseded; в файл 07-02 добавить баннер `⚠️ SUPERSEDED §admin by 2026-07-05-settings-fixes.md`.

## 2. Изменения

### 2.1 Admin-токен — не возвращать
- Код чист; работа = деплой актуального билда (deploy-скрипт, спека прилагается к PR) + этот пункт в e2e-чеклист: «на Settings нет замка/поля токена».
- В `docs/subsystems/webapp.md` убрать/пометить legacy любые упоминания admin-token.

### 2.2 Cultural Adaptation — добить хвосты
- Удалить осиротевший `prompts/scoring/cultural.md`.
- Прод-БД: **не** `DELETE` (инвариант «никогда не удалять LLM-предсказания» — у критерия есть score-строки). Деплой-чеклист (`deploy/`, см. S5 §2.4 про migrate.py) выполняет `UPDATE criterion SET enabled=0 WHERE id='cultural'`. Подтверждено ревью: и `app.py`, и `aggregate.py` УЖЕ фильтруют enabled=0 — код менять не нужно, только данные прода.
- Тест `tests/test_suggestion_guard.py`, ссылающийся на cultural, переключить на живой критерий.

### 2.3 Редактируемый промпт оценщика (главная фича S1)
UI (`EvaluatorEditor`):
- Заменить «Prompt (read-only preview)» на переключатель **Edit / Preview** (два маленьких таб-чипа справа от лейбла `Prompt`):
  - Preview (default) — текущий ReactMarkdown-рендер.
  - Edit — `<textarea class="va-field-input va-prompt-textarea">`, моноширинный, min-height 220px, автогроу до 480px.
- Под textarea — строка действий: `Save prompt` (primary, disabled пока нет изменений) + `Revert` (сброс к сохранённому) + счётчик символов.
- Save → существующий `PUT /api/criteria/{cid}` c полным телом критерия (prompt + прочие поля без изменений). Ошибка → `fieldError` в том же паттерне, что у критерия-Remove. Успех → toast-подтверждение не нужен, достаточно исчезнувшей кнопки (стала disabled) + Preview с новым текстом.
- UI-копирайт (EN): `Prompt`, `Edit`, `Preview`, `Save prompt`, `Revert`, `Unsaved changes`.
Backend: изменений не требуется (PUT уже пишет prompt). Добавить unit-тест: PUT сохраняет prompt, GET возвращает.

### 2.4 Params моделей — читаемо и валидно
Backend:
- `_require_params_object` расширить: whitelist ключей `max_tokens:int 1..32768`, `temperature:float 0..2`, `top_p:float 0..1`, `top_k:int`, `min_p:float`, `seed:int`, `enable_thinking:bool`, `reasoning:{effort: low|medium|high}`. (`enable_thinking` — легитимный ключ `ModelParams` (`model_params.py:27,68-69`), сеется у vLLM-строки `Qwen/Qwen3.6-27B` в полном 8-строчном наборе — без него no-op Save этой модели давал бы 422.) Неизвестный ключ → 422 `{"detail":"unknown param: <key>"}` (больше не сохраняем мусор, который потом молча выкидывается).
- В ответ `GET /api/models` добавить поле `effective_params` — результат `ModelParams.for_model()` для строки (то, что реально уйдёт в вызов). Контракт-SSOT дополнить.
Frontend (`SettingsTab`):
- Вместо бейджа «`N params`» — инлайн-текст моноширинным: `max_tokens 1536 · temp 0.6 · top_k 20` (первые 3, остальное «+N»). Клик — раскрытие как сейчас.
- В Edit-модалке params остаются JSON-textarea (это админский инструмент), но: (a) под полем — live-валидация с сообщением 422 от бэка; (b) блок `Effective params` (read-only, серым): что реально пойдёт в API после фильтра capability, с пометкой `seed 7 · forced for reproducibility`, если модель supports_seed.
Seed-матрица (`model_matrix.py`, demo-набор из 5 OpenRouter-строк):
- Факт (ревью): в demo-наборе экзотики нет — `qwen/qwen3.6-plus` несёт `{"max_tokens":1536,"temperature":0.7}`; `top_k/min_p` живут только на двух vLLM-строках полного набора (в прод-seed с `PALIMPSEST_SEED_DEMO=1` не попадают). Дельта: всем 5 demo-строкам выставить `temperature: 0` (детерминизм судьи), `max_tokens` не трогать; vLLM-строки не трогать (их params легальны при whitelist §2.4). Обновить спеку model-registry ссылкой.
- Деплой-скрипт обновляет params существующих строк на проде через `PUT /api/models/*` (не reseed).

### 2.5 Кнопки — работают или честно падают
- `handleRemoveModel`: catch → `fieldError` с текстом бэка (409 → `Model is used by evaluator "X" — reassign it first`; кавычки прямые, не «» — инвариант 9, в EN-UI гильеметов нет). Паттерн — как у критерия.
- `Test` у модели: оставить (работает, реальный probe); добавить видимый спиннер-состояние `Testing…` и результат в строке (match-share % / err), не только в консоль. Проверить текущий рендер результата; если уже есть — довести до e2e-чека.
- API key нельзя очистить (known_issues #9). Точный механизм бага (ревью): wire-поле — camelCase `apiKey`; `update_model` (`app.py:804`) делает falsy-check `m["apiKey"] if m.get("apiKey") else row["api_key"]`, т.е. пустая строка неотличима от отсутствия поля. Фикс: presence-check — `"apiKey" in m and m["apiKey"] == ""` ⇒ очистить; `"apiKey" not in m` ⇒ оставить прежний. UI: кнопка `Clear key` шлёт `PUT {apiKey: ""}`. Unit-тест на обе ветки.
- `+ Add evaluator` / `+ Add model` — прогнать e2e, починить найденное (разведка не нашла поломок в коде — вероятно, прод-эффект).

### 2.6 Причины «висячих табличек»
- `va-precompute-failed-notice`: расширить `precompute`-статус бэка полем `error_reason` (`no_api_key` | `budget_exhausted` | `all_failed`) и показывать человеческий текст: `Precompute skipped: no API key configured` / `…: budget cap reached`. Это убирает «что-то сломалось» без объяснений.
- Inspector-warning при evaluate: оставить (это честная ошибка), но убедиться, что Retry failed работает при живом ключе.

## 3. Контракт (дельта SSOT)
- `GET /api/models` → `+ effective_params: object` на строку.
- `POST/PUT /api/models` → 422 на неизвестный ключ params; `api_key:""` очищает ключ.
- `GET /api/documents/{id}` precompute-статус → `+ error_reason?: string`.
- Прочее без изменений. Обновить 2026-06-30-demo-contracts.md в том же коммите (doc-parity).

## 4. Тесты
- Unit (pytest): PUT criteria/prompt; 422 unknown param; api_key clear; effective_params в GET models; enabled=0 исключает критерий из evaluate.
- Vitest: EvaluatorEditor edit/save/revert; params-инлайн рендер; remove-model error surface.
- E2E (шаг 6/8): Settings-сценарий — открыть каждый оценщик, изменить промпт, сохранить, перезагрузить страницу, промпт на месте; Edit/Test/Remove модели; добавить+удалить временный оценщик и модель; скриншоты.

## 5. Риски / открытое
- ~~enabled=0 фильтрация~~ — снято: ревью подтвердило, что фильтрация уже есть в app.py и aggregate.py.
- Владелец на скрине видит 5-й evaluator (Cultural) из старой прод-БД: закрывается деплой-чеклистом (§2.2), НЕ кодом.
