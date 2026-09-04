# Изоляция сессий для параллельных рецензентов (2026-07-16, v2 после verify-spec)

## Цель

Каждый браузер, открывший glossa-mt.com, работает со **своей копией** демо-данных:
документы, оценки, issues, ревизии, глоссарий и настройки одной сессии не видны
другой и не влияют на неё. Рецензенты EMNLP тестируют демо параллельно, не мешая
друг другу и не затрагивая канонический контент владельца.

Решение владельца (2026-07-16): «эфемерный клон на сессию» — правки рецензента
живут в его сессии и не сохраняются навсегда; для демо это плюс.

v2: переработано по итогам verify-spec (2 ревьюера: concurrency и data-lifecycle).
Ключевые добавления: golden-token обход для канонических обновлений, перенос
пина температуры в migrate, полный список рекеинга in-memory состояния,
двойная блокировка клонирования, тест-совместимость.

## Не-цели

- Аккаунты/логины — нет. Слияние сессионных правок в канон — нет.
- Сохранение сессий между рестартами — нет (рестарт = свежий стенд для всех).
- Изменение фронтенда — не требуется (cookie same-origin, автоматом).

## Дизайн

### Слой данных: golden-шаблон + файловые клоны

- `/data/demo.db` — **golden**: канонический шаблон. В рантайме мутирует ТОЛЬКО
  (а) стартовыми процедурами (migrate/курация/sweep/seed) до начала
  обслуживания, (б) явными запросами владельца с golden-токеном (ниже).
- `/data/sessions/<sid>.db` — клон на сессию, лениво, `sqlite3` backup API
  (golden 2.4 MB — мгновенно). SESSIONS_DIR: env `PALIMPSEST_SESSIONS_DIR`,
  дефолт `<dirname(DB_PATH)>/sessions`.
- **Wipe при старте**: lifespan удаляет `/data/sessions/*` целиком (глоб по
  `<sid>.db*` — включая возможные `-wal`/`-shm`).
- **TTL-уборка**: asyncio-задача каждые 15 мин: сессии, неактивные > 4 ч —
  close + unlink + вычистка ключей этого sid из ВСЕХ модульных структур
  (полный список ниже). Сессия с живой фоновой задачей (её sid встречается в
  `translate._tasks`/`_translating`, `terminology_live._tasks`,
  `precompute._tasks`) уборке не подлежит независимо от `last_used`.

### Маршрутизация: cookie → contextvar → db.connect()

- ASGI-middleware на `/api/*`: cookie `glossa_sid` (UUID; нет/невалиден →
  uuid4 + `Set-Cookie: HttpOnly; SameSite=Lax; Secure; Max-Age=14400`),
  sid кладётся в `contextvars.ContextVar` ДО вызова хендлера.
- **Golden-токен (канонические обновления владельца)**: если запрос несёт
  заголовок `X-Golden-Session` и его значение в constant-time равно env
  `DEMO_ADMIN_TOKEN` — sid привязывается к специальному `"__golden__"`, чьё
  соединение = golden DB (без Set-Cookie). Env не задан → фича выключена
  (заголовок игнорируется). Это сохраняет рабочим
  `scripts/create_demo_docs.py` (единственный путь владельца добавлять
  канонические документы через полный API+LLM пайплайн): скрипт получает
  флаг `--golden-token` (или env `GLOSSA_GOLDEN_TOKEN`) и шлёт заголовок во
  ВСЕХ своих запросах (create + poll).
- `db.connect()` (37 call-sites — не меняются) резолвит по contextvar:
  - startup-фаза (до `set_startup_done()`) → golden (migrate/seed как сегодня);
  - sid `"__golden__"` → golden;
  - обычный sid → кэш `{sid: SessionConn(conn, lock, last_used)}`, на промахе
    клон+открытие;
  - **нет sid после старта → RuntimeError** (fail-loud вместо тихой записи
    в golden);
  - **тест-совместимость**: если legacy `db._conn is not None` (17 тестовых
    файлов monkeypatch-ат `db.DB_PATH`/`db._conn`) → вернуть его как сегодня
    (единая «сессия» на тест). Существующие фикстуры работают без правок.
- **Клонирование под двойной блокировкой** (sync-эндпоинты бегут в реальных
  тредах anyio-пула — гонка первого захода реальна): глобальный
  `_sessions_guard: threading.Lock` защищает кэш; последовательность:
  guard → повторная проверка кэша → клон (backup API) → открытие → вставка →
  release. Клон 2.4 MB — держать guard на время клона допустимо (мс).
