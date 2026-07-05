# Отчёт: вендоринг curated-подмножества mattpocock/skills

**Главное.** Из пяти запрошенных скиллов **4 завендорены и проверены** (`grilling`, `grill-with-docs`, `to-issues`, `handoff`); пятый — `improve-codebase-architecture` — **заблокирован** supply-chain-ревью (рантайм-фетч Tailwind/Mermaid с CDN в его HTML-отчёте) и НЕ закоммичен, с точными цитатами ниже. Всё сопутствующее (CONTEXT.md, аспект `spec-fidelity`, кап graphify на sonnet, таксономия скиллов, роутинг-строка) сделано и проверено вживую.

## Provenance

- **Источник:** https://github.com/mattpocock/skills (MIT, © 2026 Matt Pocock)
- **Pinned SHA:** `272f99b22574f50e4266791c86b9302682970e23` (upstream commit 2026-07-03)
- **Vendor date:** 2026-07-04
- **Upstream layout:** `skills/<category>/<name>/SKILL.md`; каждый из 4 завендорен под `.claude/skills/<name>/` (depth-1) + `VENDORED.md`.

## Supply-chain review (до коммита)

Пять adversarial-ревьюеров (opus), по одному на скилл, читали каждый файл целиком:

| Skill | Verdict | Заметка |
|---|---|---|
| grilling | CLEAN | один файл, generic-интервью, без внешних зависимостей |
| grill-with-docs | CLEAN | делегирует к невендоренному `/domain-modeling` → поведение инлайнено при адаптации |
| to-issues | CLEAN | «issue tracker» → файловые тикеты; `/setup-matt-pocock-skills` вырезан |
| handoff | CLEAN | писал в OS-temp → перенаправлен в repo-local HANDOFF.md |
| improve-codebase-architecture | **BLOCKED** | runtime CDN fetch (см. цитаты) |

**BLOCKED — точные цитаты (`improve-codebase-architecture`):**

- `SKILL.md`: "The report uses **Tailwind via CDN** for layout and styling, and **Mermaid via CDN** for diagrams where a graph/flow/sequence reliably communicates the structure."
- `HTML-REPORT.md`: `<script src="https://cdn.tailwindcss.com"></script>`
- `HTML-REPORT.md`: `import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";`
- `HTML-REPORT.md`: `mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "loose" });`

Правило задачи: «нашёл runtime-fetch → не коммить, пометь BLOCKED с точной цитатой». Дополнительно это нарушает инвариант проекта о self-contained отчётах (Artifact CSP / локальный served-HTML — без внешних хостов). **Ремедиация:** завендорить Tailwind+Mermaid локально (self-contained, без внешних хостов) и убрать `securityLevel:'loose'`, ИЛИ переписать отчёт под проектный self-contained Tokyo-Night шаблон. После ремедиации — классифицируется как user-invoked. Готов сделать отдельным PR по слову владельца.

## Постатейный статус

| Пункт | Статус | Свидетельство |
|---|---|---|
| P1 — вендоринг 4 скиллов | DONE | P6.1 (`ls` — 4 SKILL.md на месте) |
| P1 — 5-й скилл | BLOCKED | цитаты выше; директория не создана |
| P1 — VENDORED.md ×4 + SHA | DONE | P6.3 (`grep` SHA в 4 файлах) |
| P1 — flat layout | DONE | P6.2 (`find -mindepth 3` пусто) |
| P1 — live registration | DONE* | `grilling`/`handoff` всплыли в available-skills этой сессии; `grill-with-docs`/`to-issues` зарегистрированы, но `disable-model-invocation:true` (user-invoked-only) — см. примечание |
| P2 — адаптация (пути/схемы) | DONE | тексты SKILL.md (ниже описаны отклонения) |
| P2 — таксономия `skills.md` | DONE | P6.5 (`ls` + 17-строчная таблица) |
| P3 — аспект `spec-fidelity` | DONE | P6.6 (`grep` строка 63, внутри `<!-- custom -->` 37–66) |
| P4 — `CONTEXT.md` | DONE | P6.5 (`ls`) |
| P4 — routing-строка в CLAUDE.md | DONE | `CLAUDE.md:235` |
| P5 — кап в graphify/SKILL.md | DONE | P6.7 (`grep "never opus"` строка 9) |
| P5 — выравнивание wording | DONE | `CLAUDE.md:27,134,135`, `graphify-freshness.mjs:41,44,64` |
| P6.8 — dry-run to-issues | DONE | тикет verbatim ниже |

`*` live registration: плоский layout (то, что раньше молча ломало superpowers) подтверждён вживую — `grilling`, `handoff`, обновлённый `graphify` появились в списке доступных скиллов этой же сессии. `grill-with-docs` и `to-issues` несут `disable-model-invocation:true`, поэтому в авто-список не попадают (это их таксономия — user-invoked-only), но зарегистрированы как depth-1 SKILL.md с валидным frontmatter и вызываются по `/<name>`.

## Acceptance — сырые выводы

