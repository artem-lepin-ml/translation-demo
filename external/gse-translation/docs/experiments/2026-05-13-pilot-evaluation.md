# Пилотная оценка переводов: chunking, ярус модели, согласованность судьи

Up-link: [docs/pipeline.md](../pipeline.md).

Документ описывает эксперимент Stage 04 над уже сделанными переводами пилотного куска (549 параграфов, том I). Источник по контракту артефактов — [docs/pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md); по multi-judge scoring — [docs/stages/03_evaluate.md](../stages/03_evaluate.md). Брейнсторм-решения по скоупу — [docs/superpowers/specs/2026-05-13-pilot-evaluation-design.md](../superpowers/specs/2026-05-13-pilot-evaluation-design.md).

## 1. Контекст и мотивация

Цель команды — собрать максимально качественный черновик перевода 7 томов энциклопедии RU → academic EN. Пилотируем на 3 главах первого тома (549 параграфов, см. `data/pilot/pilot_original.md`).

**Существующий baseline (работа Данилы):** локальные модели (gemma и qwen 27B) переводят по одному параграфу, затем тот же qwen 27B оценивает по 6 критериям + factcheck, и затем правит перевод по замечаниям. Артефакты — в `data/pilot/translating/local/` и `data/pilot/evaluation/qwen_pilot/`.

**Что меняем сейчас:**

- Pool моделей расширен до 14 семейств (3 frontier-семейства и 6 семейств всего по постановке): claude (opus/sonnet/haiku), gpt (5.5/5.4/5.4-mini), gemini (pro/flash-lite), deepseek, glm, qwen (plus/flash/local), gemma-local.
- Стратегии чанкинга: `par_by_par` (1 параграф), `by_5_par` (5), `by_10_par` (10). По 1/5/10 переведено там, где это семейство тянет такой контекст.
- Reasoning effort: где провайдер позволяет — два варианта (`-low`, `-high`).
- Scoring перестроен с x6 одно-критериевых вызовов на 2 консолидированных промпта (faithfulness + english_quality) + factcheck, и одновременно прогоняется тремя LLM-судьями вместо одного.

## 2. Research Questions

### RQ1 — Эффект гранулярности чанкинга

**Вопрос.** Влияет ли стратегия чанкинга (1 / 5 / 10 параграфов за вызов) на качество перевода, и зависит ли эффект от яруса модели?

**Гипотеза.** Для больших frontier-моделей контекст в 5–10 параграфов улучшает связность, терминологическую стабильность и стиль; для маленьких моделей рост контекста скорее вредит — теряют id, путают абзацы, проседают по точности.

### RQ2 — Cost-quality граница между ярусами моделей

**Вопрос.** Где проходит граница «достаточно хорошо для черновика» между large frontier, small frontier и локальными open-source моделями? Оправданы ли затраты на дорогие LLM?

**Гипотеза.** Large frontier на пиле качества заметно выше small frontier, а small frontier — заметно выше локальных one-shot переводов; одновременно edited-baseline Данилы (qwen 27B translate→eval→edit) ожидаемо тянется к нижней границе small frontier и может конкурировать с дешёвыми облачными моделями.

### RQ3 — Согласованность llm-as-judge (вторая очередь)

**Вопрос.** Насколько одно-моделевый qwen-27B-judge Данилы согласован с frontier multi-judge ensemble, по какому критерию расходится и есть ли систематический bias?

**Гипотеза.** Для accuracy и factcheck корреляция высокая (объективные критерии); для cultural / style / consistency — низкая (субъективные); qwen-27B завышает оценки относительно frontier.

Эта RQ запускается после получения main scoring по RQ1+RQ2 и не блокирует первую итерацию.

## 3. Дизайн эксперимента

### 3.1 Факторы

| Фактор | Уровни | Контролируется |
|---|---|---|
| Tier | large-frontier, large-alt, small-frontier, local-oss | derived из bucket+family |
| Family | claude, gpt, gemini, deepseek, glm, qwen, gemma | категориальный |
| Reasoning effort | high, low, none | где провайдер позволяет |
| Chunking | par_by_par, by_5_par, by_10_par | основной фактор RQ1 |

**Фиксировано на весь эксперимент:**

- Текст: 549 параграфов из `data/pilot/pilot_original.md`.
- Промпт перевода: `prompts/02_translate/system.md` + `user.md`, версия сохранена в `config.json` каждого рана.
- Judge: large-low профиль multi-judge — `claude-opus-4.7-low`, `gemini-3.1-pro-low`, `gpt-5.5-low`.
- Temperature перевода: 0.0 (см. `config.json`).

