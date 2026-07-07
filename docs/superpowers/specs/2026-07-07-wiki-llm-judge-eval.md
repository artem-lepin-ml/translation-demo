# Спека: LLM-as-a-judge + refinement eval на 100 статьях Википедии (+ BOUQUET-параллель)

Дата: 2026-07-07. Статус: **черновик на ревью владельцу** — есть открытые вопросы (§ 11), исполнение позже.
Контекст: секция evaluation статьи EMNLP 2026 (industrial track). Третий датасет оценки judge+refinement:
том энциклопедии (Данил), BOUQUET (Данил, частично), **100 статей ru-Википедии (эта спека)**.
Связано: [docs/stages/wiki-eval.md](../../stages/wiki-eval.md) (тот же корпус, NER+grounding),
[2026-07-05-model-comparison-wiki-eval.md](2026-07-05-model-comparison-wiki-eval.md) (паттерн многомодельного прогона).

## 0. Grounding — что уже есть (проверено 2026-07-07)

- **Корпус чист и совпадает с соседней оценкой.** Аудит всех 100 статей ([отчёт](../../reports/python-pro-wiki-corpus-cleanliness-check.md)):
  100/100 файлов находятся по конвенции `wiki_gt._safe_filename`, 100/100 `tokenize.tokens(flatten(html)) == gt_v2.tokens`
  (токен-в-токен тот же текст, что в grounding-eval), **ноль** следов HTML/вики-разметки по 10 категориям паттернов.
  Контентные флаги: 8 статей содержат инлайн-плашку `[источник не указан N дней]` (14 вхождений — реальный текст статьи);
  1 статья — короткий стаб 854 символа («Калинга (государство)»).
  Итого: **2 553 непустых абзаца, 160 836 токенов; длина абзаца mean 63 / p50 54 / p90 123 / max 392 токена**.
- **Промпты и цикл refinement уже в этом репо**: judge-рубрики 1–10 [prompts/scoring/accuracy.md](../../../prompts/scoring/accuracy.md),
  [fluency.md](../../../prompts/scoring/fluency.md), [style.md](../../../prompts/scoring/style.md) (+ terminology.md);
  корректор [prompts/correction/system.md](../../../prompts/correction/system.md) (вход: Source + Translation + issues
  `{source fragment, problematic fragment, explanation, suggestion}`, выход: исправленный перевод);
  формат issues уже реализован в [src/palimpsest/webapp/judge.py](../../../src/palimpsest/webapp/judge.py);
  первичный перевод — [prompts/translator/default.md](../../../prompts/translator/default.md) и паттерн rolling-контекста
  в [src/palimpsest/pipeline/draft.py](../../../src/palimpsest/pipeline/draft.py)/`runner.py`.
  `LLMClient` ([src/palimpsest/llm/client.py](../../../src/palimpsest/llm/client.py)) принимает произвольный `base_url` —
  локальный vLLM OpenAI-endpoint подключается без правок клиента.
- **Раннер-паттерны переиспользуем из wiki-eval**: BudgetGuard (extract+judge), чекпоинтинг `pred.partial.jsonl`/`--resume`,
  `meta.json` с полным учётом спенда, схема директорий `<model-slug>/<config>/<run_id>/` ([scripts/wiki_eval.py](../../../scripts/wiki_eval.py)).
- **Сетап Данила** (скриншот + чат, код в GitLab `ru2en-enciclopedia-translation@artem`, `scripts/03_translation_scoring.py`):
  BOUQUET ru2en по абзацам; системы TranslateGemma / +Refined / Qwen3.6-27B / +Refined; метрики Accuracy/Fluency/Style
  (LLM, наблюдаемые 9.5–9.9 из 10), MetricX w/ ref 2.41–2.70, MetricX QE 3.55–3.79, COMET w/o ref 0.72–0.74;
  Спирмен judge×авто-метрики околонулевой. **Блокер: из облачной сессии GitLab недоступен**
  (нет ssh-клиента/ключей/токена; HTTPS API отвечает 404 на приватный проект) — точные промпты/скрипты Данила
  не сверены, пайплайн реконструирован по активам этого репо. Нужен read-only PAT или выгрузка ветки (§ 11, В1).

## 1. Цель