- `db.current_lock()` — акцессор per-session блокировки (заменяет глобальный
  `db._lock`): **27 call-sites** `with db._lock:` переписываются на
  `with db.current_lock():` в том же коммите — app.py (~20), terminology_live
  (5), translate (1), precompute (1). В legacy-режиме (`_conn` подменён
  тестом) current_lock() возвращает прежний глобальный лок. `current_lock()`
  и `connect()` бампают `last_used`.

### Распространение контекста (verify-spec: подтверждено кодом)

`asyncio.create_task` (translate.py:80, terminology_live.py:188) и
`asyncio.to_thread` копируют contextvars; синхронные эндпоинты бегут в
anyio-пуле с переносом контекста. Ключевое свойство кода: фоновые пайплайны
захватывают `conn = db.connect()` ОДИН раз на старте задачи и протаскивают
его явно (translate.py:144, precompute.py:141, terminology_live.py:327 →
`_grounding_judge_live` никогда не вызывает db.connect() внутри) — дыры
«sid потерялся в чужом треде» нет по построению. Обратная сторона: во время
долгой задачи `last_used` не бампается запросами этой задачи — поэтому TTL
дополнительно (а) бампается из per-параграфных write-хелперов фоновых задач,
(б) свипер пропускает сессии с живыми задачами (см. выше). Замечание
ревьюера: защита от уборки под живой задачей — таймаут-маржа + пропуск по
задачам, а НЕ структурная гарантия лока; зафиксировано здесь честно.

### Модульное in-memory состояние → ключ (sid, doc_id) — ПОЛНЫЙ список

doc id одинаковы во всех клонах (общий шаблон + одинаковый autoincrement),
коллизии между сессиями — норма, не край. Рекеинг обязателен для всех семи:

| Структура | Сегодня | Риск без рекеинга |
|---|---|---|
| `translate._status` (translate.py:27) | dict[int, dict] | чужой прогресс перевода в UI |
| `translate._translating` (:35) | set[int] | ложный «перевод уже идёт» |
| `translate._tasks` (:31) | dict[int, Task] | **A отменяет живой перевод B** (delete→cancel) |
| `precompute._status` (precompute.py:22) | dict[int, dict] | чужие warming-числа в UI |
| `precompute._tasks` | dict[int, Task] | как у translate._tasks |
| `terminology_live._tasks` (:136) | dict[int, Task] | как выше |
| `app._evaluating` (app.py:105) | set[int] | ложный/потерянный guard evaluate против delete/reset — гонка записи в СВОЁМ клоне |

Ключ — `(db.current_sid(), doc_id)`; `current_sid()` — единственный источник
(в legacy-тест-режиме возвращает константу). TTL-уборка вычищает ключи
своего sid из всех семи структур.

### Перенос шага 8 деплоя в migrate (CRITICAL из verify-spec)

`update-server.sh` шаг 8 (пин temperature 0.7 на 4 моделях) сегодня идёт
через живой API urllib-ом БЕЗ cookie — при изоляции пин молча уехал бы в
одноразовый клон. Фикс: идемпотентный `_pin_demo_model_temperature(conn)` в
migrate.py (JSON-merge `temperature: 0.7` в `params_json` — рядом с
`_upsert_model_registry_and_remap`, тот же паттерн), вызов из `migrate()`;
шаг 8 из update-server.sh удаляется. Шаг 7 (criterion disable) — проверить
механизм при имплементации: если тоже через API — перенести аналогично
(`_reduce_to_three_criteria` уже существует — вероятно, шаг 7 уже
избыточен; проверить и убрать).

### Что остаётся глобальным (сознательно)

budget (учёт трат и кап $5 — ключ OpenRouter один; лог в /data), LLM-клиенты
и HTTP-пулы, вежливость Wikidata-клиента.

### Инварианты данных

- «Никогда не удалять score/issue» — к golden в полную силу; golden мутирует
  только startup-процедурами и golden-токен-запросами владельца. Сессионные
  клоны — эфемерные копии; их удаление по TTL/рестарту — не удаление
  канонических предсказаний (решение владельца 2026-07-16). Внутри сессии
  семантика прежняя (Reset архивирует, DELETE FROM score/issue отсутствует).
- Обновление канона: deploy (migrate/курация/seed) ИЛИ владелец с
  golden-токеном (create_demo_docs.py).

## Совместимость / ops