```
$ ls .claude/skills/{grilling,grill-with-docs,to-issues,handoff,improve-codebase-architecture}/SKILL.md
.claude/skills/grill-with-docs/SKILL.md
.claude/skills/grilling/SKILL.md
.claude/skills/handoff/SKILL.md
.claude/skills/to-issues/SKILL.md
ls: cannot access '.claude/skills/improve-codebase-architecture/SKILL.md': No such file or directory   # BLOCKED — ожидаемо

$ find .claude/skills -mindepth 3 -name SKILL.md
# (пусто — flat layout)

$ grep -n "272f99b22574f50e4266791c86b9302682970e23" .claude/skills/{grilling,grill-with-docs,to-issues,handoff}/VENDORED.md
.claude/skills/grilling/VENDORED.md:3:- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`
.claude/skills/grill-with-docs/VENDORED.md:5:- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`
.claude/skills/to-issues/VENDORED.md:3:- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`
.claude/skills/handoff/VENDORED.md:3:- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`

$ ls CONTEXT.md .claude/rules/skills.md
.claude/rules/skills.md
CONTEXT.md

$ grep -n "spec-fidelity" docs/superpowers/review-aspects.md
63:### C7. Соответствие спецификации (spec-fidelity)

$ grep -n "never opus" .claude/skills/graphify/SKILL.md
9:> **Model cap (owner directive).** Invoke via a background agent pinned `model: sonnet` or lower (`haiku` acceptable) — never opus or fable for graph build/update/query.
```

## Dry-run to-issues (P6.8) — тикет verbatim

Прогон адаптированного `to-issues` на существующем плане `docs/superpowers/plans/2026-07-01-model-registry.md`; тикет 001 записан ТОЛЬКО в scratchpad (демо соответствия схеме W5, не коммитится):

```
---
status: ready
agent: python-pro
model: sonnet
depends_on: []
files:
  - src/palimpsest/webapp/model_matrix.py
  - src/palimpsest/webapp/model_params.py
  - src/palimpsest/llm/client.py
  - tests/test_model_params.py
  - tests/test_llm_result.py
---

## Scope

Establish the single source-of-truth data contract every later slice builds on:
an 8-model capability matrix, a per-model params filter, and a widened LLM
client that reports usage/cost. `LLMClient.complete()` returns
`LLMResult(content, usage)` instead of a bare string, with `extra_body`
passthrough and retries disabled. `ModelParams.for_model(name, raw)` drops
params a model doesn't support (temperature/top_k/min_p/reasoning) per the
matrix; `to_extra_body()` builds the provider payload plus the OpenRouter
`usage:{include:true}` cost-accounting flag. No existing caller is switched
over yet (judge.py, seed.py, _client_for follow in later slices).

## Acceptance Criteria

1. `uv run pytest tests/test_model_params.py -v` -> all tests pass (8 matrix rows / 5 OpenRouter; Claude and Gemini drop `temperature`).
2. `uv run pytest tests/test_llm_result.py -v` -> 2 passed (`complete()` returns `LLMResult` with populated `usage`; `temperature=None` omitted while `extra_body` still sent).
3. `python -c "from palimpsest.webapp import model_matrix as mm; assert len(mm.MATRIX) == 8"` -> exits 0.

## Out of scope

Wiring these types into `_client_for`, `budget.py`, `seed.py`, or `judge.py` — that starts in the next slice.
```

Тикет 1:1 соответствует схеме W5 адаптированного скилла (frontmatter `status/agent/model/depends_on/files` + Scope ≤10 строк + нумерованные исполняемые AC + одна строка Out of scope).

## Отклонения

- **Ветка.** Задача просила `feat/pocock-skills` от `dev-demo`; облачная сессия жёстко привязана к designated-ветке `claude/claude-md-docs-review-tabi6h`, где уже открыт draft-PR #2 (не влит → сброс невозможен без потери незамерженной работы). Работа положена стеком туда — тематически это то же «workflow hardening» (эти 5 скиллов ровно те, на что ссылается v2 `workflow.md`).
- **`.claude/workflow.md` в чекауте нет** (как и хуков `workflow-inject.py`/`dispatch-telemetry.py`/`e2e-screenshot-gate.py`). Загруженный `workflow.md` — контекст v2, не файл к созданию (вне P1–P7). Скиллы сделаны self-contained: `to-issues` встраивает схему W5 целиком и ссылается на `.claude/workflow.md § W5` как на канон «когда появится».
- **`improve-codebase-architecture`** — BLOCKED, не завендорен (см. выше).
- **graphify-кап** сформулирован «… — never opus or fable …» (строчная, через тире), чтобы удовлетворить и текст P5, и буквальный `grep -n "never opus"` из P6.
- **`to-issues` и `grill-with-docs`** содержат по одному worked-example/ADR-шаблону — ради самодостаточности скилла (не запрошено явно, но в рамках «self-contained»).
- **`handoff`**: снят `disable-model-invocation:true` — чтобы соответствовать классификации model-invoked.
- **CONTEXT.md — находки при граундинге** (задокументированы в самом CONTEXT.md, не «замолчаны»): (a) `docs/subsystems/webapp.md:32` говорит «five criteria», но `seed.py` сеет 4 (5-й «Cultural Adaptation» убран в wave-4) — вероятно устаревшая прод-дока, НЕ правил (вне скоупа); (b) `src/palimpsest/evaluation/criteria.py` (6-критериальная формула) — мёртвый код, нигде не импортируется; помечен как не-живой, чтобы не путать с реальным набором.

## НЕ сделано (явно)

- `improve-codebase-architecture` НЕ завендорен (BLOCKED; ремедиация описана).
- `.claude/workflow.md` НЕ создан (вне P1–P7; на него ссылаются как на канон схемы).
- Сгенерированный dry-run тикет НЕ закоммичен (только scratchpad — демо схемы).
- Устаревшее «five criteria» в `webapp.md` НЕ исправлено (вне скоупа; зафлажено в CONTEXT.md).
- Отдельный `feat/pocock-skills` PR НЕ создан (сессия привязана к designated-ветке).