Дать для статьи третий eval-датасет компонента «LLM-as-a-judge + refinement» в **безреференсном** сеттинге:
на 100 статьях ru-Википедии для 4 моделей измерить качество перевода до/после refinement тремя LLM-метриками
(Accuracy / Fluency / Style, 1–10) и двумя автоматическими QE-метриками (MetricX-24-QE, CometKiwi-22),
посчитать согласованность judge×метрики (Спирмен + paired-анализ), и отдать:
(а) две таблицы уровня статьи (качество систем; корреляции), (б) per-paragraph JSON
(source, translation, 5 метрик) в формате хэндоффа Данила/Андрея, (в) case study / error analysis,
(г) прогон тех же 4 моделей на BOUQUET-абзацах для пересечения таблиц с Данилом («побольше пересечения по моделям»).

## 2. Данные

| Датасет | Единица | N | Референс EN | Роль |
|---|---|---|---|---|
| wiki v2 (наш) | абзац (`tokenize.flatten`, split `"\n"`) | 2 553 (100 статей) | **нет** → только QE-режимы | основной, новый вклад |
| BOUQUET `paragraph_level` ru→en | абзац (3–6 предложений) | 320 (dev 120 + test 200) | **есть** (`tgt_text`) | параллель с Данилом; + ref-based метрики |

- Wiki-абзацы берутся ровно из того же экстракта, что grounding-eval (см. § 0) — единый corpus-claim в статье.
- BOUQUET: HF `facebook/bouquet` (gated, автоодобрение, CC-BY-4.0, eval-only). Русский — один из 8 исходных языков.
  Загрузка: `load_dataset("facebook/bouquet", "paragraph_level", split=...)` + фильтр `src_lang=="rus_Cyrl" and tgt_lang=="eng_Latn"`.
- Плашки `[источник не указан…]` (8 статей) **оставляем как есть** (это текст статьи; отражаем в limitations).
  Решение зеркалит owner-decision 2026-07-05 «не курировать пост-хок».
- Масштаб прогона: **вариант A (дефолт) — все 2 553 абзаца**; вариант B — стратифицированная подвыборка
  ~10 абзацев/статью (≈1 000). Решает владелец (§ 11, В4) по бюджету judge-вызовов (§ 8).

## 3. Модели (ID верифицированы онлайн 2026-07-07)

| Система | HF/API ID | Размер | Сервинг | Примечания |
|---|---|---|---|---|
| TranslateGemma 27B | `google/translategemma-27b-it` (gated, manual) | 27.4B bf16 ≈ 55 GB | vLLM: **репак `Infomaniak-AI/vllm-translategemma-27b-it`** (офиц. vLLM-recipes), 1×A100 | ⚠️ контекст **2K токенов всего**; шаблон принимает ТОЛЬКО задачу перевода (`source/target_lang_code`) — correction-промпт не поддерживается (§ 4, § 11 В3) |
| Qwen 4B | `Qwen/Qwen3-4B-Instruct-2507` (рекоменд.) или `Qwen/Qwen3.5-4B` | 4.0B / 4.7B | vLLM ≥0.8.5 / **nightly** для 3.5, 1×A100 | 3.5-4B — thinking по умолчанию (`enable_thinking:false`) и nightly-vLLM риск → дефолт 2507 (§ 11 В5) |
| Qwen3.6-27B | `Qwen/Qwen3.6-27B` (Apache-2.0) | 27.8B bf16 ≈ 56 GB | vLLM ≥0.19, TP=2, `--reasoning-parser qwen3` | hybrid-thinking: в запросах `chat_template_kwargs={"enable_thinking": false}`; sampling non-thinking: T=0.7, top_p=0.8, top_k=20, presence=1.5 |
| deepseek-v4-flash | `deepseek/deepseek-v4-flash` через CloseRouter | 284B MoE (13B act) | **только API** ($0.09/$0.18 за M) | слаг подтверждён по OpenRouter; маршрут пинить по triage-методике model-comparison |

GPU-раскладка (4×A100 80GB): TranslateGemma (GPU0) + Qwen-4B (GPU1) + Qwen3.6-27B (GPU2-3, TP=2) — все три
одновременно; deepseek через CloseRouter параллельно. Метрики (MetricX/COMET) гоняются после освобождения GPU
или на GPU1 рядом с 4B-моделью (XXL-bf16 ≈ 26 GB).

