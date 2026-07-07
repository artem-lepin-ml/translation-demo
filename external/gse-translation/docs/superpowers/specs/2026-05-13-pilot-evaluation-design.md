# Spec: пилотная оценка переводов (RQ1 + RQ2)

Брейнсторм 2026-05-13. Фиксирует решения по скоупу Stage 04 scoring над уже сделанными переводами пилотного куска.

**Артефакт-описание эксперимента (research draft):** [docs/experiments/2026-05-13-pilot-evaluation.md](../../experiments/2026-05-13-pilot-evaluation.md) — мотивация, RQ, дизайн, как читаем результаты.

Эта спека — про *что и как мы решили оценивать*. Подробный narrative — в research draft.

## 1. Цель брейнсторма

1. Структурировать research questions так, чтобы каждой RQ соответствовал измеримый артефакт (таблица скоров) и явный механизм ответа.
2. Из 57 имеющихся переводов выбрать минимальное достаточное подмножество, отвечающее на RQ1 и RQ2 без избыточности.
3. Зафиксировать judge profile и наименование ранов для Stage 04.

## 2. Решения

### 2.1 Judge profile (фиксирован для RQ1+RQ2)

Используем только **large-low профиль** Stage 04: `claude-opus-4.7-low` + `gemini-3.1-pro-low` + `gpt-5.5-low`. Median aggregation по трём.

Small-low профиль и qwen-27B-judge оставлены для RQ3 (judge correlation), не подключаются в основном scoring.

### 2.2 Reasoning effort

- **В RQ1 (chunking sweep) — только `-high`.** Изолируем эффект chunking от reasoning. Иначе ortho-grid раздувается без необходимости.
- **В RQ2 (par_by_par sweep) — оба варианта (`-high` и `-low`) там, где провайдер их даёт.** Side-question «помогает ли reasoning» решается естественно поверх RQ2.

### 2.3 Скоуп моделей

| Tier | Семейства в RQ1 (chunking) | Семейства в RQ2 (par_by_par) |
|---|---|---|
| Large frontier | claude-opus, gemini-pro, gpt-5.5 | + claude-sonnet, gpt-5.4 |
| Large alt | — | deepseek, glm, qwen-plus |
| Small frontier | claude-haiku, gpt-5.4-mini, gemini-flash-lite-preview, qwen-flash | (те же) |
| Local OSS | — | gemma, qwen, qwen-edited |

Обоснование:

- В RQ1 не включаем sonnet/gpt-5.4: для claude и gpt уже есть «верх семьи» (opus, gpt-5.5). Меньшие варианты добавляются только в RQ2 для cost-quality карты.
- `glm-5.1`, `qwen3.6-plus`, `deepseek-v4-pro` есть только в `par_by_par` (3 chunkings не запускали), поэтому в RQ1 не идут — только RQ2.
- Из вариантов `gemini-3.1-flash-lite-*` берём только `-preview-high` / `-preview-low` (см. memory 542: non-preview временно недоступен у провайдера).
- Legacy `claude-opus-4.7_*` без reasoning суффикса не включаем — для opus уже есть `-high` / `-low` варианты, legacy перекрывается.

### 2.4 Включение полного pipeline Данилы

Данилин baseline = 3 артефакта, не 2:

1. `data/pilot/translating/local/gemma_par_by_par/translation.md` — gemma one-shot.
2. `data/pilot/translating/local/qwen_par_by_par/translation.md` — qwen one-shot.
3. `data/pilot/translating/local/qwen_par_by_par/edited_translation.md` — qwen translate→eval→edit (*итоговый продукт* старого pipeline, главный baseline для RQ2).

Третий артефакт — самый сильный baseline: small/large-frontier сравниваем не только с one-shot OSS, но и с pipeline-доработкой.

## 3. Контрактное изменение: `qwen_edited_par_by_par`