- Frontend: без изменений. Vite dev proxy переносит cookie.
- Deploy: rsync не меняется (/data исключён; sessions живут в /data/sessions).
  update-server.sh: шаг 8 удалён (перенесён в migrate), шаг 7 проверить/убрать.
  Бэкап demo.db бэкапит golden. Smoke-GETы без cookie создают ≤5 клонов-сирот —
  снимаются wipe/TTL.
- `scripts/create_demo_docs.py`: параметр `--golden-token` / env; README скрипта.
- Логи: создание клона (sid[:8]), TTL-уборка с числом, golden-токен-запрос
  (факт, без значения токена).
- Диск: 2.4 MB × активные сессии, TTL 4 ч.

## Краевые случаи

| Случай | Поведение |
|---|---|
| Cookie отключены | Каждый запрос — новая сессия; работает, состояние не липнет; приемлемо |
| Два таба одного браузера | Один sid — общая сессия (ожидаемо) |
| Рестарт посреди сессии | Клон удалён wipe-ом; старый cookie валиден → лениво пересоздаётся чистый клон под тем же sid; UX «демо сбросилось» |
| Параллельные первые запросы одной новой сессии | Двойная блокировка `_sessions_guard` — ровно один клон |
| Параллельные запросы одной сессии | `db.current_lock()` — та же сериализация, что сегодня, но per-session |
| TTL против живой фоновой задачи | Свипер пропускает sid с живыми задачами + write-хелперы бампают last_used; маржа 4 ч |
| Deploy smoke / внешние GET без cookie | Одноразовые клоны, wipe/TTL |
| Golden-токен при незаданном env | Заголовок игнорируется — обычная сессия |

## Критерии успеха (Verify)

1. **Изоляция в браузере**: два независимых playwright-профиля параллельно:
   A дисмиссит issue / правит Settings / рефайнит — B ничего не видит, и
   наоборот. Скриншоты обоих.
2. **Golden неизменен**: md5 `/data/demo.db` до/после сессионных мутаций
   совпадает (при этом golden-токен-путь отдельно проверен: с токеном
   создание документа попадает в golden и видно новой сессии после клона).
3. pytest зелёный (599+); новые тесты: cookie ставится; два sid изолированы
   после мутации; fail-loud без sid; двойная блокировка клона (2 треда — 1
   файл); TTL-уборка удаляет файл + ключи всех 7 структур; свипер щадит sid
   с живой задачей; wipe на старте; golden-токен → golden; legacy-фикстуры
   (17 файлов) работают без правок.
4. Deploy: smoke 5/5; пин температуры применён migrate-ом (проверка значений
   в golden после рестарта); фоновый translate доводится внутри сессии.
5. Бюджет-лог общий, в /data.

## План имплементации (исполнителю, по шагам)

1. `db.py`: ContextVar `_session_id`; `current_sid()`; `SessionConn`
   (conn, lock, last_used); кэш `_sessions` + `_sessions_guard`;
   `connect()` по матрице (startup→golden / __golden__→golden / legacy
   `_conn`→него / sid→клон / нет sid→RuntimeError); `current_lock()`;
   `clone_golden(sid)` backup-API; `close_session(sid)`; `wipe_sessions()`
   (глоб `*.db*`); `set_startup_done()`; `touch(sid)` для write-хелперов.
2. Переписать 27 `with db._lock:` → `with db.current_lock():` (app.py ~20,
   terminology_live 5, translate 1, precompute 1). Сам `db._lock` остаётся
   как legacy-объект для тест-режима.
3. `app.py` middleware (cookie + golden-токен, constant-time compare) —
   ставит contextvar до хендлера, Set-Cookie при выдаче нового sid.
4. `app.py` lifespan: migrate+sweep на golden → `wipe_sessions()` →
   `set_startup_done()` → TTL-задача (15 мин; cancel на shutdown).
5. Рекеинг всех 7 структур на `(current_sid(), doc_id)` + уборка ключей в
   `close_session`.
6. `migrate.py`: `_pin_demo_model_temperature`; удалить шаг 8 из
   update-server.sh (шаг 7 — проверить и, если дубль `_reduce_to_three_criteria`,
   убрать).
7. `scripts/create_demo_docs.py`: `--golden-token`/env → заголовок во всех
   запросах.
8. Тесты по критерию 3. Доки same-commit: webapp.md (§ Session isolation),
   contracts-spec delta, deploy/README.md (/data/sessions, golden-токен),
   docs/testing/e2e-data.md (плейбуки e2e получают свежий клон на профиль).