## 4. Пайплайн прогона (per model × per paragraph)

1. **Translate** — независимый перевод абзаца (без rolling-контекста: паритет с BOUQUET-сетапом Данила и
   независимость сэмплов для корреляций; rolling-вариант — отдельная абляция, вне скоупа). Промпт:
   для TranslateGemma — её нативный шаблон (`ru`→`en`); для остальных — [prompts/translator/default.md](../../../prompts/translator/default.md).
   Sampling: greedy/T≈0 для TG (по model card), рекомендованные non-thinking параметры для Qwen, T=0.3 для deepseek (как в демо).
2. **Judge (initial)** — фиксированный judge-модель J (единый для всех систем; выбор — § 11 В2) оценивает
   абзац тремя промптами [prompts/scoring/](../../../prompts/scoring/) → скоры 1–10 + структурированные issues
   (формат webapp judge: `{sourceFragment, targetFragment, explanation, suggestion, severity}`).
3. **Refine** — [prompts/correction/system.md](../../../prompts/correction/system.md): Source + Translation + issues → исправленный перевод.
   Исполнитель-рефайнер: **та же система, что переводила** (self-refine, паритет с «Refined» Данила) — кроме
   TranslateGemma, которая структурно не принимает correction-промпт (§ 11 В3: кто рефайнит TG у Данила?).
   Если issues пусты — refined := initial (запись помечается `refine_skipped`).
4. **Judge (refined)** — те же 3 промпта тем же J.
5. **QE-метрики** — на initial И refined: MetricX-24 (`google/metricx-24-hybrid-xxl-v2p6-bfloat16`, `--qe`,
   `--max_input_length 1536`, batch ≥ числа видимых GPU — известный баг деления батча) и CometKiwi
   (`Unbabel/wmt22-cometkiwi-da`, gated CC-BY-NC-SA). На BOUQUET дополнительно ref-based:
   MetricX-24 без `--qe` + `Unbabel/wmt22-comet-da` (Apache-2.0).
6. **Длинные абзацы — обязательный гард.** Оба скорера **молча** обрезают вход (MetricX: конкатенация
   source+candidate(+reference) до 1536 mT5-токенов; COMET: 512 XLM-R-токенов на сэмпл). Верхний дециль
   wiki-абзацев (p90=123 слова) в COMET-окно не влезает. Правило: пре-токенизация обоими токенизаторами;
   абзац сверх лимита → предложенческий сплит (razdel/nltk EN) с длинно-взвешенным средним по кускам;
   доля таких абзацев логируется в `meta.json` и раскрывается в статье. Никогда не поднимать
   `--max_input_length` выше обученного (README-варнинг MetricX).

Судья J вызывается через CloseRouter с пином маршрута (методика triage из model-comparison), `temperature=0`,
строгий JSON-выход с одним corrective re-ask (паттерн wiki-eval). Bias-note: J не должен совпадать ни с одной
оцениваемой системой (self-preference); если владелец выберет deepseek-v4-flash как J — deepseek-строки таблицы
помечаются в статье как self-judged (§ 11 В2).

## 5. Метрики, корреляции и анализ (по методологической записке)

- **Таблица 1 (качество):** 4 системы × {initial, refined} × {Accuracy, Fluency, Style, MetricX-QE↓, CometKiwi↑}
  (+ для BOUQUET колонки MetricX-ref↓, COMET-ref↑). Средние + bootstrap 95% CI (ресэмплинг по абзацам).
- **Таблица 2 (согласованность):** Спирмен 3 judge-оси × 2 QE-метрики × 2 датасета (12 ячеек, как у Данила), с:
  (а) знаком MetricX, явно инвертированным (raw MetricX должен коррелировать **отрицательно**);
  (б) tie-rate / доля модального значения judge на ячейку; (в) отдельно pooled и within-system
  (де-мин по системе; защита от парадокса Симпсона).
- **Paired-анализ (главная added value):** Δjudge vs Δmetric на refinement (та же система, тот же абзац):
  sign-agreement (3×3 win/tie/loss), Kendall tau-b по дельтам, bootstrap CI по абзацам. При ceiling-эффекте judge
  (у Данила 80%+ масс на 9–10) потолок |ρ| ≈ √(3p(1-p)) ≈ 0.5–0.7 даже при идеальном согласии — околонулевые
  Спирмены ожидаемы теоретически; в статье подаём это как объяснение, а не оправдание.
