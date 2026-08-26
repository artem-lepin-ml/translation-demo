# Memory index

> Курировано 2026-07-12: оба файла — действующие операционные факты (прод жив,
> харнесс-паттерны воспроизводимы), ничего не убрано. Полная история — в git log
> этой директории.

- [Prod server ops](prod-server-ops.md) — ssh BioAI-grader (root), контейнер gse-demo, канонический rsync-роллаут, живой LLM-ключ на проде; `/api/health` — не гейт деплоя, нужен полный smoke + просмотр в браузере.
- [Harness flakiness recovery](harness-flakiness-recovery.md) — восстановление после сбоев Bash safety classifier и обрывов агентов в середине потока; резюмирование через SendMessage, не переделывать завершённую работу.