Stage 04 читает `<bucket>/<run_name>/translation.md` (см. [pilot_interfaces_agreement.md](../../pilot_interfaces_agreement.md) § 03). Чтобы оценить `edited_translation.md` как отдельный run без расширения контракта — создаём четвёртую run-папку:

```
data/pilot/translating/local/qwen_edited_par_by_par/
    translation.md -> ../qwen_par_by_par/edited_translation.md   (symlink)
    config.json                                                   (новый, копия qwen_par_by_par/config.json с обновлённым run_name)
```

Создаётся перед запуском Stage 04. Не часть этой спеки.

Альтернатива (расширить Stage 04 чтобы принимать опциональный `translation_file` параметр) отвергнута — лишняя сложность ради одного рана.

## 4. Полный список ранов (32 уникальных)

См. таблицы в [research draft § 5](../../experiments/2026-05-13-pilot-evaluation.md#5-сводный-список-ранов-под-scoring).

Разбивка:

| Группа | Кол-во |
|---|---|
| RQ1 large chunking sweep | 9 |
| RQ1 small chunking sweep | 8 |
| RQ2 large frontier additional | 7 |
| RQ2 large alt | 3 |
| RQ2 small additional reasoning | 2 |
| RQ2 local OSS (Данилин baseline) | 3 |
| **Total** | **32** |

Все пути валидируются перед запуском Stage 04 (`translation.md` существует и не пустой; для symlink — целевой файл тоже).

## 5. Бюджет

- 32 ранов × 549 параграфов × 3 judge LLM × 3 промпта на параграф (faithfulness + english_quality + factcheck) ≈ **158 000 judge calls**.
- Без factcheck (если решим выкатывать его отдельно) — ~105 000.
- Если позже накладываем small-low профиль для RQ3 на subset из 5 ранов — ещё +5 × 549 × 3 × 3 ≈ 25 000.

Бюджет на токены — приемлемо для текущей итерации (по словам владельца репо). Время по API: оцениваем после первого прогона на 1 ране.

## 6. Зависимости

| Зависимость | Статус | Где |
|---|---|---|
| Stage 04 multi-judge implementation | в работе по 18-task TDD плану | memory S203 |
| Spec Stage 04 (judge profiles, consolidated prompts, aggregation) | финализирован | memory S195, S197 |
| Все 31 перевод на диске | готовы | `data/pilot/translating/` |
| 32-й (qwen_edited_par_by_par симлинк) | создаётся перед прогоном | этот документ § 3 |
| RQ3 (correlation analysis) | вторая очередь | memory S197 |

## 7. Out of scope для этого брейнсторма

- Реализация Stage 04 multi-judge (отдельный план).
- RQ3 correlation analysis (вторая очередь, после получения main scoring).
- Изменения промпта перевода (`prompts/02_translate/*`) — зафиксирован.
- `smart_llm_split` chunking — не запускали.
- Прогон по полным 7 томам.
- Композитный score и его веса — обсуждаем с supervisor после получения первых таблиц.

## 8. Open questions (решаются после первого прогона)

- Веса композитного score (для RQ2 ранжирования) — supervisor.
- Какие конкретно 5 ранов идут в RQ3 subset — выбираем по результатам RQ1+RQ2 (берём максимально разнородные).
- Нужны ли поправки на multiple comparisons в RQ1: Holm-Bonferroni vs FDR — определяемся после первого взгляда на p-value distribution.

## 9. Cross-references

- Research draft (motivation, RQ, дизайн, ответы): [docs/experiments/2026-05-13-pilot-evaluation.md](../../experiments/2026-05-13-pilot-evaluation.md)
- Pipeline overview: [docs/pipeline.md](../../pipeline.md)
- Stage 04 design: [docs/stages/03_evaluate.md](../../stages/03_evaluate.md)
- Pilot artifact contract: [docs/pilot_interfaces_agreement.md](../../pilot_interfaces_agreement.md)
- Factcheck operational guide: [docs/factchecker.md](../../factchecker.md)