- System-level корреляция (4 системы) — только описательно: n=4 не достигает значимости в принципе (min p=2/24≈0.083).
- Гистограммы распределений judge-скоров и метрик — в отчёт и приложение статьи.
- Кейс-стади по образцу FactOWL: таблица разобранных вручную расхождений judge×метрика с колонкой «доказательство»
  (цитата source/translation), 8–12 строк; + примеры удачного/неудачного refinement.

## 6. Реализация в репо

- Новый модуль **`src/palimpsest/evaluation/`** (stage-конвенция «один stage = один модуль»):
  `translate.py` (обёртки промптов систем), `judge.py` (реюз/адаптация webapp-judge под 3 рубрики + issues),
  `refine.py` (correction-вызов), `qe.py` (подготовка JSONL для MetricX/COMET + sentence-split гард),
  `stats.py` (корреляции/paired-анализ; scipy).
- CLI **`scripts/translation_eval.py`**: `translate` / `judge` / `refine` / `score-qe` / `report` — раздельные
  идемпотентные фазы с чекпоинтом на фазу (паттерн wiki-eval: partial.jsonl + `--resume`, `meta.json`,
  BudgetGuard на judge/refine-вызовы, `model_slug`-директории `reports/translation-eval/<slug>/<run_id>/`).
- Выходной per-paragraph JSONL (формат хэндоффа Данила/Андрея): `{article, par_idx, source, translation_initial,
  translation_refined, scores: {accuracy, fluency, style} × {initial, refined}, metricx_qe × 2, cometkiwi × 2,
  issues[], refine_skipped, judge_model, provider, usage}`.
- MetricX/COMET — не вендорим: раздельный venv на A100-ноде (у MetricX пины 2023 года — `transformers==4.30.2`,
  Python 3.10; конфликтует с vLLM-окружением) + git-clone `google-research/metricx`. В репо — только раннер-скрипт
  и полный runbook в `docs/stages/translation-eval.md` (doc-parity в том же коммите, Hard Invariant 2).
- Доступы (чек-лист перед прогоном): HF-логин + gates: `google/translategemma-27b-it` (manual — запросить заранее),
  `facebook/bouquet`, `Unbabel/wmt22-cometkiwi-da`; `OPENROUTER_API_KEY` (CloseRouter) на ноде.

## 7. Оценка объёма (вариант A: полный корпус, 2 553 ¶)

| Фаза | Вызовов | Где | Оценка |
|---|---|---|---|
| Translate | 2 553 × 4 | 3 локально + deepseek API | локально часы; deepseek ≈ $1–2 |
| Judge initial + refined | 2 553 × 4 × 2 × 3 ≈ **61 к** | CloseRouter (J) | при ~2k in/0.3k out на вызов ≈ 130M in / 20M out ток. → gemini-flash-lite-класс ≈ $15–25; frontier-класс (0.30/0.30) ≈ $45–60 |
| Refine | 2 553 × 4 | 3 локально + deepseek API | локально часы; deepseek ≈ $1–2 |
| MetricX-QE + CometKiwi | (2 553×4×2) × 2 ≈ 41 к скорингов | локально (1×A100) | GPU-часы, $0 |
| BOUQUET (всё то же на 320 ¶) | ≈ 13 к judge-вызовов + локальный прогон | — | ≈ +15% к бюджету |

Вариант B (~1 000 ¶) делит judge-бюджет на ≈2.5. Жёсткий кап по образцу model-comparison: `--max-usd` на прогон,
итоговый кап эксперимента задаёт владелец (§ 11 В6). Тайминг: 3 дня на A100 достаточно —
критический путь judge-вызовы через CloseRouter (~4 конкурентных, ≈61 к вызовов ≈ 30–40 ч при 2 с/вызов →
нужно поднять конкурентность judge до 8–12 с отдельным семафором, CloseRouter это выдерживал на triage).

## 8. Статья (часть 3–4 по структуре синка)

- Data statistics таблица: 3 датасета (том — числа Данила; BOUQUET — 320 ¶; wiki — 100 статей / 2 553 ¶ /
  160 836 токенов / mean 63); зеркалит задачу Данила «статистика по пилотным главам».