### 3.2 Дизайн под RQ1

Ortho-grid `family × chunking` при фиксированном reasoning=`high`. Reasoning не варьируется в RQ1, чтобы изолировать эффект chunking.

- **Large тиr** (3 семейства × 3 чанкинга = 9 ранов): claude-opus-4.7-high, gemini-3.1-pro-high, gpt-5.5-high.
- **Small тиr** (4 семейства × 2 чанкинга — `by_5` для small не запускался = 8 ранов): claude-haiku-4.5, gpt-5.4-mini-high, gemini-3.1-flash-lite-preview-high, qwen3.6-flash.

### 3.3 Дизайн под RQ2

Чанкинг фиксирован = `par_by_par` (доступен у всех моделей). Sweep по семьям и ярусам, оба reasoning варианта где есть.

- **Large frontier** (5 семейств × {-high, -low} = 10 ранов): opus, sonnet-4.6, gemini-pro, gpt-5.4, gpt-5.5.
- **Large alt** (3 семейства × no-reasoning = 3 рана): deepseek-v4-pro, glm-5.1, qwen3.6-plus.
- **Small frontier** (4 семейства, у двух — оба reasoning = 6 ранов): haiku-4.5, gpt-5.4-mini × {-high, -low}, gemini-flash-lite-preview × {-high, -low}, qwen3.6-flash.
- **Local OSS** (3 артефакта Данилы): gemma_par_by_par, qwen_par_by_par, qwen_edited_par_by_par (qwen translate→eval→edit пайплайн).

Overlap с RQ1: 7 ранов (все par_by_par-варианты из RQ1 — 3 large + 4 small — переиспользуются как точки RQ2). После вычета overlap в RQ2 добавляется 15 уникальных ранов.

### 3.4 Side-question внутри RQ2: эффект reasoning

Внутри каждой large-frontier семьи с двумя reasoning-вариантами сравниваем `-high` vs `-low` по par_by_par. Не отдельная RQ, но даёт ответ «стоит ли платить за high reasoning при переводе».

## 4. Метрика и judge

Stage 04 (см. [docs/stages/03_evaluate.md](../stages/03_evaluate.md)) выдает на каждый параграф 7 оценок:

| Критерий | Шкала | Источник промпта |
|---|---|---|
| accuracy | 1–10 | faithfulness consolidated |
| terminology | 1–10 | faithfulness consolidated |
| cultural | 1–10 | faithfulness consolidated |
| fluency | 1–10 | english_quality consolidated |
| style | 1–10 | english_quality consolidated |
| consistency | 1–10 | english_quality consolidated |
| factcheck | F1 ∈ [0, 1] | two-sided atomic-fact overlap |

3 LLM-судьи (opus-low, gemini-pro-low, gpt-5.5-low) выдают оценки независимо. **Aggregation:** median по 3 судьям per criterion per paragraph; затем mean по параграфам — итоговая оценка рана.

Median вместо mean между судьями — устойчиво к выбросу одного судьи. Mean по параграфам — стандартный summary.

Источник `score = -1` (judge не справился, parse failed) исключается из агрегатов.

## 5. Сводный список ранов под scoring

Полный путь: `data/pilot/translating/<bucket>/<run_name>/translation.md`. Всего 32 уникальных рана.

### 5.1 RQ1 chunking sweep (17 ранов)

**Large, reasoning=high, 3 чанкинга:**

| Run name | Bucket |
|---|---|
| `claude-opus-4.7-high_par_by_par` | large |
| `claude-opus-4.7-high_by_5_par` | large |
| `claude-opus-4.7-high_by_10_par` | large |
| `gemini-3.1-pro-high_par_by_par` | large |
| `gemini-3.1-pro-high_by_5_par` | large |
| `gemini-3.1-pro-high_by_10_par` | large |
| `gpt-5.5-high_par_by_par` | large |
| `gpt-5.5-high_by_5_par` | large |
| `gpt-5.5-high_by_10_par` | large |

**Small, 2 чанкинга (by_5_par для small не запускался):**

| Run name | Bucket |
|---|---|
| `claude-haiku-4.5_par_by_par` | small |
| `claude-haiku-4.5_by_10_par` | small |
| `gpt-5.4-mini-high_par_by_par` | small |
| `gpt-5.4-mini-high_by_10_par` | small |
| `gemini-3.1-flash-lite-preview-high_par_by_par` | small |
| `gemini-3.1-flash-lite-preview-high_by_10_par` | small |
| `qwen3.6-flash_par_by_par` | small |
| `qwen3.6-flash_by_10_par` | small |

