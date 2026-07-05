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
- Пишется в ТОЙ ЖЕ транзакции, что и изменение `paragraph.target`: PATCH paragraph (только если текст реально изменился — дебаунс уже на фронте, плюс сравнение на бэке), apply-edit, translate (S4), restore (§3.3), reset (пишет ревизию origin='seed' с seed_target).
- Миграция при деплое: для существующих абзацев вставить по одной ревизии из текущего target (origin='seed', created_at=now) — чтобы у всего была базовая ревизия. Инвариант «не удалять предсказания» не задет (только добавляем).
- `score` получает колонку `revision_id INTEGER REFERENCES target_revision(id)` (nullable; старые строки NULL). Evaluate заполняет её текущей (последней) ревизией абзаца.

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

### 3.3 Restore
- `POST /api/paragraphs/{pid}/restore` `{revision_id}` → target := text ревизии, новая ревизия origin='restore', ответ = обновлённый paragraph DTO. Скоры НЕ копируются (после restore чип показывает `—`/старый latest с пометкой; следующий evaluate честно замерит). 409 если ревизия чужого абзаца.
- UI-копирайт: `Revision history`, `Restore`, `Best`, `current`, `not scored`.

### 3.4 Кэш-фолбэк — честная подпись
- Ответ evaluate с `cached:true` уже отличим: в ScoresView добавить бейдж `cached` (`--va-text-dim`, mono, 10px) у затронутых критериев + тултип `Offline fallback estimate, not a live judgment`. Дельта после кэша считается от последнего ЖИВОГО балла, не от кэшевого (фикс §0.2a: `_para_score_views.prev` пропускает kind='cache' при выборе базы для дельты).

## 4. Документный уровень
- `docAggregate` без изменений (сумма latest). Рядом в шапке — при наличии хотя бы одного абзаца, где best>latest: тултип на doc-чипе `Some paragraphs have better past revisions — see ⭰`. Не делаем «doc-best» (агрегат из разных ревизий разных абзацев — фикция).

## 5. Тесты
- Pytest: ревизия пишется на PATCH/apply-edit/reset/restore (и НЕ пишется на no-op PATCH); best-выбор исключает cache; restore создаёт ревизию и не трогает score; evaluate проставляет revision_id; миграция сид-БД (скрипт деплоя) идемпотентна.
- Vitest: History-блок (сортировка, best-маркер, +N more, restore-вызов); cached-бейдж; дельта пропускает cache.
- E2E: изменить абзац → evaluate (балл A) → изменить хуже → evaluate (балл B<A) → History показывает обе ревизии, best=A → Restore → evaluate → балл≈A. Скриншоты каждого шага.

## 6. Риски / решения
- Дисперсия остаётся (LLM). Мы её не маскируем; продуктовая гарантия — «лучший вариант никогда не теряется и восстановим», плюс temperature 0 у судей (S1) уменьшает разброс.
- Rev-спам от дебаунса: PATCH уже дебаунсится 600ms на фронте; бэк дополнительно не пишет ревизию, если текст равен последней ревизии.
- Хранилище: текст абзаца ≤4000 симв., ревизий за демо-сессию десятки — SQLite ок.
