# docs-keeper — doc-parity проверка stability-волны (uncommitted diff, feat/emnlp-demo-sprint)

## Scope

Проверена текущая незакоммиченная дельта (`git status`/`git diff` в воркдереве
`/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, ветка `feat/emnlp-demo-sprint`):
терминологический пайплайн (per-mention isolation, `use_cirrus`/`use_sitelink`
trace-переименование), backend `app.py`/`terminology_live.py` (startup sweep,
clone-cache byte-exact fingerprint + score-gate, NER/grounding таймауты),
фронтенд (`store.ts`, `GlossaryTab.tsx`, `glossary-grouping.ts`,
`InspectorPanel.tsx`, `VariantA.tsx`) и `deploy/update-server.sh`
(`PALIMPSEST_BUDGET_LOG`). Канонические доки, которые уже были тронуты этой
же дельтой (`docs/stages/terminology.md`, `docs/subsystems/webapp.md`,
`docs/superpowers/specs/2026-06-30-demo-contracts.md`), проверены на полноту
и точность; там, где парности не хватало, внесены минимальные правки.

## Files changed

- `docs/subsystems/webapp.md` — 4 добавления/правки (см. Decisions).
- `deploy/README.md` — 1 добавление (переменная `PALIMPSEST_BUDGET_LOG` в
  описании `DATA_DIR`).
- `docs/stages/terminology.md`, `docs/superpowers/specs/2026-06-30-demo-contracts.md` —
  не редактировались повторно: уже полны и точны (проверено, см. Decisions).

## Decisions & rationale

Что уже было в порядке (внесено предыдущим агентом в этой же дельте, я
только сверил код↔факт):

1. **Per-mention isolation в `pipeline.run`** — `docs/stages/terminology.md`
   пункт "Per-mention isolation (2026-07-16 fix)" точно описывает
   `try/except` вокруг `grounder.ground()`, исключение `FatalGroundingJudgeError`
   и расширение catch в `label_first.py` до `(RuntimeError, HTTPError, OSError)`.
   Сверено построчно с `pipeline.py`/`label_first.py`. Без изменений.
2. **`use_cirrus`/`use_sitelink` вместо `use_fallbacks` в trace** — это
   переименование одного ключа в `trace_json.config` (комментарий в
   `label_first.py:313`), а сама фича `use_cirrus`/`use_sitelink` уже
   задокументирована с 2026-07-06 в `docs/stages/terminology.md` (§ Design
   decisions, ablation) и `docs/stages/wiki-eval.md`. Ни один потребитель
   trace.config во фронтенде/спеке не читает это поле — переименование не
   требует правки контракта. Без изменений.
3. **Startup sweep `_reset_stuck_terms`** — `docs/subsystems/webapp.md`
   ("Status column, not an in-memory registry — but restart recovery is an
   explicit startup sweep...") и `docs/superpowers/specs/2026-06-30-demo-contracts.md`
   уже точно и честно описывают факт ("значение колонки переживает рестарт,
   но это НЕ значит «безопасно»") и сам fix. Сверено с `app.py::_reset_stuck_terms`
   и `_lifespan`. Без изменений.
4. **Clone cache: raw-байтовый fingerprint + `_clone_source_eligible`** —
   `docs/subsystems/webapp.md` "Content clone cache" полностью переписан
   под новую raw-hash логику и score-гейт; сверено с `app.py::_content_fingerprint`,
   `_clone_source_eligible`, `_find_clone_source`. Без изменений.
5. **NER/grounding таймауты** — `docs/subsystems/webapp.md` "Timeout ceilings"
   точно описывает `_effective_ner_timeout` (client.config.timeout + 5s) и
   `_GROUNDING_TIMEOUT` (180s, env `PALIMPSEST_TERMS_GROUNDING_TIMEOUT`);
   сверено с `terminology_live.py`. Без изменений.

Что было расхождением (найдено, исправлено):

6. **`docs/subsystems/webapp.md` — grounding-path stepper описан по старой,
   никогда реально не работавшей схеме.** Строка про `GlossaryTab.tsx`
   утверждала 4-шаговый stepper "QUERY→SEARCH→LABEL MATCH→DECISION". Дифф
   переписывает `stepPresentation`/`candidatesForDisplay` на реальную плоскую
   форму трейса (`queries`/`candidates`/`exact_matches`/`judge`/`chosen_qid`),
   потому что старая вложенная форма (`TraceStep`) никогда не эмитится живым
   пайплайном (`label_first.py::_result` пишет плоскую форму) — это был
   код↔доки дрейф, из-за которого степпер всегда рендерил "Skipped — no
   trace" на живых терминах. Также исправлена колонка Matched: она читала
   несуществующее поле `matched_via` вместо `trace_json.candidates[].matched`.
   Обновил таблицу компонентов: новые имена шагов (SEARCH→CANDIDATES→EXACT→DECISION)
   + абзац про trace-shape fix + про Matched-колонку.
7. **`docs/subsystems/webapp.md` — red-dot poisoning fix в `glossary-grouping.ts`
   не был задокументирован.** `buildFields` теперь фильтрует агрегацию
   `difficulty` по `qid` группы, чтобы ungrounded lemma-сиблинг, слитый чисто
   ради dedup, не красил точку у уже сгруппированного grounded-термина.
   Добавил абзац в описание `glossary-grouping.ts`.
8. **`docs/subsystems/webapp.md` — Refine-кнопка описана как доступная без
   уточнения таба.** Диффом снято условие `tab === 'issues'` — кнопка теперь
   видна и на Scores. Уточнил формулировку в строке `InspectorPanel.tsx`.
9. **`docs/subsystems/webapp.md` — `refreshDocument` (store.ts) не описывал
   два новых защитных механизма.** Диффом добавлены (а) stale-fetch guard
   (проверка `document.id` после `await` перед `set()`) и (б) обработка 404
   удалённого документа (`stopTermsPolling` + возврат на picker). Добавил
   отдельный пункт в Subtleties + сослался на него из строки состояния стора.
10. **`deploy/README.md` — переменная `-e PALIMPSEST_BUDGET_LOG=/data/budget_calls.jsonl`
    в `update-server.sh` не упоминалась явно.** Строка `DATA_DIR` уже
    утверждала, что `budget_calls.jsonl` живёт на volume — это было целевым
    состоянием, ставшим фактом только этим коммитом (до фикса `PALIMPSEST_BUDGET_LOG`
    не передавался, и `budget.py`'s default писал файл в дерево приложения,
    которое теряется при пересборке). Добавил уточнение прямо в строку `DATA_DIR`
    вместо новой строки — факт один (место, где живёт budget-лог), лишняя
    строка была бы дублированием.

Что НЕ трогал по правилам границ зоны (найден дрейф вне диффа, без правок):

- `docs/known_issues.md` — файл сам декларирует конвенцию "Fixed bugs are
  not listed here" (шапка файла), поэтому ни новую запись про red-dot/trace-shape
  баги, ни про startup-sweep не добавлял — это по определению не тот файл.
  Записи про "Translate status is lost on server restart" (для
  `translate`/`precompute`, отдельная фича) не затронуты этой дельтой и
  остаются верными как есть — не путать с terms_status, для которого fix
  уже есть и описан в webapp.md.
- Не проверял весь остальной `docs/` корпус на дрейф вне зоны диффа (это
  отдельная задача с согласия владельца, вне текущего скоупа).

## Open questions

Нет открытых вопросов к владельцу — все найденные расхождения однозначно
устранимы правкой докстрок без решений, требующих его участия.

## NOT done (explicit)

- Не запускал тесты/линтеры — задача была чисто doc-parity, код не менял.
- Не проверял `docs/reports/*.md` (десятки untracked report-файлов в
  `git status`) — это отчёты предыдущих агентов, не часть L1→L4 иерархии,
  вне скоупа doc-parity.
- Не сверял English/`.md` UI-копирайт-инвариант (Hard Invariant 9) — фронтенд-строки
  в диффе (Reset dialog copy) уже на английском, отдельная проверка не
  требовалась.
- Не коммитил и не пушил ничего (по инструкции задачи).

## Полный список сверенных пар код↔докс

| Код | Документация | Статус |
|---|---|---|
| `src/palimpsest/terminology/pipeline.py::run` (per-mention try/except) | `docs/stages/terminology.md` "Per-mention isolation (2026-07-16 fix)" | сверено, точно |
| `src/palimpsest/terminology/grounding/label_first.py` (`use_cirrus`/`use_sitelink` в trace.config) | `docs/stages/terminology.md` § Design decisions + `docs/stages/wiki-eval.md` | сверено, точно (переименование не требует правки) |
| `src/palimpsest/webapp/app.py::_reset_stuck_terms` + `_lifespan` | `docs/subsystems/webapp.md` "Status column... startup sweep" + `docs/superpowers/specs/2026-06-30-demo-contracts.md` | сверено, точно |
| `src/palimpsest/webapp/app.py::_content_fingerprint` (raw-байтовый hash) | `docs/subsystems/webapp.md` "Fingerprint — byte-exact" | сверено, точно |
| `src/palimpsest/webapp/app.py::_clone_source_eligible`/`_find_clone_source` | `docs/subsystems/webapp.md` "Match rule" | сверено, точно |
| `src/palimpsest/webapp/terminology_live.py::_effective_ner_timeout` | `docs/subsystems/webapp.md` "Timeout ceilings" (NER leg) | сверено, точно |
| `src/palimpsest/webapp/terminology_live.py::_GROUNDING_TIMEOUT`/`asyncio.wait_for` вокруг `pipeline.run` | `docs/subsystems/webapp.md` "Timeout ceilings" (grounding leg) | сверено, точно |
| `frontend/src/demo/variant-a/GlossaryTab.tsx::stepPresentation`/`candidatesForDisplay` (real flat trace shape) | `docs/subsystems/webapp.md` строка `GlossaryTab.tsx` | **исправлено** (было: старая QUERY/SEARCH/LABEL MATCH/DECISION схема) |
| `frontend/src/demo/variant-a/glossary-grouping.ts::buildFields` (qid-gated difficulty) | `docs/subsystems/webapp.md` строка `glossary-grouping.ts` | **исправлено** (было не описано) |
| `frontend/src/demo/variant-a/InspectorPanel.tsx` (Refine-кнопка без `tab==='issues'` гейта) | `docs/subsystems/webapp.md` строка `InspectorPanel.tsx` | **исправлено** |
| `frontend/src/demo/store.ts::refreshDocument` (stale-fetch guard + 404 handling) | `docs/subsystems/webapp.md` Subtleties, новый пункт | **исправлено** (было не описано) |
| `frontend/src/demo/variant-a/VariantA.tsx` (Reset dialog copy: "archived, not lost") | `docs/subsystems/webapp.md` "Reset:" (backend-правда об archive не delete) | сверено — фронтенд-копирайт теперь совпадает с уже верной доке; правка доки не требовалась |
| `deploy/update-server.sh` (`-e PALIMPSEST_BUDGET_LOG=/data/budget_calls.jsonl`) | `deploy/README.md` строка `DATA_DIR` | **исправлено** (уточнена причина/дата фикса) |
