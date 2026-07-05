# Спека S4 — Translator: первичный AI-перевод для загрузки «только оригинал»

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Владельческое требование: «Очень важно сделать первоначальный перевод. Возможность подгружать не пару, а только оригинал и перевести его "переводчиком", который задаётся выше оценщиков во вкладке Settings, аналогичным образом — промпт + выбор модели из model registry».
Связано: S3 (та же модалка), S1 (та же вкладка Settings), контракт-SSOT.

## 0. Grounding

- Translate-функциональности в webapp **нет вообще** (grep «translate» по `src/palimpsest/webapp/` пуст; в UploadModal `canNext` жёстко требует текст в обеих панелях).
- Переиспользуемое: `src/palimpsest/pipeline/draft.py` — `DraftStage` (system-промпт `prompts/01_draft_academic_en.md`, вызов `LLMClient.complete(system,user)`); `PipelineRunner` держит rolling-контекст предыдущих EN-абзацев. Пайплайн полностью отвязан от webapp (мертвый код исследовательской линии) — берём паттерн и промпт, НЕ импортируем пайплайн как есть.
- Паттерны для фоновой работы уже есть: precompute (первые 12 абзацев, статус в document DTO, бейдж в UI, budget-guard `reserve()/settle()`); `_client_for` (`app.py:378-392`) строит LLMClient из строки registry.
- Конфиг-паттерн: `grounding_config (id=1, model_name→model, prompt, params_json)` + `GET/PUT /api/grounding-config` + секция в Settings. Translator делаем зеркально.

## 1. Цель

Пользователь загружает только оригинал → жмёт `Create & translate` → документ создаётся, абзацы переводятся фоново выбранной моделью с настраиваемым промптом → появляются переводы, дальше стандартный цикл (evaluate → issues → apply-edit → re-evaluate). Всё под budget-guard.

## 2. Данные и контракт

### 2.1 Новая конфиг-таблица (DDL — дельта SSOT)
```sql
CREATE TABLE translator_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
```
Seed: `model_name` = `openai/gpt-5.4-mini` (первый живой judge-модели демо-набора), `prompt` = содержимое `prompts/01_draft_academic_en.md`, адаптированное: см. §6 (плейсхолдеры языков), `params_json` = `{"max_tokens": 2048, "temperature": 0.3}`.

**Миграция (CRITICAL из ревью — в проекте НЕТ механизма миграций):** DDL добавляется в ДВА места: (1) `db.py::SCHEMA` — безусловно (из него собираются все свежие dev/test/e2e БД через `init_db(reset=True)`); (2) общий идемпотентный `src/palimpsest/webapp/migrate.py` (владелец модуля — S5 §2.4, там же архитектура и тесты) — он создаёт `translator_config` через `CREATE TABLE IF NOT EXISTS` и сеет строку конфига, если её нет, на живой прод-БД без reseed.

### 2.2 REST (дельта SSOT)
- `GET /api/translator-config` → `{model_name, prompt, params}` (зеркало grounding-config).
- `PUT /api/translator-config` → то же; валидация params по whitelist S1 §2.4.
- `POST /api/documents` — тело получает опциональный флаг `translate: true`; при нём допускается пустой `target` (сейчас 422 в `app.py:292`). Валидация: translate=true ⇒ source_lang/target_lang заданы, все source непустые, и **ВСЕ target пустые** — смешанное тело → 422 `{"detail":"mixed_targets"}` (модалка всегда шлёт все-пустые; контракт это фиксирует явно). Создаёт paragraphs с `target=''`, `seed_target=''`, document.origin='upload'.
- **CRITICAL (ревью): `translate:true` принудительно отключает precompute на создании.** `CreateDocumentBody.precompute` дефолтится в `true` (`app.py:238`), а чекбокс живёт в пропускаемом Step 2 — буквальная реализация запустила бы платный judge-прогон по 12 ПУСТЫМ target-ам и навсегда записала бы мусорный baseline (`_already_scored` потом пропускает эти абзацы). Правило: сервер игнорирует precompute при translate=true (форс `false`), фронт дополнительно шлёт `precompute:false`; unit-тест: между созданием translate-документа и завершением перевода не появляется ни одной score-строки.
- `POST /api/documents/{doc_id}/translate` → 202 `{status:'started', total:N}`; 409 если уже идёт; budget-предпроверка (ревью: у reserve() нет «стартового» примитива): синхронно читаем снапшот бюджета (остаток $ и calls); если calls==0 или остаток < грубой оценки одного вызова → 409 `{"detail":"budget_exhausted"}` БЕЗ запуска задачи. Жёсткой гарантией остаётся пер-вызовный `reserve()` внутри цикла. Фоновая задача (asyncio.create_task, как precompute).
- Статус: в `GET /api/documents/{id}` DTO добавить блок `translation: {status: 'idle'|'running'|'done'|'failed', done: n, total: N, error_reason?: str}` (in-memory реестр процесса — паттерн precompute; после рестарта сервера running→idle, «продолжить» = повторный POST, уже переведённые абзацы (target≠'') пропускаются — идемпотентность).

