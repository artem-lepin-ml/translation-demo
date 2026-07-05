# Спека S5 — Немонотонная переоценка: история ревизий и «лучший вариант в глубине»

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Проблема владельца: «при переоценке качество может снижаться… учитывать историю или сделать аккумуляцию правок и находить наиболее удачный вариант в глубине».

## 0. Grounding (корень проблемы — из разведки)

1. `score` уже append-only: каждая переоценка INSERT-ит `kind='live'`-строки; `_para_score_views` (`app.py:130-147`) строит latest/prev/baseline. История хранится, но UI показывает только latest vs prev vs baseline.
2. Два источника «снижения»:
   a. **Кэш-аплифт**: seed-кэш = baseline + фикс. `CACHE_UPLIFT=1.5` (`seed.py:36,110-111`); фолбэк на таймауте показывает завышенный балл, следующий живой judge честно ниже → «упало» (docs/known_issues.md:70-71).
   b. **Дисперсия судьи**: каждый evaluate — независимое суждение; даже на неизменном тексте живой балл гуляет.
3. Текст абзаца (`paragraph.target`) мутируется на месте (PATCH, apply-edit) — истории версий текста НЕТ: «удачный вариант в глубине» сейчас невосстановим в принципе.

## 1. Цель и принцип

Честность важнее косметики (quality bar «honest deltas»): мы НЕ подкручиваем баллы и НЕ прячем снижение. Вместо этого:
- каждая версия текста сохраняется (ревизии);
- каждая оценка привязывается к ревизии;
- «лучший вариант» всегда виден и восстановим в один клик;
- дисперсия судьи снижается детерминизмом (temperature 0 — S1 §2.4 seed-params) и сравнением ревизий, а не одиночных замеров.

## 2. Данные

### 2.1 Новая таблица (DDL — дельта SSOT)
```sql
CREATE TABLE target_revision (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  origin TEXT NOT NULL,           -- 'seed' | 'edit' | 'apply_edit' | 'translate' | 'restore'
  created_at TEXT NOT NULL
);
CREATE INDEX idx_target_revision_para ON target_revision(paragraph_id, id);
```
`origin`: `'seed' | 'upload' | 'edit' | 'apply_edit' | 'translate' | 'restore'`.
- **Полный список точек записи ревизии (HIGH из ревью — исходный список был неполон).** Ревизия пишется в той же транзакции, что и изменение/создание `paragraph.target`:
  1. `POST /api/documents` — создание абзацев (обычная пара: origin='upload' с исходным target; translate:true — ревизию НЕ пишем, target пуст, её напишет translate);
  2. PATCH paragraph (origin='edit'; только если текст реально изменился — сравнение на бэке);
  3. apply-edit (origin='apply_edit');
  4. translate S4 (origin='translate', по мере записи каждого абзаца);
  5. restore §3.3 (origin='restore');
  6. reset (origin='seed', текст = seed_target);
  7. seed.py — базовая ревизия origin='seed' на каждый абзац при засеве (чтобы свежая dev/test БД совпадала по форме с мигрированным продом).
- **Штамповка `score.revision_id` — во ВСЕХ трёх местах INSERT INTO score** (ревью нашло три): `app.py:493` (evaluate), `precompute.py:97-109` (`_write_paragraph` — единственный путь оценки свежезагруженных/переведённых документов!), `seed.py:118-125` (baseline+cache при засеве → ссылаются на ревизию п.7). Хелпер `db.latest_revision_id(paragraph_id)`.
- `score.revision_id INTEGER REFERENCES target_revision(id)` (nullable). Исторические прод-строки остаются NULL — честно; «best» активируется вперёд с момента деплоя.

### 2.4 Миграционный модуль (CRITICAL из ревью: механизма миграций в проекте НЕТ; владелец модуля — эта спека, S4/S1 переиспользуют)
- Новый `src/palimpsest/webapp/migrate.py`: функция `migrate(conn)` — СТРОГО аддитивные идемпотентные шаги: `CREATE TABLE IF NOT EXISTS target_revision (...)`; `CREATE TABLE IF NOT EXISTS translator_config (...)` (+INSERT seed-строки конфига при отсутствии — S4 §2.1); `ALTER TABLE score ADD COLUMN revision_id ...` под защитой `PRAGMA table_info(score)`; backfill: абзацам без единой ревизии — одна ревизия из текущего target (origin='seed').
- Вызов: (а) на старте приложения (lifespan / первый connect — до обслуживания запросов) — прод получает схему автоматически при рестарте контейнера; (б) CLI `python -m palimpsest.webapp.migrate` для ручного прогона. Деплой-чеклист: `cp demo.db demo.db.bak-$(date +%s)` ПЕРЕД рестартом.
- Параллельно та же DDL добавляется в `db.py::SCHEMA` (безусловно — из него строятся все свежие БД; иначе тесты зелёные на схеме, которой нет на проде).
- Тесты: миграция дважды подряд на заполненной фикстуре (идемпотентность, данные целы); эквивалентность схем «fresh seed» vs «старая БД + migrate» (сравнение sqlite_master по таблицам/колонкам).

