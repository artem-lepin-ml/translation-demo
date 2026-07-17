# e2e-tester — T2 «Китайский язык» (мега-кампания, прод glossa-mt.com)

## Scope
Сценарий T2 спеки [2026-07-17-e2e-mega-campaign.md](../superpowers/specs/2026-07-17-e2e-mega-campaign.md): загрузка китайского исторического текста (5 CJK-абзацев, фикстуры манифеста) парой zh→en, проверка (а) CJK-офсетов подсветки, (б) грундинга 秦朝→Q7183 / 长城→Q12501, (в) рендера CJK в попапах/глоссарии, (г) судей (скоры + issues), (д) второго захода zh→ru, (е) export .md. Изолированная браузерная сессия `playwright-cli -s=t2` (эфемерный клон БД), golden не тронут, документы удалены через UI в конце.

Полный evidence-first отчёт (таблица шагов, терм→QID→состояние, provenance, LLM-учёт): **[docs/reports/e2e/campaign/t2-chinese-cjk.md](e2e/campaign/t2-chinese-cjk.md)**.

## Вердикт
**PASS-WITH-FINDINGS** — 1 CRITICAL, 2 HIGH, 2 MEDIUM, 4 LOW/SUSPECTED; 0 крэшей, 0 вечных спиннеров, 0 JS-ошибок за весь прогон.

1. CRITICAL — 秦朝(¶3)→Q999148 «The Qin Empire Ⅰ» (телесериал) с 🟢 «unambiguous · exact label match»; причинная цепочка из трейса: русская лемма «династия Цинь» → exact match по ru-label телесериала (Wikidata подтверждено) → LLM-judge пропущен, Q7183 остался в кандидатах; репро 2/2 (zh→en и zh→ru).
2. HIGH — ¶2 (长城): 0 терминов, 2/2 прогона, `termsStatus: done`, сбой невидим; 长城→Q12501 непроверяем.
3. HIGH — русские леммы у 15/27 и 16/28 CJK-терминов (NER russian-tuned, недетерминированно по абзацам).
4. MEDIUM — precompute `budget_exhausted` абсолютно молча (Score «—», ни бейджа/тоста); ручной Evaluate позже успешен, ретрая нет.
5. MEDIUM-LOW — двойной DELETE на один confirm (5-й прогон подряд).
6. LOW×3 + SUSPECTED×1 — бейдж «RU» в трейсе на zh-тексте; «Q5360871Q5360871» при отсутствии en-label; +1 char за хвостовой \n при file-upload; первый клик по чипу Terms не включил оверлей (единично).

Позитив: CJK-офсеты 55/55 (программная сверка `context[charStart:charEnd]==sourceSurface` + DOM + скриншоты), export плоский и побайтово равен фикстурам оба раза, судьи осмысленны на обоих target-языках, `judge_unavailable` — честная деградация.

## Files changed
- `docs/reports/e2e/campaign/t2-chinese-cjk.md` — основной отчёт (новый).
- `docs/reports/e2e/shots/campaign/t2/01…16-*.png` — 16 скриншотов (новые).
- `docs/reports/e2e/campaign/t2-files/qin-and-han-dynasties-t2-18.md`, `qin-and-han-zh-ru-t2b-19.md` — экспортные артефакты (новые).
- `docs/reports/e2e-tester-t2-chinese-cjk.md` — этот файл.
- Память агента (вне репо): `~/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` + индекс — паттерны T2.
- Код/прод не менялись; прод-состояние восстановлено (оба тестовых документа удалены через UI, скрин 16).

## Decisions & rationale
- Первый заход — paste-путь, второй — file-upload источника: покрыл оба пути ввода без раздувания сценария (заодно поймал расхождение счётчика на 1 char).
- Фактические QID сверял живым Wikidata `wbgetentities`, а не по памяти — урок T5 (манифест может ошибаться в expected-QID).
- ¶2-пропуск и budget_exhausted зафиксированы как клиентски наблюдаемые факты с API-выводом; серверные логи вне доступа роли — распутывание «LLM ничего не нашёл vs упавший вызов» оставлено дебагу.
- Ручной Evaluate на T2b после budget_exhausted — сознательный негативный тест деградации; он же дал скоры судей для zh→ru (подшаг (г) для второго захода).
- GET-запросы `/api/documents/{id}` из сессии браузера использованы только для верификации (офсеты, precompute, traceJson) — все мутации строго через UI, как требует манифест.

## Open questions
- ¶2: экстракция честно вернула пусто или per-paragraph вызов упал и был проглочен? Нужны прод-логи (терминологический pipeline) — определит severity-уточнение F2.
- Должен ли precompute ретраиться после восстановления бюджета, или «stopped» терминален по дизайну? Если терминален — где UI-сигнал?
- Язык леммы: контракт нигде не фиксирует «лемма на языке источника» — стоит закрепить в спеке терминологии, иначе F3 не квалифицируется формально как нарушение контракта.

## NOT done (explicit)
- xlsx-export, Ranking, Settings, Refine — принадлежат T4/T6/T7.
- Misaligned-создание (source≠target ¶) — контракт T1(г), не дублировал.
- AI-translate для zh — T2 задан как Upload pair; бюджет к середине прогона уже падал в exhausted.
- Server-side root-cause F1/F2 (код NER-промпта, логи) — вне роли e2e; передано в findings.
- HTML-версия отчёта — сводный HTML собирает оркестратор кампании по всем 10 сценариям.
