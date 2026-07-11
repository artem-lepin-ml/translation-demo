# docs-keeper: Wiki-eval sweep commit — 2026-07-11

## Scope

Механическая фиксация (коммит) результатов ночных прогонов wiki-eval-harness и подготовленных отчётов агентов:
- Обновленный финальный отчёт (20-article judge intersection, свежие числа)
- Четыре отчёта ml-engineer о постановке диагноза и восстановлении после сбоев

**Ограничения:** только коммит в `docs/reports/` (L2 уровень); не трогаем live-run директории под `reports/terminology/wiki-eval/`.

## Files changed

Коммит `2df27bd` (push успешно):

### Modified
- **`docs/reports/html/wiki-eval-final-2026-07-11.html`** — финальный отчёт; обновлены числовые данные по пересечению judge-х (20 статей, актуальные оценки)

### Created (agent reports)
- **`docs/reports/ml-engineer-judge-x3-refresh.md`** — отчёт о бабиситинге трёх judge'ей (переформатирование, восстановление после сбоя)
- **`docs/reports/ml-engineer-wiki-eval-babysit-stalled-runs.md`** — отчёт о восстановлении зависших прогонов на ночь
- **`docs/reports/ml-engineer-wiki-eval-gemma4-single-run-diagnostic.md`** — диагноз одного прогона Gemma-4 (изоляция проблемы)
- **`docs/reports/ml-engineer-wiki-eval-mass-process-death-recovery.md`** — отчёт о восстановлении после массового отказа процессов

**Не включены в коммит** (как и ожидалось):
- 12 modified файлов под live-run директориями (`.jsonl` из deepseek, gemini, gemma-4, qwen прогонов) — остаются в working tree как часть активных экспериментов
- 7 untracked директорий gemma-3-27b-it runs и 4 файла wikidata кеша — экспериментальные артефакты, не входят в docs/reports/ sweep

## Decisions & rationale

1. **Стадирование ровно 5 файлов** — следование инструкции "EXACTLY those paths"; избегаем случайного сташирования live-run данных (`reports/terminology/**`), которые активны и меняются в процессе экспериментов.

2. **Коммит-сообщение по Conventional Commits** — `docs(wiki-eval): refresh final report to 20-article judge intersection + overnight babysit reports`; область `wiki-eval`, вид `docs`, без AI-подписей (согласно Hard Invariant 7).

3. **Push с retry-логикой** — попытка 1 успешна, сетевых ошибок не было; стандартные backoff-таймауты (2s–16s) готовы на случай отказа, хотя не понадобились.

4. **Ручное исключение экспериментальных данных** — `git add` с явным списком файлов вместо `git add -A`, чтобы гарантировать, что live-run JSONL (progress, pred.partial, calls) и неполные кеши не попадут в общий коммит; они остаются для следующей консолидации или архивации позже.

## Open questions

Нет открытых вопросов. Задача — чистый механический коммит с чётким границами: 5 завершённых артефактов в docs/reports/ (финальный отчёт + 4 диагностических отчёта от ml-engineer), всё остальное оставляется в working tree.

## NOT done

- Архивация или фиксация live-run директорий под `reports/terminology/` — это отдельная задача (требует консенсуса о том, какие прогоны считаются завершёнными и готовыми к архиву)
- Консолидация wikidata кешей (будут включены в следующий sweep)
- Любые изменения самих агентских отчётов (они уже готовы, копирование как есть)

---

**Commit:** `2df27bd`  
**Branch:** `claude/ner-translation-config-b0ozsc`  
**Status:** ✓ Успешно, обе задачи выполнены (commit + push).
