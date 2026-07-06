# Session log — model-comparison эксперимент (сессия eb7d84db, 2026-07-05 → 07-06)

Сводка работы сессии для передачи контекста. **Точка входа для продолжения:**
[docs/superpowers/specs/2026-07-06-finish-model-comparison-runs.md](../../superpowers/specs/2026-07-06-finish-model-comparison-runs.md).

## Что было сделано

### 1. Исправлена устаревшая стратификация (коммит `dfd835c`)
Владелец отказался от «50 сложных / 50 типичных» страт. Выпилены `hardness`/`select_articles`,
доки и Methodology-абзац переписаны на 10 тематических секций, забаннены спека/план 07-03.
Корпус v2 залит в репо: `data/eval/wiki/{titles_v2.txt, selection_v2.json}`, `scripts/select_wiki_corpus.py`.

### 2. Апгрейд раннера (коммиты `7173ee6`, `76353a8`, `a40690f`, `02bc705`, `f7b0497`, `0ac746f`)
`scripts/wiki_eval.py` доведён до полных прогонов: CLI `--model/--provider/--max-judge-calls/--llm-workers/--wikidata-workers`,
параллелизм на уровне статей с глобальным семафором LLM, честный учёт стоимости extraction,
ретраи Wikidata с уважением Retry-After, освобождение слота в backoff, **чекпойнтинг + `--resume`**.
Тесты выросли до 496 зелёных.

### 3. Провайдер-triage (коммит `05dbd54`)
`scripts/probe_providers.py` + `docs/experiments/2026-07-05-model-comparison/triage/`.
Выбор маршрутов: gemini/deepseek → provider-9, gpt-5.5 → provider-8 (override auto ради анти-дрифта),
qwen → provider-8 (чистого маршрута нет — reliability-находка). Дисквалифицирован padded provider-6 (+4 395 скрытых токенов).

### 4. Матрица прогонов (config 111, корпус v2)
| Модель | Run dir | R_doc | Статус |
|---|---|---|---|
| gemini-3.1-flash-lite | `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/` | 0.690 | ✅ готов |
| deepseek-v4-flash | `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z/` | 0.614 | ✅ готов |
| qwen3.7-plus | `reports/terminology/wiki-eval/qwen--qwen3.7-plus--provider-8/111/2026-07-06T09-55-11Z/` | 0.092 | ⚠️ ДЕГРАДИРОВАЛ (80% отказов, не измерение качества) |
| gpt-5.5 | — | — | ❌ заблокирован 429 провайдера |

Инциденты ночи (все дали коммит + тест): Wikidata-429 (Retry-After обрезался), circuit-breaker auto qwen,
429 OpenAI-апстрима gpt-5.5, таймауты deepseek, 2 рестарта контейнера (→ чекпойнтинг), семафор держался в backoff (→ фикс).

### 5. Полная 8-конфигурационная абляция (gemini, sub20)
Каталоги `.../google--...--provider-9/{000..111}/`. Вклады: лемма **+0.322**, фолбэки **+0.145**, алиасы **+0.004**.
Воспроизводит контрольный набор из 91 термина.

### 6. Активация P3 (коммит `a76d9a5`)
Реальный предикат меток, ключ `p3_ex` (без тавтологичного exact_label-пути).
**P_label = 0.526 (gemini) / 0.530 (deepseek)** против P_mention 0.30 — количественное подтверждение неполноты разметки.

### 7. Обнаружена и устранена циркулярность (коммит `9145bc9`)
Владелец заметил на схеме ступень «ru-Wikipedia title → sitelink» — она воспроизводит механизм построения эталона.
Детерминированный реплей: **1.0–1.2 % граунд-предсказаний, эффект 0.5–0.8 п.п. recall**, ранжирование не затронуто.
Чистые числа: gemini 0.684, deepseek 0.609. `use_fallbacks` расщеплён на `use_cirrus`/`use_sitelink`, eval-прогоны с `use_sitelink=False`.

### 8. Отчёт — три версии по правкам владельца
- **v1**: сравнение 2 моделей, инциденты, литература (KG-MT = EMNLP 2024, не ICML).
- **v2**: M3-primary, ярусы recall (Opus-анализ: 34 % шум / 66 % настоящие пропуски терминов), схема пайплайна, без шлюза/цен.
- **v3**: EMNLP-терминология (R_doc/R_span/R_strict, P_mention/P_type/P_label, Gold mentions), RU без точек с запятой,
  EN-секция переписана изолированным Opus + Fable-полировка.

## Ключевые числа (все верифицированы против metrics.json)
- R_doc: gemini 0.690 [0.680–0.700], deepseek 0.614 [0.604–0.625].
- Декомпозиция: coverage 0.763 / 0.632, grounding-accuracy **0.814 / 0.815 (идентична — главный вывод)**.
- Тип (R_doc): named 0.828, lowercase 0.414 (gemini).
- Ярусы: R_all/R_clean/R_term = 0.690 / 0.704 / 0.741 (gemini).
- P_label: 0.526 / 0.530. Clean (sitelink off): 0.684 / 0.609.

## Куда смотреть (файлы)

**Для продолжения:**
- `docs/superpowers/specs/2026-07-06-finish-model-comparison-runs.md` — **спека передачи, читать первой**.
- `docs/experiments/2026-07-05-model-comparison/` — TASK/BUDGET/PLAN/APPROVED/FINDINGS + этот лог + `drafts/`.

**Финальные тексты (git-снимок из scratchpad, в `drafts/`):**
- `drafts/report-ru-v3.md` — финальный RU-отчёт.
- `drafts/paper-section-en-final.md` — **финальная EN-секция статьи (главный артефакт)**.
- `drafts/terminology-spec.md` — биндинг терминологии (обязателен для правок).
- `drafts/recall-tiers-analysis.md`, `drafts/sitelink-contamination.md` — анализы.
- `drafts/g6-pipeline.svg`, `drafts/tier_assignment.json`, `drafts/tier_defs.json`.

**Код:** `scripts/wiki_eval.py` (раннер), `scripts/probe_providers.py` (triage),
`scripts/replay_sitelink_contamination.py` (реплей циркулярности), `src/palimpsest/terminology/grounding/` (G6),
`src/palimpsest/terminology/evaluation/{metrics,report,matching}.py`.

**Данные:** `data/eval/wiki/gt_v2.jsonl` (эталон), `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/`.

**Доставлено владельцу в чат (file_uuid в транскрипте):** `model-comparison-experiment-v3.docx`,
`en-section-final.md`, `g6-pipeline.png/svg`, `evaluation-sections.tex` (устаревшая нотация, перепаковать).

**Артефакты:** §5 с таблицами — `https://claude.ai/code/artifact/f0710899-2edd-4c18-89a4-7982e0b474cb`;
промежуточный отчёт — `https://claude.ai/code/artifact/231866f8-cc53-40f6-b29d-af40ee777993`.

## Осталось (по спеке)
1. Довести qwen (`--resume`), report с `--p3` + чистые sitelink-числа.
2. gpt-5.5 — если маршрут ожил, иначе reliability-заметка.
3. Вписать P_label + qwen вместо плейсхолдеров → docx v4 + перепаковать .tex + обновить артефакт → верификация → доставка.
4. doc-parity (`docs/stages/wiki-eval.md § Status`), LESSONS, сброс ACTIVE.

Спенд эксперимента на текущий момент ~$4 из капа $60.