### 2.3 Семантика записи
- Каждый переведённый абзац: `UPDATE paragraph SET target=?, seed_target=?` (seed_target = AI-первичник; Reset возвращает к нему) + запись ревизии `origin='translate'` (S5 §2.1, если S5 смержен первым; иначе — без ревизии, S5 добавит).
- Score-строки НЕ пишутся translate-ом (оценка — отдельный явный шаг; после завершения перевода фронт предлагает precompute — §3.3).

## 3. Backend-реализация

### 3.1 Модуль `src/palimpsest/webapp/translate.py` (новый, один res-модуль)
- `async def run_translation(doc_id)`: абзацы по порядку idx; rolling-контекст = последние 2 переведённых EN-абзаца (паттерн PipelineRunner, обрезка по символам ≤2000); на абзац: `budget.reserve()` → `LLMClient.complete(system=rendered_prompt, user=user_block)` → `settle()`; ретрай 1 раз с backoff на 429/5xx; фейл абзаца → пропуск (target остаётся ''), счётчик failed.
- user_block: `Source ({source_lang}):\n{source}\n\nContext — previous translation:\n{ctx}\n\nTranslate into {target_lang}. Output ONLY the translation.` Ответ trim, защита от префиксов «Translation:» (strip по regex).
- Статус-реестр `TRANSLATIONS: dict[int, TranslationState]` — как precompute; error_reason: `no_api_key` | `budget_exhausted` | `all_failed`.
- **Клиент и params (HIGH из ревью):** `_client_for` (`app.py:378-392`) строит конфиг ТОЛЬКО из params_json строки model-registry и не принимает override — существующий grounding-путь из-за этого молча игнорирует свои params (использует их только для оценки стоимости). Требование: расширить `_client_for(name, params_override: dict | None = None)`; translate передаёт `translator_config.params_json`. Unit-тест: эффективные temperature/max_tokens клиента переводчика взяты из translator_config, НЕ из строки registry. Бонус тем же механизмом (3 строки): передать override и в `_grounding_judge_live` — чинит no-op params у Settings › Grounding; отразить в known_issues.
- **Конкурентность (HIGH из ревью):** реестр `_translating: set[int]` (doc_id), зеркало `_evaluating`: (a) `evaluate` на абзаце документа из `_translating` → 409 `{"detail":"translation_in_progress"}`; (b) `reset_document` для такого документа → 409; (c) `delete_document_route` вызывает `translate.cancel(doc_id)` (флаг, как `precompute.cancel`) и ждёт выхода цикла; (d) `run_translation` перед КАЖДОЙ записью перепроверяет `_document_exists` (паттерн `precompute._run`).

### 3.2 Модалка (frontend, поверх S3)
- Translation-панель пустая и Source непустой → в футере Translation-панели появляется CTA-блок: иконка ✦ + `No translation? Translate with AI` (кнопка `va-btn-secondary` с accent-текстом) — переключает панель в режим **AI translate**: textarea заменяется на плейсхолдер-карточку `Will be translated by {model_name} after upload` (модель из translator-config, моно), кнопка становится `↩ Paste translation instead` (возврат).
- В режиме AI translate: `nextBlockReason()` → null при валидном Source; Step 2 (alignment) пропускается ЦЕЛИКОМ (align не с чем) — кнопка Next → `Create & translate`; сабмит: `POST /api/documents {translate:true}` → `POST …/translate` → модалка закрывается, документ открыт.
- UI-копирайт (EN, инвариант 9): `No translation? Translate with AI`, `Will be translated by {model} after upload`, `Paste translation instead`, `Create & translate`.