- Заголовки-выводы жирным (стиль FactOWL «bold claim as heading»); «—» для непрогнанных ячеек, не пропуск строки;
  промпты judge/correction — в приложение; judge-модель и параметры — раскрыты явно.
- Методологический абзац EN для секции evaluation пишется при исполнении (паттерн wiki-eval `methodology_draft()` — verbatim).

## 9. Риски

- **Несопоставимость с числами Данила**, если его judge-модель/промпты отличаются от наших реконструированных —
  снимается только доступом к GitLab-коду (В1) или фиксацией судьи вместе с ним (В2). До этого таблицы Данила и наши
  публикуются как разные сетапы одного компонента.
- TranslateGemma 2K-контекст: max wiki-абзац 392 слова ≈ 600–800 ток + шаблон — влезает, но проверяем пре-токенизацией; refinement для TG — открыт (В3).
- Qwen3.6-27B thinking-протечки в перевод → строгий `enable_thinking:false` + regex-страховка на `<think>`.
- CloseRouter надёжность ~90%/маршрут → resilient-ретраи 6×(1..60с) + пин маршрута + `FailureTracker` (паттерны wiki-eval уже написаны).
- Gated-модели: TranslateGemma — manual approval, может занять время → запросить доступ сразу после утверждения спеки.
- Judge-двойная роль (скоринг и issues для refinement) создаёт circular-flavor: judge оценивает то, что сам же
  правил через issues. Мера: раскрытие в limitations + QE-метрики как независимый контроль дельты refinement.

## 10. Критерии успеха

1. Per-paragraph JSONL по 4 системам × 2 стадиям на wiki-корпусе (+BOUQUET), с meta.json и полным учётом спенда.
2. Таблицы 1–2 + paired-анализ + гистограммы; числа воспроизводимы `report`-фазой оффлайн.
3. Доля обрезанных/сплитнутых абзацев в метриках задокументирована; ни одного молчаливого трима.
4. Кейс-стади (8–12 разобранных строк) готово для статьи.
5. Спенд ≤ капа владельца; ни один прогон не убит молча (stopped_reason в meta.json).

## 11. Открытые вопросы владельцу

- **В1 (блокер сверки).** GitLab: дать read-only PAT / выгрузить ветку `artem` (или хотя бы
  `scripts/03_translation_scoring.py` + промпты + скрипт корреляций) — иначе паритет с Данилом остаётся реконструкцией.
- **В2 (ключевое).** Judge-модель J: (а) gemini-3.1-flash-lite (дёшево, уже пинован маршрут), (б) deepseek-v4-flash
  (но он же — оцениваемая система → self-judge bias), (в) frontier-модель (какая — «обсудим после»)?
  Дополнительно: J должен совпадать с судьёй Данила для согласованных таблиц — какой судья у него?
- **В3.** Кто делает refinement для TranslateGemma (она не принимает correction-промпт): у Данила в BOUQUET-таблице
  «Translate Gemma Refined» — чем рефайнилось? Наш дефолт-предложение: рефайнер = Qwen3.6-27B для TG-строки
  (помечается в таблице), либо повторить сетап Данила после В1.
- **В4.** Масштаб wiki-прогона: полный (2 553 ¶) или подвыборка (~1 000 ¶, 10/статью)? Дефолт-рекомендация: полный —
  корреляциям нужен n (CI ±0.1 при ρ≈0.2 требует ~380 ¶ уже на ячейку, а paired-анализ выигрывает от объёма).
- **В5.** «qwen 4B» = `Qwen3-4B-Instruct-2507` (стабильный, дефолт) или `Qwen3.5-4B` (новее, но nightly-vLLM + thinking)?
- **В6.** Кап бюджета на эксперимент (CloseRouter): предложение $40 при judge=flash-lite-классе, $80 при frontier-J.
- **В7.** BOUQUET: гоним все 4 системы обеими стадиями (рекомендация — да, для пересечения с Данилом), или только
  недостающие qwen-4B и deepseek?
- **В8.** MetricX-вариант: XXL-bf16 (лучшая корреляция, ~26 GB, дольше) или XL (быстрее)? Дефолт: XXL-bf16 — прогон
  локальный и бесплатный, качество метрики важнее скорости.
