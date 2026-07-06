# Спека: довести прогоны model-comparison и финализировать отчёт

Дата: 2026-07-06. Автор: оркестратор (сессия eb7d84db). **Назначение: передача в новую сессию.**
Ветка: `claude/ner-wikidata-status-check-ky2bp8` (единственная рабочая, HEAD на момент записи `100864f`).
Родитель: [2026-07-05-model-comparison-wiki-eval.md](2026-07-05-model-comparison-wiki-eval.md).
Операционные доки эксперимента: [docs/experiments/2026-07-05-model-comparison/](../../experiments/2026-07-05-model-comparison/).

## Цель новой сессии

Довести матрицу до 3 (в идеале 4) моделей и выпустить **финальную версию 4** отчёта (RU + EN-секция статьи + .tex + артефакт) с реальными числами вместо оставшихся плейсхолдеров. Никаких новых экспериментов сверх этого списка. Владелец сам донесёт данные новых моделей позже — наша задача закрыть текущие.

## Что уже сделано (не переделывать)

- **Корпус v2**: `data/eval/wiki/gt_v2.jsonl` (100 статей, 7 959 эталонных упоминаний, 3 868 QID). Подмножество абляции `data/eval/wiki/gt_v2_sub20.jsonl` (20 статей, 1 443).
- **Два полных прогона** (config 111), с активированным P3:
  - gemini-3.1-flash-lite: `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/`
  - deepseek-v4-flash: `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z/`
- **Полная 8-конфигурационная абляция** лестницы (gemini, sub20): каталоги `.../google--...--provider-9/{000..111}/`.
- **Код** (всё в ветке, тесты 496 зелёных): чекпойнтинг + `--resume`, устойчивость к API-сбоям (ретраи с Retry-After, слот вне backoff), расщепление `use_fallbacks` → `use_cirrus`/`use_sitelink`, активный P3 (`report --p3`, ключ `p3_ex`), Wikidata-счётчики в meta.
- **Готовые метрики** (числа для отчёта, все верифицированы адверсариально против metrics.json):

| Метрика | gemini | deepseek |
|---|---|---|
| R_doc (M3) | 0.690 [0.680–0.700] | 0.614 [0.604–0.625] |
| R_span / R_strict | 0.630 / 0.610 | 0.524 / 0.509 |
| P_mention / P_type | 0.300 / 0.451 | 0.305 / 0.458 |
| **P_label (p3_ex)** | **0.526** | **0.530** |
| Coverage × grounding-acc | 0.763 × 0.814 | 0.632 × 0.815 |
| R_all / R_clean / R_term | 0.690 / 0.704 / 0.741 | 0.614 / 0.627 / 0.663 |
| Clean (sitelink off) R_doc | 0.684 | 0.609 |

- **Документы** (финальные тексты в scratchpad — см. § Файлы): RU-отчёт v3 (0 точек с запятой, EMNLP-терминология), EN-секция v-final (Opus + Fable-полировка), схема пайплайна PNG/SVG. Плейсхолдеры в них: строка qwen и числа P_label (последние теперь известны — вписать).

## Задача 1 — довести qwen3.7-plus (частичный чекпойнт)

Прогон был жив на 87/100, закоммичен как частичный чекпойнт (`100864f`). Если контейнер новый — процесс убит, но `pred.partial.jsonl` (87 статей) сохранён.

1. **Проверить**, не завершился ли прогон в старом контейнере: `ls reports/terminology/wiki-eval/qwen--qwen3.7-plus--provider-8/111/2026-07-06T09-55-11Z/` — если есть `pred.jsonl` + `meta.json`, значит готов, переходить к report.
2. **Иначе — возобновить** (маршрут qwen@provider-8 был рабочим 3/3; проверить пробой перед запуском, при 429/503 подождать):
   ```
   PYTHONPATH=src uv run python scripts/wiki_eval.py run \
     --gt data/eval/wiki/gt_v2.jsonl --config 111 \
     --model qwen/qwen3.7-plus --provider provider-8 \
     --max-usd 12 --max-judge-calls 30000 --llm-workers 4 --article-workers 10 \
     --wikidata-workers 2 --wikidata-cache reports/terminology/wikidata_cache.qwen.jsonl \
     --resume reports/terminology/wiki-eval/qwen--qwen3.7-plus--provider-8/111/2026-07-06T09-55-11Z/
   ```
   Фоном (harness-tracked, не через субагента — супервизия через субагента дважды теряла процесс этой ночью). Осталось ~13 статей, ~20–30 мин.
3. **Report с P3 + чистые sitelink-числа**:
   ```
   PYTHONPATH=src uv run python scripts/wiki_eval.py report --p3 \
     --gt data/eval/wiki/gt_v2.jsonl --pred <run_dir>
   ```
   Затем чистые (без sitelink) числа реплеем: `scratchpad/sitelink_contamination.py` (переиспользуемый, дать ему кэш `wikidata_cache.qwen.jsonl`).
4. Закоммитить run dir; вписать строку qwen во все документы и таблицы.

## Задача 2 — gpt-5.5 (опционально, заблокирован провайдером)

gpt-5.5 недоступен с ~23:20 UTC 05-07 (429 на provider-8 и auto, OpenAI-апстрим). Владелец капнул «одна последняя модель» — ею стал qwen. gpt-5.5 брать **только если** маршрут ожил (пробой `provider-8`/`auto` тремя вызовами) и владелец не против. Если недоступен — задокументировать как reliability-находку (модель без стабильного маршрута через шлюз в окне эксперимента), строку оставить «— unavailable —». Запуск идентичен qwen, но `--provider provider-8`, свой `--wikidata-cache ...gpt55.jsonl`.