### 5.2 RQ2 par_by_par additional (15 ранов)

**Large frontier, reasoning=low (для пары с -high из RQ1) + новые семьи:**

| Run name | Bucket |
|---|---|
| `claude-opus-4.7-low_par_by_par` | large |
| `claude-sonnet-4.6-high_par_by_par` | large |
| `claude-sonnet-4.6-low_par_by_par` | large |
| `gemini-3.1-pro-low_par_by_par` | large |
| `gpt-5.4-high_par_by_par` | large |
| `gpt-5.4-low_par_by_par` | large |
| `gpt-5.5-low_par_by_par` | large |

**Large alt:**

| Run name | Bucket |
|---|---|
| `deepseek-v4-pro_par_by_par` | large |
| `glm-5.1_par_by_par` | large |
| `qwen3.6-plus_par_by_par` | large |

**Small, reasoning=low (для пары с -high из RQ1):**

| Run name | Bucket |
|---|---|
| `gpt-5.4-mini-low_par_by_par` | small |
| `gemini-3.1-flash-lite-preview-low_par_by_par` | small |

**Local OSS (Данилин baseline):**

| Run name | Bucket | Источник |
|---|---|---|
| `gemma_par_by_par` | local | gemma one-shot перевод |
| `qwen_par_by_par` | local | qwen 27B one-shot перевод |
| `qwen_edited_par_by_par` | local | qwen 27B translate→eval→edit pipeline (симлинк на `qwen_par_by_par/edited_translation.md`) |

## 6. Как отвечаем на RQ

### RQ1

Per (model_family, reasoning=`high`, chunking) считаем mean(criterion) по 549 параграфам. Получаем таблицу 7 (large + small) × 3 (criteria block) × 3 chunking levels.

**Сравнение:** парные тесты within-paragraph (Wilcoxon signed-rank) для каждого критерия между chunking levels внутри одного `(family, reasoning)`. Поправка Holm-Bonferroni на множественные сравнения.

**Эффект-сайз:** mean difference + 95% bootstrap CI (per paragraph).

**Ответ:** «для large-tier `by_K` (K=5 или 10) выше par_by_par на X баллов по accuracy/style/...; для small-tier по_10 ниже par на Y баллов».

### RQ2

Per run считаем aggregated score = mean(median по judges) per criterion. Таблица 32 ранов × 7 критериев. Сводный composite score — взвешенное среднее (веса предложит supervisor).

**Группировка по tier:** mean ± std composite score per tier.

**Контрасты:**

- large-frontier vs small-frontier — есть ли разрыв и какой.
- small-frontier vs local-oss-baseline (qwen_edited) — догоняет ли pipeline Данилы дешевые облачные модели.
- внутри family `-high` vs `-low` (side-question по reasoning).

**Ответ:** «для черновика энциклопедии достаточен ярус Z, разрыв с следующим вверх Δ баллов».

### RQ3 (вторая очередь)

На subsetе из 5 разнотипных переводов (по одному из large-frontier, large-alt, small-frontier, local one-shot, local edited) запускаем все три judge-конфига:

1. large-low профиль (уже посчитан в RQ1/2).
2. small-low профиль: sonnet-4.6-low + gemini-flash-lite-preview-low + gpt-5.4-mini-low.
3. qwen-27B-judge Данилы (через переиспользование старого Stage 03 кода).

**Метрика:** Spearman корреляция между профилями per criterion. Bland-Altman bias plot.

**Ответ:** «qwen-27B можно использовать как proxy для accuracy/factcheck (ρ ≥ X), но не для cultural/style».

## 7. Out of scope

- Прогон по полным 7 томам — только пилот.
- Промпт-инжиниринг (фиксирован).
- `smart_llm_split` chunking — не запускался.
- Тюнинг hyperparameters (temperature, top_p — фиксированы).
- Перевод дополнительных моделей.

## 8. Статус

- 32 перевода готовы под `data/pilot/translating/` (31 файл + 1 симлинк, который создаётся перед запуском Stage 04).
- Stage 04 multi-judge: spec финализирован, имплементация ведётся по 18-task TDD плану.
- Scoring запускается, как только Stage 04 готов; результаты ложатся в `data/pilot/evaluation/<run_name>/`.
- Сводная таблица скоров: `data/pilot/evaluation/scores.json` (см. контракт в [pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md)).
- Excel-таблица команды наполняется из `scores.json`.