### 3.3 Прогресс в Document-табе
- Пока `translation.status==='running'`: бейдж в топ-баре документа (паттерн precompute-бейджа): `Translating {done}/{total}…` с тонким прогресс-баром; абзацы без target рендерятся плейсхолдером `…` (dim, курсив). Store поллит документ каждые 3s (ровно как существующий precompute-поллинг `VariantA.tsx:132`, setInterval 3000; очистка по done/failed).
- **Новый UI-паттерн (ревью):** детерминированного прогресс-бара в дизайн-системе НЕТ (есть только шиммер `va-score-bar-shimmer`) — вводим `.va-progress-bar`/`.va-progress-fill` (высота 3px, fill = `--va-accent`, ширина inline-стилем из done/total) и в ТОМ ЖЕ коммите дополняем таблицу компонентов `docs/subsystems/webapp-ui-design.md` (extension rule).
- `done` → бейдж `Translated {total}¶` (зелёный, исчезает через 5s) + предложение precompute: маленькая строка под бейджем `Evaluate first paragraphs?` [Run] — клик = существующий precompute-путь. `failed` → красный бейдж с error_reason и кнопкой `Retry` (повторный POST translate).

### 3.4 Settings-секция Translator (S1-вкладка, выше Evaluators)
- Заголовок `Translator`, под ним карточка: `Model` (select из registry, как у evaluator), `Params` (JSON-textarea + effective-preview, реюз S1 §2.4 компонента), `Prompt` (Edit/Preview toggle — реюз компонента S1 §2.3), `Save`. Один конфиг, без add/remove.
- Изменение конфига действует на СЛЕДУЮЩИЙ запуск перевода (идущий не трогаем) — подпись мелким: `Applies to the next translation run`.

## 4. Тесты
- Pytest: POST documents translate:true с пустыми target (создание ок; без флага — прежняя 422; смешанные target → 422 mixed_targets; precompute форсится в false — ни одной score-строки до завершения перевода); translate endpoint: happy (fake LLMClient), идемпотентный ре-POST переводит только пустые, budget_exhausted 409 (предпроверка), no_api_key → failed+reason; rolling-контекст собирается верно; params-override: клиент получает temperature/max_tokens из translator_config; конкурентность: evaluate → 409 translation_in_progress, reset → 409, delete отменяет цикл; GET/PUT translator-config + валидация params; строгий запрет translate для origin='seed' документа (403 — сид не перезаписываем).
- Vitest: режим AI translate в модалке (переключение, blockReason, сабмит-цепочка моками); прогресс-бейдж по статусам.
- E2E: полный сценарий — см. общий пайплайн-сценарий в плане verify (upload source-only .txt → Create & translate → дождаться перевода (живой ключ, короткий 3-абзацный текст) → evaluate ¶1 → apply-edit → re-evaluate → export S6).

## 5. Дизайн-мокап
Единый мокап-файл `2026-07-05-settings-upload-mockup.html` (готовит исполнитель ДО кода, Sonnet, по образцу glossary-мокапа: те же токены): экран A — Settings с секцией Translator над Evaluators + editable prompt открыт; экран B — модалка в режиме AI translate; экран C — Document-таб с бейджем Translating 3/12. Владелец смотрит мокап в Artifact.

## 6. Промпт по умолчанию (seed)
За основу — `prompts/01_draft_academic_en.md` (академический EN-черновик), генерализовать: явные `{source_lang}`/`{target_lang}` плейсхолдеры (рендер бэком при вызове), тон — «faithful, fluent, terminology-consistent», запрет добавлений/пояснений, вывод только перевода. Файл нового промпта: `prompts/translator/default.md`; seed читает его.

## 7. Риски / решения
- Стоимость: 12-абзацный документ ≈ 12 вызовов gpt-5.4-mini ≈ $0.02-0.05 — в бюджете. Живой e2e — на 3-абзацном тексте.
- Долгий документ (40¶): фон, поллинг, идемпотентный retry — приемлемо для демо; очередь/воркеры не строим (no speculative abstractions).
- Владелец сказал «переводчик задаётся аналогично оценщикам»: сознательное решение — НЕ строка в таблице evaluators, а отдельная секция-карточка (переводчик один, семантика другая); зеркалит grounding-config, уже знакомый паттерн проекта.