## Задача 3 — финальная сборка отчёта (версия 4)

1. **Вписать реальные числа** вместо плейсхолдеров:
   - P_label: gemini 0.526, deepseek 0.530 (в RU § 3.7 и EN §6 `\placeholder{P_label values}`).
   - Строка qwen в Table 1 и по секциям (из его report).
   - Опционально колонка «clean (sitelink off)» рядом с headline — числа gemini 0.684 / deepseek 0.609 / qwen — уже есть в `scratchpad/sitelink-contamination.md`.
2. **Пересобрать docx** тем же inline-скриптом python-docx (паттерн — в истории сессии; рендерит `##/###` заголовки, `**bold**`, `|таблицы|` → Word-таблицы, вставляет `g6-pipeline.png`). Источники: `scratchpad/doc-part1-ru.md` + `scratchpad/en-section-final.md`. Выход `model-comparison-experiment-v4.docx`.
3. **Пересобрать .tex**: текущий `scratchpad/evaluation-sections.tex` — от старой версии (M1/M2 нотация). Перепаковать из `en-section-final.md` в acmart (booktabs, ≤6 стр., BibTeX-блок уже есть — сверить ключи). Это **главный академический артефакт** — качество EN важнее всего (указание владельца).
4. **Обновить артефакт** §5 (URL `https://claude.ai/code/artifact/f0710899-...`) и `docs/reports/2026-07-06-model-comparison.html`.
5. **Верификация**: адверсариальный агент (модель ≥ Sonnet) сверяет каждое число финальных документов против `metrics.json`/`sitelink_contamination.json`/`tier_assignment.json`. Обязательно перед доставкой (в этой сессии верификатор поймал реальную ошибку CI 0.534→0.535).
6. **Доставка**: SendUserFile (docx + .tex + en-section-final.md) + республикация артефакта.
7. **doc-parity + LESSONS**: обновить `docs/stages/wiki-eval.md § Status`, дописать `docs/experiments/LESSONS.md` (уроки ночи: canary перед матрицей окупился; супервизия live-процессов — прямым тредом, не субагентом; чекпойнтинг обязателен для длинных прогонов; annotation-mechanism leakage как ревью-аспект), сбросить `docs/experiments/ACTIVE`.

## Ключевые файлы (scratchpad `/tmp/claude-0/-home-user-translation-demo/eb7d84db-f5ab-5bf8-9951-e48d0dc8c3ae/scratchpad/`)

Scratchpad **не переживёт новый контейнер**. Всё критичное для финализации, чего нет в git, нужно либо перегенерировать, либо владелец приложит. Что там есть:
- `doc-part1-ru.md` — финальный RU-отчёт v3.
- `en-section-final.md` — финальная EN-секция (Opus+Fable). **Продублирована в git-доставке** (file_uuid в истории), но лучше владельцу приложить.
- `terminology-spec.md` — **биндинг терминологии** (R_doc/R_span/R_strict, P_mention/P_type/P_label, R_all/R_clean/R_term, Gold mentions). Обязателен для любой правки текста.
- `g6-pipeline.png` / `.svg` — схема (рис. 1).
- `tier_assignment.json` / `tier_defs.json` — ярусы (детерминированные, {qid: 0/1/2}).
- `sitelink_contamination.py` + `sitelink-contamination.json` — реплей циркулярности (переиспользуем для qwen).
- `numbers_pack.json` — сводка метрик gemini/deepseek (source of truth для сверки).
- Артефакт-исходники: `part3.md`, `part3_body.html`, `gen_part3.py` (§5 с таблицами).

Если scratchpad пуст — регенерировать из git: тексты придётся восстановить из истории сессии (транскрипт `/root/.claude/projects/.../eb7d84db-....jsonl`) или пересоздать. **Рекомендация: в начале новой сессии сразу перегенерировать `sitelink_contamination.py` и tier-скрипты из транскрипта в git-tracked `scripts/`, чтобы не зависеть от scratchpad.**

## Оркестрация (инварианты владельца)

- **Fable/оркестратор только оркестрирует.** Вся реализация — субагенты с явной моделью, имя агента начинается с модели (Opus/Sonnet/Haiku). Главный риск — поставить оркестратор на реализацию и сжечь лимит.
- Код по готовому плану → Sonnet. Анализ/research без плана → Opus. Recon/mechanical → Haiku.
- **Live-процессы супервизировать прямым главным тредом** (harness-tracked background bash + `ps`/лог), НЕ через субагента: субагенты этой ночью трижды «проспали» нотификации и теряли процессы.
- Коммиты атомарные, Conventional Commits, без AI-подписей. Doc-parity в том же коммите.
- Все owner-facing тексты RU, документация EN, таблицы EN. Отчёты — артефактом (cloud), не bare-файлом.
- Периодические чек-ины через `send_later` (claude-code-remote MCP) на случай пропущенных нотификаций.

## Критерии готовности

1. qwen завершён (или задокументирован дропаут), его строка во всех таблицах; gpt-5.5 закрыт (числа или reliability-заметка).
2. Плейсхолдеры P_label и qwen заменены реальными числами; спенд ≤ $60 (сейчас ~$4).
3. docx v4 + .tex (перепакован) + артефакт обновлены и доставлены; числа прошли адверсариальную верификацию.
4. doc-parity, LESSONS дописан, ACTIVE сброшен.
