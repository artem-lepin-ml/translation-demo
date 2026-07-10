# Handoff: параллельная работа двух сессий — 2026-07-10

Эта сессия (Fable, оркестратор): чистка разметки WikiHist + NER-метрики + материалы статьи.
Вторая сессия (владелец): disambiguation + более качественный retrieval из Wikidata.

## Ветки
- Эта сессия коммитит ТОЛЬКО в `claude/ner-translation-config-b0ozsc`. Не коммитить в неё из второй сессии — два пишущих процесса на одной ветке дадут гонки и конфликтные пуши.
- Второй сессии: ответвиться от текущего HEAD этой ветки — `git checkout -b feat/retrieval-disambig-v2 origin/claude/ner-translation-config-b0ozsc` — там весь v2-код (промпты, транспорт, гейты Р15, v3-метрики). Обратно — через PR.

## Зоны файлов (не пересекаемся)
Зона этой сессии (во второй НЕ трогать):
- `data/eval/wiki/**` — gt.jsonl и кампания чистки (`cleanup/**`)
- `src/palimpsest/terminology/extract.py` — NER-промпт v2.2 (заморожен, правки только здесь)
- `docs/paper/sections/**`, `docs/reports/**`, `tests/test_wiki_metrics_v3.py`

Зона второй сессии (retrieval/disambiguation):
- `src/palimpsest/terminology/grounding/candidates.py` — `generate_candidates()`: `search_limit=7`, `enrich_top=5` — главный рычаг (числа ниже)
- `src/palimpsest/terminology/grounding/label_first.py` — judge-промпты (`DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT`/`..._USER_TEMPLATE`), эскалация; проброс `FatalGroundingJudgeError` не ломать
- `src/palimpsest/terminology/grounding/match.py` — `norm()`
- `src/palimpsest/terminology/wikidata.py` — клиент (wbsearchentities + CirrusSearch), кэш `reports/terminology/wikidata_cache.jsonl`
- При изменении judge-промпта — doc-parity в том же коммите: `docs/paper/sections/appendix-prompt-judge.tex` + amendment-заметка в спеке.

## Данные и инструменты для retrieval-работы (всё в репо)
- Пилотный прогон gemini (10 статей): `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/` — `pred.jsonl` (1203 упоминания, поле `resolved_by`), `metrics.json` (официальные v3-числа), `calls.jsonl`.
- Оффлайн replay-харнесс: `data/eval/wiki/cleanup/tools/replay_analysis.py` — восстанавливает кандидатные списки для pred.jsonl из кэша БЕЗ сети и БЕЗ LLM (на пилоте 0 промахов кэша; 100% совпадение с боевым прогоном). Итерация retrieval-изменений бесплатна: поменял `generate_candidates` → реплей → сразу видно, попадает ли gold-QID в кандидаты.
- Анализы: `docs/reports/wiki-eval-v2-pilot-ner-vs-disambig.md` (разложение A/B/C/D), `docs/reports/kg-mt-emnlp-applicability.md` (KG-MT: dense ⟨имя+описание⟩ retrieval), `docs/reports/wiki-eval-v2-pilot-analysis.md`.

## Ключевые числа для retrieval (пилот, 10 статей)
- FN named 47: retrieval_miss 20 (42.6%), not_extracted 11, no_candidates 6, судья 10 (21.3%). FN term 45: not_extracted 24 (53.3%), retrieval_miss 15 (33.3%), no_candidates 4, судья 2.
- Oracle (gold-QID есть среди кандидатов): named 88.4% vs фактических 84.4% (+4.0pp); term 44.2% vs 41.6% (+2.6pp). Судья уже работает почти в потолок retrieval.
- 75.4% эскалаций упираются в кап `enrich_top=5` (медиана размера кандидатного списка = 5). Поднять `search_limit`/`enrich_top` — первый дешёвый эксперимент.
- FP-подмены: 70% (named) / 92% (term) — вынужденные, правильного QID не было в списке.
- Из KG-MT (EMNLP 2024): сигнал дизамбигуации живёт в ОПИСАНИЯХ сущностей; дешёвая аппроксимация без индекса — CirrusSearch-запросы «лемма + контекстные слова из предложения»; полный вариант — локальный dense-индекс по срезу Wikidata (mContriever, ⟨имя, описание⟩, хард-негативы из омонимов).

## Действующие правила (в обеих сессиях)
- SSOT спека: `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` (решения Р1–Р15: пины провайдеров, семплинг, reasoning, гейты; две amendment-заметки к §3.1).
- Ключ OpenRouter: лимит $2.00, остаток ~$1.29 — полные прогоны 3×100 заблокированы (нужно $12–15). Ключ не печатать/не логировать/не коммитить; ротация после сессии.
- Предсказания append-only: pred.jsonl и score-таблицы не удалять и не перезаписывать.
- Conventional Commits (EN), без AI-подписей; doc-parity в том же коммите.

## Статус этой сессии на момент handoff
Сделано: пилот gemini (все гейты §5.2 зелёные); разложение ошибок — главный bottleneck это candidate retrieval, не судья; span-level NER recall named 93.5% / term 62.1% (отчёт-артефакт по всем 64 промахам); NER-промпт v2.1→v2.2 по вердиктам владельца (падежи, гео-имена, реалии, языки; коммиты 6039325, c8c851f); чистка gold: волна 1/10 (статьи 001–010) готова и сверена оркестратором — 37 удалений агентов, точность 36/37; оверрайды в `data/eval/wiki/cleanup/overrides_wave1.json` (восстановлен «древнеперсидск» по вердикту владельца; добавлены: мумия, артефактов, Браслеты, дарами, армянской государственности, этногенез (по аналогии, флаг), «настоящие древние египтяне…»; открытый вопрос — теги древних языков хетт./аккад./урарт./ассир.).
В работе: волны 2–10 чистки (sonnet-агенты, аудит-промпт v1.1); затем агрегация в `data/eval/wiki/anchor_exclusions_draft.json` (gt.jsonl не меняется до одобрения владельца) + финальный HTML-отчёт со всеми удалениями; после одобрения — пересчёт NER-метрик на чищеном gold.