### 2.2 Понятие «лучшая ревизия»
- `best = argmax(aggregate)` по score-строкам абзаца с `kind='live'` или `'seed'` (кэш-строки `kind='cache'` ИСКЛЮЧЕНЫ — они синтетические, см. §0.2a) с непустым revision_id; тай-брейк — новее.
- Вычисляется на лету в `_para_score_views` (без денормализации): добавить в DTO paragraph-скоров блок `best: {aggregate, revision_id, created_at, is_current: bool}`.

## 3. UI (Inspector, Document-таб)

### 3.1 Score-чип абзаца
- Показ как сейчас (latest), но если `best.aggregate > latest.aggregate + 0.05` и `!best.is_current` → рядом с чипом маленький значок ⭰ (best-маркер, `--va-yellow`) с тултипом `Best 8.4 — click to review`. Клик → Inspector открывает History-блок (§3.2).

### 3.2 History-блок в Inspector (новый, под ScoresView)
- Заголовок `Revision history` + компактный список (макс 8 последних, старее — `+N more` раскрытие): каждая строка = `origin-иконка · {aggregate или —} · {relative time} · [Restore]`; текущая ревизия помечена `current`, лучшая — ⭰ жёлтым.
- Ревизии без оценки показывают `—` (не оценивались) — честно.
- Diff-подсказка: клик по строке истории → под списком мини-панель с текстом этой ревизии (read-only, 6 строк макс, скролл) — без полноценного diff-рендера (не изобретать; простой текст).

### 3.3 Restore + список ревизий (REST — дельта SSOT)
- `GET /api/paragraphs/{pid}/revisions` → `{revisions: [{id, origin, createdAt, text, aggregate: number|null, isBest, isCurrent}]}` (aggregate — лучший score-агрегат, привязанный к этой ревизии, null если не оценивалась; сортировка новые-сверху). Питает History-блок §3.2.
- `POST /api/paragraphs/{pid}/restore` `{revisionId}` → target := text ревизии, новая ревизия origin='restore', ответ = обновлённый paragraph DTO. Скоры НЕ копируются (после restore чип показывает `—`/старый latest с пометкой; следующий evaluate честно замерит). 409 если ревизия чужого абзаца.
- UI-копирайт: `Revision history`, `Restore`, `Best`, `current`, `not scored`.

### 3.4 Кэш-фолбэк — честная подпись (только фронт; backend-«фикс» снят ревью)
- Факт (ревью): `_para_score_views` (`app.py:126-131`) УЖЕ выбирает только `kind IN ('seed','live')` — кэш никогда не участвует в дельте; «падение» от кэша — чисто отображенческий артефакт транзиентного `cached:true`-ответа, в БД он не персистится. Backend не трогаем.
- Фронт: в ScoresView бейдж `cached` (`--va-text-dim`, mono, 10px) у затронутых критериев + тултип `Offline fallback estimate, not a live judgment` — этого достаточно, чтобы кэш-число не читалось как живой балл.

## 4. Документный уровень
- `docAggregate` без изменений (сумма latest). Рядом в шапке — при наличии хотя бы одного абзаца, где best>latest: тултип на doc-чипе `Some paragraphs have better past revisions — see ⭰`. Не делаем «doc-best» (агрегат из разных ревизий разных абзацев — фикция).

## 5. Тесты
- Pytest: ревизия пишется на create/PATCH/apply-edit/reset/restore/translate (и НЕ пишется на no-op PATCH); best-выбор исключает cache; restore создаёт ревизию и не трогает score; revision_id проставляют ВСЕ ТРИ score-пути (evaluate, precompute._write_paragraph, seed); migrate.py — идемпотентность двойного прогона + эквивалентность схем fresh-vs-migrated; «best» активируется на свежезагруженном документе после precompute (регрессия на главный HIGH ревью).
- Vitest: History-блок (сортировка, best-маркер, +N more, restore-вызов); cached-бейдж; дельта пропускает cache.
- E2E: изменить абзац → evaluate (балл A) → изменить хуже → evaluate (балл B<A) → History показывает обе ревизии, best=A → Restore → evaluate → балл≈A. Скриншоты каждого шага.

## 6. Риски / решения
- Дисперсия остаётся (LLM). Мы её не маскируем; продуктовая гарантия — «лучший вариант никогда не теряется и восстановим», плюс temperature 0 у судей (S1) уменьшает разброс.
- Rev-спам от дебаунса: PATCH уже дебаунсится 600ms на фронте; бэк дополнительно не пишет ревизию, если текст равен последней ревизии.
- Хранилище: текст абзаца ≤4000 симв., ревизий за демо-сессию десятки — SQLite ок.
