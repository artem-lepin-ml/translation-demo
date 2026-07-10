# Handoff: сессия «текст статьи» (2026-07-10)

> Владелец: Artem. Это стартовое сообщение для НОВОЙ сессии, которая пишет
> текст статьи EMNLP 2026 System Demonstration, пока сессия-оркестратор
> `claude/ner-translation-config-b0ozsc` исполняет спеку эксперимента.
> Язык общения с владельцем — русский; текст статьи — академический
> английский; чистовые фрагменты пишет только Fable (не Sonnet).

## Разделение зон между сессиями (не пересекаться!)

**ЭТА сессия (текст статьи) пишет всё, КРОМЕ терминологического
эксперимента:** Introduction (полировка), §2 System — Translation,
LLM-as-a-judge Evaluation, Live Demo и Interactive Use Cases, §3 Evaluation
Setup — абзацы BOUQuET и RuWH, Hyperparameter Details, §4 Results —
LLM-as-a-judge и Refinement (с Данилом), Conclusion, Abstract, Limitations.

**ДРУГАЯ сессия (оркестратор эксперимента) владеет:** подсекцией
\datasetWikipediaName{} (WikiHist) в Evaluation Data, параграфом
Terminology Recognition в Evaluation Metrics (sec:eval-metrics), Results →
Terminology Recognition (Table C + findings), обоими промптами
(NER + disambiguation judge) в appendix, appendix
app:wiki-corpus. Эти места НЕ трогать — числа и тексты приедут после
v2-прогонов.

## Где что лежит

| Что | Где |
|---|---|
| Снапшот Overleaf-текса (актуальный, 2026-07-10) | `docs/paper/snapshots/2026-07-10/acl_latex-2026-07-10.tex` |
| PDF-рендер того же состояния | `docs/paper/snapshots/2026-07-10/2026-EMNLP-History-Demo-2026-07-10.pdf` |
| Старый большой отчёт по эксперименту (числа НЕ доверять, смысл — да) | `docs/paper/snapshots/2026-07-10/model-comparison-experiment-v3_1.docx` |
| Готовые фрагменты (2 варианта в каждом файле: активный + закомментированный) | `docs/paper/sections/*.tex` |
| Live Demo фрагмент (готов, ждёт выбора варианта) | `docs/paper/sections/live-demo.tex` |
| Table A (судьи BOUQUET, 4/8 строк заполнено) | `docs/paper/table-a-judges.tex`; данные `reports/bouquet/judges/*/stats.json`, сводка `reports/bouquet/judges/summary.md` |
| Судейские прогоны — отчёты с протоколами | `docs/reports/python-pro-judge-run-*.md` |
| Состояние статьи (ВНИМАНИЕ: дрейфует, Table C нарратив устарел — верить tex-файлам и спеке) | `docs/paper/paper-state.md` |
| Спека эксперимента (контекст, что изменится в числах) | `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` |
| Домашний язык проекта | `CONTEXT.md`, `CLAUDE.md` |

## Правила письма (выжимка рекомендаций владельца из сессий 2026-07-08…10)

1. Лаконичный академический английский, как пишет native speaker. Без
   em-тире, без точек с запятой, без оверклеймов («extreme», «powerful»,
   «seamless», «high-stakes» — вычёркивать). Present tense «we».
2. Только факты, подтверждённые файлами репо. Числа — из закоммиченных
   json/отчётов, никогда из памяти.
3. Технические детали воспроизводимости — в appendix, не в основной текст.
4. Списки предметов — в скобках внутри предложения. Без тавтологий
   («Wikipedia is a corpus of Wikipedia articles»). Не выпячивать
   «Russian» — это limitation, а не фича.
5. Для каждого датасета: для каких evaluation он используется и почему.
6. Статистику датасетов не дублировать в прозе — одно общее предложение со
   ссылкой на Table 1 после всех трёх датасетов.
7. Caption'ы таблиц короткие: определения живут в тексте секции метрик, не
   в caption. В главных таблицах — без CI, без даггеров, без дисклеймеров.
8. Каждый фрагмент — в ДВУХ вариантах (основной + заметно другой
   креативный), второй закомментирован в том же tex-файле, чтобы
   руководитель мог выбрать.
9. Дубликаты фактов запрещены (single source of truth): по конфликту
   позднее побеждает раннее, документация побеждает спеки.
10. UI-копирайт англоязычный; в тексте статьи термины «Source» /
    «Translation» (не «original», не «target text»).
11. Макросы текса: `\systemname{}`, `\datasetWikipediaName{}` (WikiHist),
    `\datasetEncyclopediaName{}` (RuWH), `\moduleTranslation` и т.д. —
    использовать их, не сырые имена.
12. Перед любым дизайном/правкой — открыть существующий код/текст и
    назвать конкретную находку (Ground before you design).

## Что уже сделано и ждёт владельца

- `live-demo.tex` (Functionality + Implementation, TipTap footnote) — 2
  варианта, выбрать.
- `appendix-wiki-corpus.tex` — готов, вставить после `\appendix`.
- Цитаты для двух «(TODO)»: WikiHist intro —
  `semenov-etal-2025-findings` (+ `conia-etal-2025-semeval`, но его ключ
  есть только в закомментированном cite — проверить bib на Overleaf); RuWH
  intro — `kocmi-etal-2025-findings` + `conia-etal-2024-towards`. Оба
  первых предложения этих абзацев начинаются одинаковыми девятью словами —
  переформулировать одно из двух.
- В tex дважды указана ссылка `Section~\ref{sec:eval-metrics}` и дважды
  `Appendix~\ref{app:wiki-corpus}` — labels ещё не расставлены (список
  integration-шагов в шапках наших tex-файлов).

## Известные шероховатости соавторского текста (кандидаты на полировку)

- RuWH-абзац: «presents extreme challenges», «high-stakes domain» —
  смягчить по правилу 1.
- «Refiment Improve» — опечатка в заголовке подсекции Results.
- Данные Table 1 (WikiHist: 100 статей / 160 836 слов / 2 553 абзаца / 63
  слова средняя длина) — уже сверены, верны.
