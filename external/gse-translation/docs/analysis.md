# Stage 03 — code review (pre-merge)

Up-link: [CLAUDE.md](../CLAUDE.md). Контекст: [docs/superpowers/specs/2026-05-14-scoring-v1-only-design.md](superpowers/specs/2026-05-14-scoring-v1-only-design.md), [docs/known_issues.md](known_issues.md).

Свод результатов swarm-ревью (4 параллельных агента, opus) по stage 03 на ветке `feat/scoring-v2-sequential` перед мержем в `feat/project`. Цель — найти проблемные места и мусорный код, оценить соответствие инварианту «один модуль = одна ответственность».

Приоритеты:
- **HIGH** — баг, мёртвый код, нарушение инварианта, плохая отлаживаемость в проде.
- **MED** — ergonomics / idiomaticity / hidden coupling.
- **LOW** — nitpick, информационная заметка, потенциальная регрессия без следов в проде.

---

## TL;DR — что чинить в первую очередь

| Приоритет | Находка | Где |
|---|---|---|
| HIGH | scoring.py совмещает 4 несвязанных concern'а (parsing / dispatcher / factcheck / aggregation) | [A1](#a1) |
| HIGH | Aggregation хардкодит пути в обход `paths.py` | [A2](#a2) |
| HIGH | `os.environ[cfg.api_key_env]` падает голым KeyError без контекста | [C4](#c4) |
| HIGH | `fluency.md` ассиметричен по структуре и имеет внутренний conflict ключей (`suggested_improvement` vs `suggestion`) | [D1](#d1) |
| MED | 9 YAML-конфигов дублируют общий каркас (P1–P6 + large-low/small-low) | [B1](#b1) |
| MED | `load_prompts` не фильтрует не-criterion `.md` файлы | [B5](#b5) |
| MED | `LLMConfig` дублирует поля `ModelConfig` — sync вручную в 3 местах | [B7](#b7) |
| MED | Local vLLM модели без явного `supports_structured_output` | [B4](#b4) |
| MED | `response_format` silently drop без логирования | [C2](#c2) |
| MED | Retry amplification 3 × 2 = 6 не задокументирован в одном месте | [C3](#c3) |
| MED | `build_merged_jsonl` — non-atomic write | [C7](#c7) |
| MED | `--force` flag — бизнес-логика в CLI | [D8](#d8) |
| MED | Hardcoded priority bucket list в `03_scoring_exprs.sh` | [D5](#d5) |
| MED | `03_cleanup_minus_one.py` — мигратор без TTL | [D6](#d6) |
| MED | `consistency.md` — лишняя скоринговая калибровка vs остальные 5 промптов | [D2](#d2) |
| MED | Нет теста на response_format toggle (D16) | [D9](#d9) |
| MED | soft-warning через `print(stderr)` вместо `warnings.warn` | [B6](#b6) |
| MED | `score_paragraph` использует custom dict-of-Exception вместо `gather(return_exceptions=True)` | [A5](#a5) |
| MED | Два почти идентичных диспатчера `_score_run_for_judge` ↔ `_score_factcheck_for_run` | [A7](#a7) |

LOW-находки сгруппированы по разделам ниже.

---

## Раздел A. scoring.py — архитектура и ответственности

### <a id="a1"></a>A1. Файл совмещает 4 несвязанных concern'а — HIGH
**Где**: [src/palimpsest/scoring.py:1-746](../src/palimpsest/scoring.py) (весь файл, 746 строк).
**Что**: один модуль держит (a) парсинг ответов и retries, (b) dispatcher по runs/judges/criteria, (c) factcheck-обвязку, (d) aggregation `merged.jsonl` и `scores.json`. CLAUDE.md «one module = one responsibility» нарушен.
**Почему проблема**: aggregation — это **post-processing**, factcheck — отдельный стадийный поток с другим judge'ом и другой schema, parsing — это библиотечная ответственность. Растёт стоимость любого изменения и тестов.
**Что сделать**: вынести в подпакет `scoring/`:
- `scoring/parsing.py` — `JudgeParseError`, `parse_judge_response`, `_JSON_FENCE`, `classify_paragraph`, `_JUDGE_RESPONSE_FORMAT`, `_USER_MSG_TEMPLATE`, `score_paragraph`.
- `scoring/persistence.py` — `append_jsonl_row`, `load_existing_ids`, `_load_parse_failure_counts`, `_read_jsonl`, `_read_aligned_lines`.
- `scoring/factcheck_runner.py` — `_extractor_run`, `_overlap_run`, `score_factcheck`, `_score_factcheck_for_run`.
- `scoring/aggregation.py` — `_avg_excluding_nulls`, `build_merged_jsonl`, `build_aggregate_scores`.
- `scoring/__init__.py` (или `dispatcher.py`) — `_score_run_for_judge`, `run_scoring`, `_build_client`, `_skip_payload`, `load_prompts`, константы threshold.

### <a id="a2"></a>A2. Aggregation хардкодит пути в обход `paths.py` — HIGH
**Где**: [scoring.py:559](../src/palimpsest/scoring.py#L559), [:564](../src/palimpsest/scoring.py#L564), [:572](../src/palimpsest/scoring.py#L572), [:621](../src/palimpsest/scoring.py#L621), [:628](../src/palimpsest/scoring.py#L628).
**Что**: `build_merged_jsonl` склеивает `run_dir / j / f"{c}_scores.jsonl"`, `run_dir / "factcheck" / "factcheck_scores.jsonl"`, `run_dir / "merged_scores.jsonl"`; `build_aggregate_scores` — `evaluation_dir / run_dirname / "merged_scores.jsonl"` и `evaluation_dir / "scores.json"`. В `paths.py` уже есть `criterion_jsonl`, `factcheck_jsonl`, `merged_jsonl`, `scores_json`, `judge_dir`, `factcheck_dir` — не используются.
**Почему проблема**: invariant «single source of truth» (Hard Invariant #3). Переименовать `factcheck_scores.jsonl` в одном месте — забыть в другом.
**Что сделать**: принимать `base_dir` + `evaluation_subdir` + `run`, звать `merged_jsonl()`, `criterion_jsonl()`, `factcheck_jsonl()`, `scores_json()`. Удалить ручную склейку.

### A3. `score_paragraph` смешивает API-вызов, retry и parsing — MED
**Где**: [scoring.py:134-172](../src/palimpsest/scoring.py#L134-L172).
**Что**: внутренний `_one` одновременно делает (a) `client.complete`, (b) inline-retry loop, (c) парсинг через `parse_judge_response`, (d) per-attempt warning print. Поверх ещё `asyncio.gather` на 6 critеrion'ах.
**Почему проблема**: тестировать retry-логику нельзя без мока `client.complete` И раскладки prompts. Вложенность 3 уровня + обнажённый `assert last_exc is not None` (антипаттерн — assert маскирует структурный риск).
**Что сделать**: выделить `_one_criterion(client, criterion, prompt, user_msg) -> dict | JudgeParseError` без assert (вынести retry в отдельную async-функцию, последний catch возвращает `exc`).

### A4. `prompts_for_this = dict(prompts)` + ручной `pop` — MED
**Где**: [scoring.py:367-376](../src/palimpsest/scoring.py#L367-L376).
**Что**: копия dict для каждого параграфа, затем `pop` по criterion'ам, которые уже сделаны или превысили threshold. Через десяток строк код проверяет `if not prompts_for_this: return` и снова итерируется.
**Почему проблема**: неидиоматично — работа с подмножеством через мутацию. Прозрачнее построить `pending: list[str] = [c for c in criteria if i not in existing[c] and fail_counts.get((i,c),0) < THRESHOLD]`.
**Что сделать**: заменить mutate-копию на comprehension `pending_criteria`, в `score_paragraph` передавать `{c: prompts[c] for c in pending}`.

### <a id="a5"></a>A5. `score_paragraph` контракт `dict | JudgeParseError` — нестандартно — MED
**Где**: [scoring.py:139](../src/palimpsest/scoring.py#L139), [:401-424](../src/palimpsest/scoring.py#L401-L424).
**Что**: возврат `dict[str, dict | JudgeParseError]` (исключение как значение). Caller через `isinstance` разветвляет. Это намеренный fix D14, но идиома Python — `asyncio.gather(..., return_exceptions=True)`, которая делает ровно это.
**Почему проблема**: D14 lesson правильный (gather cancels siblings), но реализация через ручной try/except дублирует stdlib. Custom-pattern требует чтения комментария; `return_exceptions=True` любой Python-читатель узнает мгновенно.
**Что сделать**: `asyncio.gather(*(_one(c, p) for c, p in prompts.items()), return_exceptions=True)`, `_one` поднимает `JudgeParseError` штатно после retries, внешний слой собирает `dict(zip(prompts, results))`. Тип возврата остаётся тем же.

### A6. `_skip_payload` — лишняя функция — LOW
**Где**: [scoring.py:293-299](../src/palimpsest/scoring.py#L293-L299), вызов [:385](../src/palimpsest/scoring.py#L385).
**Что**: строит dict с 4 ключами, из которых caller использует только `llm_report`.
**Что сделать**: удалить, инлайнить `llm_report=f"skipped: {reason}"` прямо в построение row.

### <a id="a7"></a>A7. Два почти идентичных диспатчера — MED
**Где**: [scoring.py:302-452](../src/palimpsest/scoring.py#L302-L452) (`_score_run_for_judge`) vs [:455-520](../src/palimpsest/scoring.py#L455-L520) (`_score_factcheck_for_run`).
**Что**: общий каркас — load pairs, build target paths, load existing, async-tqdm loop, failures list, meta.json write, raise first. 80% общего кода.
**Что сделать**: вынести общий runner-каркас в helper (`_run_paragraphs(label, pairs, process_fn, meta_path, meta_payload)`); `_process` остаётся специфичным per-dispatcher. Либо принять дубль как осознанный и пометить TODO.

### A8. `max_concurrency=0` magic default в `_build_client` — LOW
**Где**: [scoring.py:266](../src/palimpsest/scoring.py#L266).
**Что**: `max_concurrency: int = 0` — оба caller'а всегда передают значение явно. Default мёртвый, и `0` как «без лимита» — нестандартно (обычно `None`).
**Что сделать**: убрать дефолт, либо `int | None = None` с явной семантикой «no cap».

### A9. `SCORE_SKIPPED: Final[None] = None` — тавтологичный алиас — LOW
**Где**: [scoring.py:96](../src/palimpsest/scoring.py#L96).
**Что**: `score=SCORE_SKIPPED` читается хуже, чем `score=None`. Семантика «terminal skip» закреплена в D12.
**Что сделать**: либо удалить алиас и использовать `None`, либо переименовать в `TERMINAL_SKIP`.

### A10. Прямой `print` для warning'ов и progress'а — LOW
**Где**: 8 точек в [scoring.py](../src/palimpsest/scoring.py), часть в stdout, часть в stderr.
**Что**: нет уровней, неконсистентно (одни warning'и в stdout, другие в stderr).
**Что сделать**: завести `logger = logging.getLogger("palimpsest.scoring")`. `async_tqdm.write` оставить только для прогресс-перебивок.

### A11. `_MAX_PARSE_ATTEMPTS`, `_PERSISTENT_FAILURE_THRESHOLD` — захардкожены — LOW
**Где**: [scoring.py:125](../src/palimpsest/scoring.py#L125), [:252](../src/palimpsest/scoring.py#L252).
**Что**: D13 называет threshold «tunable». YAGNI до момента, когда понадобится крутить.
**Что сделать**: оставить, добавить comment-ссылку на запись в known_issues.

### A12. Docstring ссылается на несуществующий `_score_run_for_judge._process` — LOW
**Где**: [scoring.py:146](../src/palimpsest/scoring.py#L146).
**Что**: `_process` — закрытая `async def` внутри функции, attribute-ссылкой через дот не доступна. Сбивает IDE help.
**Что сделать**: заменить на «the dispatcher inside `_score_run_for_judge`».

---

## Раздел B. Конфигурация и dispatcher

### <a id="b1"></a>B1. P1–P6 + large-low/small-low дублируют общий каркас — MED
**Где**: [configs/scoring/01-top-vs-baseline.yaml](../configs/scoring/01-top-vs-baseline.yaml) … 06, плюс `large-low.yaml`, `small-low.yaml`.
**Что**: 8 из 9 файлов различаются только `runs:` и (иногда) набором `judges:`. Одинаковые `base_dir`, `prompts_variant: v1`, `max_concurrency: 32`, `factcheck.{enabled,judge}`. P1∩P6 пересекаются по `large/claude-opus-4.7-low_par_by_par`, `gemini-3.1-pro-low_par_by_par`, `gpt-5.5-low_par_by_par`.
**Почему проблема**: Hard Invariant #3. Смена `max_concurrency` или `factcheck.judge` — править все 9.
**Что сделать**: YAML `defaults:` + `runs_buckets:` со сборкой в коде, либо вынести общий блок в `configs/scoring/_base.yaml` через `!include`. Минимум — README конфиг-папки с пометкой «P-набор — legacy от v2 sequential».

### B2. `ScoringConfig.prompts_variant` — переход с Literal на str — LOW
**Где**: [config.py:82](../src/palimpsest/config.py#L82).
**Что**: свободный str + soft-warning validator. Опечатка `v11` отловится только soft-warning'ом в stderr, не как pydantic error.
**Что сделать**: ничего обязательного. Опционально — `field_validator` с regex `^[a-z][a-z0-9_]*$`.

### B3. `JudgeConfig.variant` удалён + `extra: forbid` — миграция чистая — info
**Где**: [config.py:60-65](../src/palimpsest/config.py#L60-L65).
**Что**: `grep "variant:" configs/scoring/` показывает только top-level. Миграция D2 завершена.

### <a id="b4"></a>B4. Local vLLM модели без явного supports_structured_output — MED
**Где**: [configs/models.yaml:14-37](../configs/models.yaml#L14-L37) (`qwen3-4b-thinking`, `translate_gemma-27b`, `qwen3_6-27b`).
**Что**: 3 модели без поля → default `False`. Все 29 cloud OpenRouter моделей имеют явный `true`.
**Почему проблема**: default-false молча роняет `response_format`. Если оператор запускает vLLM с `--guided-decoding-backend outlines` — нужно вручную помнить про правку YAML. Нет ни валидатора, ни комментария.
**Что сделать**: явно прописать `supports_structured_output: false` всем трём local entries, либо добавить inline-комментарий «set to true if launched with --guided-decoding-backend».

### <a id="b5"></a>B5. `load_prompts` не фильтрует не-criterion `.md` — MED
**Где**: [scoring.py:99-116](../src/palimpsest/scoring.py#L99-L116).
**Что**: `sorted(variant_dir.glob('*.md'))` — любой `.md` (README, draft, _notes) становится criterion'ом, попадает в `merged_scores.jsonl` ключом и спавнит API-вызовы.
**Почему проблема**: D1 говорит «filename = contract», но защиты нет. Сейчас лежит ровно 6 файлов — hold-by-convention, не enforcement.
**Что сделать**: filter по whitelist (`^[a-z][a-z0-9_]+\.md$`, отбрасывать `README.md`, `_*.md`, `.*.md`), либо суффикс `*.criterion.md`. Минимум — docstring «directory MUST contain ONLY criterion .md files».

### <a id="b6"></a>B6. Soft-warning через `print(stderr)` в pydantic validator — MED
**Где**: [config.py:88-98](../src/palimpsest/config.py#L88-L98).
**Что**: `@model_validator(mode='after')` использует `print(..., file=sys.stderr)` вместо `warnings.warn` или `logging`.
**Почему проблема**: `warnings.warn` подбирается через `pytest.warns(...)` и фильтры (`-W error::UserWarning`); голый `print` — нет. Тесты не могут assert'ить warning. CLAUDE.md «Idiomatic-first».
**Что сделать**: `warnings.warn(f"prompts variant directory {variant_dir} is missing or empty", UserWarning, stacklevel=2)`.

### <a id="b7"></a>B7. `LLMConfig` дублирует поля `ModelConfig` — MED
**Где**: [config.py:13-47](../src/palimpsest/config.py#L13-L47) vs [llm/client.py:19-61](../src/palimpsest/llm/client.py#L19-L61).
**Что**: 8 из 10 полей `LLMConfig` 1-в-1 копируют `ModelConfig`. Дополнительно: `model`, `api_key` (resolved), `or_style` (derived).
**Почему проблема**: новое поле = править 3 места (`ModelConfig` → `LLMConfig` → `from_model_config`). Уже случилось с `supports_structured_output`.
**Что сделать**: упростить до `LLMConfig(model_config: ModelConfig, api_key: str, or_style: bool)` и читать sampling params через `self.model_config.temperature`. Альтернатива — выкинуть `LLMConfig` совсем и работать поверх pydantic.

### B8. `_score_run_for_judge` получает `prompts` и `criteria` параллельно — LOW
**Где**: [scoring.py:302-311](../src/palimpsest/scoring.py#L302-L311), call site [:706-712](../src/palimpsest/scoring.py#L706-L712).
**Что**: `criteria` всегда `== list(prompts.keys())` по контракту `load_prompts`. Внутри используется только для итерации.
**Что сделать**: убрать `criteria` из сигнатуры `_score_run_for_judge` и `score_paragraph`, везде вычислять `list(prompts.keys())`. `build_merged_jsonl`/`build_aggregate_scores` работают только с criterion-JSONL на диске — там `criteria` нужен.

### B9. `meta.json` содержит весь корпус промптов — LOW
**Где**: [scoring.py:442](../src/palimpsest/scoring.py#L442).
**Что**: десятки KB JSON snapshot'а промптов, дублированный по каждому run-judge. Промпты лежат под git как single source of truth.
**Что сделать**: хранить только `prompts_variant` (имя папки) + `criteria` (list). При нужде reproducibility — `git rev-parse HEAD` тоже в meta.

---

## Раздел C. LLM client, paths, persistence

### C1. `_load_parse_failure_counts` — snapshot на старте run'а — LOW
**Где**: [scoring.py:230-249](../src/palimpsest/scoring.py#L230-L249), вызов [:331](../src/palimpsest/scoring.py#L331).
**Что**: `fail_counts` собирается один раз; failures того же run'а в счётчик не попадают. Порог `_PERSISTENT_FAILURE_THRESHOLD=3` срабатывает только после рестарта.
**Что сделать**: переименовать в `fail_counts_at_start` + WHY-comment, либо инкрементировать локально из `_persist_failure_log`.

### <a id="c2"></a>C2. `response_format` silently drop без логирования — MED
**Где**: [llm/client.py:203-205](../src/palimpsest/llm/client.py#L203-L205).
**Что**: при `supports_structured_output=False` параметр беззвучно отбрасывается. Если кто-то передаст `{"type":"json_schema","strict":True,...}` — silently превратится в prompt-only mode.
**Что сделать**: однократный stderr-warn per-LLMClient при первом drop'е. Либо guard на known-safe форматы (`type == "json_object"`), всё остальное — `NotImplementedError`.

### <a id="c3"></a>C3. Retry amplification 3 × 2 = 6 — MED
**Где**: [client.py:88](../src/palimpsest/llm/client.py#L88) (`_RETRY_MAX_ATTEMPTS=3`) + [scoring.py:125](../src/palimpsest/scoring.py#L125) (`_MAX_PARSE_ATTEMPTS=2`).
**Что**: worst-case 6 API hits на параграф/criterion. 6 × 50 = 1800 вместо ожидаемых 300 на битом ране.
**Что сделать**: блок-комментарий в начале `score_paragraph` с явным worst-case бюджетом + пересмотреть, нужны ли оба слоя на parse-fail'е (parse-retry уже стоит после transient-backoff).

### <a id="c4"></a>C4. `os.environ[cfg.api_key_env]` — KeyError без контекста — HIGH
**Где**: [llm/client.py:51](../src/palimpsest/llm/client.py#L51) (`LLMConfig.from_model_config`).
**Что**: голый `KeyError('OPENROUTER_API_KEY')`. В battery через `_run_task` ловится в except и печатается `task failed: <run> × <judge.model>: KeyError(...)` — связь восстанавливается только по логам.
**Что сделать**: `os.environ.get(cfg.api_key_env)` + `raise RuntimeError(f"model {cfg.name!r} requires env var {cfg.api_key_env}, but it is not set")`. 3 строки.

### C5. `LLMConfig` ≈ `ModelConfig` — duplication — LOW
**Где**: [client.py:19-61](../src/palimpsest/llm/client.py#L19-L61) vs [config.py:13-47](../src/palimpsest/config.py#L13-L47).
**Что**: дубликат [B7](#b7). Tech-debt, не блокер.

### C6. Concurrency на persistence — нет inter-process lock — LOW
**Где**: [scoring.py:259-263](../src/palimpsest/scoring.py#L259-L263).
**Что**: `write_lock` — `asyncio.Lock`, защита только в одном loop'е. Два процесса на одинаковый judge dir → POSIX append < 4KB атомарен, corruption не будет, но `load_existing_ids` может дублировать ids.
**Что сделать**: зафиксировать в `docs/known_issues.md`: «не запускайте два процесса с одинаковым judge dir».

### <a id="c7"></a>C7. `build_merged_jsonl` — non-atomic write — MED
**Где**: [scoring.py:572-605](../src/palimpsest/scoring.py#L572-L605).
**Что**: открывает `out_path` в `"w"`, пишет построчно. Если процесс убьют — truncated last line; `build_aggregate_scores` сразу следом читает и может схватить partial `json.loads` raise.
**Что сделать**: запись в `out_path.with_suffix(".jsonl.tmp")` + `os.replace`. 3 строки.

### C8. `meta.json` без fsync — LOW
**Где**: [scoring.py:443](../src/palimpsest/scoring.py#L443).
**Что**: criterion-rows fsync'ятся (commit `d8ef294`), а `meta.json` — `Path.write_text` без fsync/atomic.
**Что сделать**: либо принять асимметрию (meta — best-effort), либо tmp+rename. Решение по тому, читает ли кто-то meta.json в parsing flow — судя по grep, нет.

### C9. `_score_run_for_judge` тащит `cfg.base_dir / cfg.evaluation_subdir` 5 раз — LOW
**Где**: [scoring.py:324, 327, 440, 469-470, 721, 735](../src/palimpsest/scoring.py).
**Что**: тройка `(base_dir, evaluation_subdir, run)` повторяется по call sites.
**Что сделать**: YAGNI; если в `paths.py` появится 4-й аргумент — фабрика-замыкание `RunPaths(...)`.

### C10. `LLMClient` mixes 4 concerns — но overengineering — LOW
**Где**: [client.py:99-242](../src/palimpsest/llm/client.py#L99-L242).
**Что**: provider dispatch, transient retry, rate-limit gate, response_format gating, or_style wrapping, thinking-mode anthropic kwargs.
**Что сделать**: не разрезать. Если файл доедет до 400 строк или появится 3-й провайдер — выделить `_complete_openai`/`_complete_anthropic` в `llm/providers.py`, оставив `LLMClient` фасадом.

---

## Раздел D. Скрипты, промпты, тесты

### <a id="d1"></a>D1. `fluency.md` уникален по полю и порядку секций — HIGH
**Где**: [prompts/03_scoring/v1/fluency.md:3,11,63](../prompts/03_scoring/v1/fluency.md) vs остальные пять.
**Что**: только в fluency секции идут `Definition → Your Role` (остальные 5 — `Your Role → Definition`). Поле названо `"suggested_improvement"`, в accuracy/consistency/cultural/style/terminology — `"suggestion"`. В fluency.md `CRITICAL RULES` ссылаются на «the `suggestion` field», а схема использует `suggested_improvement` — внутренний conflict.
**Почему проблема**: D16: «все 6 critеrion-промптов **симметричны**». Дрейф ломает контракт, запутывает модель и downstream-парсеры.
**Что сделать**: переставить `## Your Role` перед `## Definition of Fluency`. Переименовать `suggested_improvement` → `suggestion` (либо во всех остальных промптах наоборот — 5-vs-1 дешевле выровнять fluency).

### <a id="d2"></a>D2. `consistency.md` — лишняя секция «Handling of Difficult Cases» — MED
**Где**: [prompts/03_scoring/v1/consistency.md:21-37](../prompts/03_scoring/v1/consistency.md#L21-L37).
**Что**: только в consistency есть блок с «scoring impact» правилами (−1 балл за silent alteration, escalation pattern).
**Почему проблема**: D16: «отличаться только содержанием criterion'а». Этот блок смещает шкалу 1–10 относительно других судей. Cross-criterion сравнение скоров теряет калибровку.
**Что сделать**: снять блок или распространить аналогичную калибровку на остальные 5. Минимум — убрать жёсткую «−1 point» арифметику.

### D3. JSON skeletons расходятся по top-level ключам — LOW
**Где**: 6 промптов в [prompts/03_scoring/v1/](../prompts/03_scoring/v1/).
**Что**: inventory-ключи разные (`identified_terms`, `cultural_inventory`, `recurring_elements`, `source_structure_note`, `source_stylistic_profile`). `parse_judge_response` использует только `final_score` и `summary` — остальное летит в `llm_report` и нигде не агрегируется.
**Что сделать**: либо явно задокументировать differentation в спеке, либо унифицировать к `{summary, identified_issues, criteria_assessment, final_score}`.

### D4. `03_scoring_exprs.sh` — название не отражает функцию — LOW
**Где**: [scripts/03_scoring_exprs.sh:1-101](../scripts/03_scoring_exprs.sh).
**Что**: первая строка комментария — «Resume scoring for the pilot», имя файла — `_exprs.sh`.
**Что сделать**: переименовать в `03_scoring_pilot.sh` или `03_scoring_resume.sh`.

### <a id="d5"></a>D5. Hardcoded priority bucket list в bash — MED
**Где**: [scripts/03_scoring_exprs.sh:94-99](../scripts/03_scoring_exprs.sh#L94-L99).
**Что**: 6 вызовов `attempt_config configs/scoring/0N-*.yaml` зашиты списком. Skip-нуть один bucket — комментировать строку. Bash содержит бизнес-логику «вот порядок исполнения exp'ов».
**Что сделать**: `for cfg in configs/scoring/0[1-9]-*.yaml; do attempt_config "$cfg"; done`. Лексикографический `01..06` порядок сохраняется.

### <a id="d6"></a>D6. `03_cleanup_minus_one.py` — мигратор без TTL — MED
**Где**: [scripts/03_cleanup_minus_one.py:1-66](../scripts/03_cleanup_minus_one.py).
**Что**: удаляет legacy `-1` rows (post-D12). После применения один раз — мёртвый код. Нет TODO о removal, нет даты.
**Что сделать**: добавить в docstring явное «DELETE AFTER <YYYY-MM-DD> once all existing JSONLs are scrubbed». Лучше — удалить в том же PR, после миграции. Тест-инвариант «dispatcher never writes -1» уже защищает от регрессии.

### D7. `03_translation_scoring.py` docstring врёт — LOW
**Где**: [scripts/03_translation_scoring.py:1](../scripts/03_translation_scoring.py#L1).
**Что**: `"""Stage 04 scoring CLI: ..."""`. На самом деле Stage 03.
**Что сделать**: заменить на `"""Stage 03 scoring CLI: ..."""`.

### <a id="d8"></a>D8. `--force` flag — бизнес-логика в CLI — MED
**Где**: [scripts/03_translation_scoring.py:23, 37-42](../scripts/03_translation_scoring.py#L23).
**Что**: при `--force` скрипт `rglob("*.jsonl")` и `unlink()` каждый. Бизнес-логика «как сбросить state» живёт в CLI-обёртке. Опасно: нет dry-run, легко прибить рядом стоящий файл.
**Что сделать**: перенести wipe-логику в `palimpsest.scoring.clear_run(cfg, run)`, в CLI оставить однострочник. Появится тестируемая поверхность.

### <a id="d9"></a>D9. Нет теста на response_format toggle (D16) — MED
**Где**: `tests/` — отсутствует.
**Что**: D16 — центральный механизм, регрессия здесь незаметна (если кто-то вынесет drop-условие — gemma/qwen-local получат `response_format` и упадут на стороне провайдера).
**Что сделать**: unit-тест в `test_llm_client.py`: mock provider call, проверить `response_format in kwargs` для модели с флагом True и `not in kwargs` для False. (Частично уже есть три теста — расширить покрытие на dispatch-call.)

### D10. `single_criterion_response` слишком thin — LOW
**Где**: [tests/conftest.py:7-14](../tests/conftest.py#L7-L14).
**Что**: хардкодит `identified_issues: []`, параметризован только score+summary. Edge cases не тестируются: `final_score: "8"`, `final_score: 8.5`, response с дополнительными полями.
**Что сделать**: либо принять narrow scope (переименовать в `valid_response`), либо добавить `extra_fields`, `score_as`.

### D11. Покрытие `parse_judge_response` хорошее, но boundary `1` и `10` не тестируется — LOW
**Где**: [tests/test_scoring_strategy.py:45-60](../tests/test_scoring_strategy.py#L45-L60).
**Что**: есть `missing_score`, `score_out_of_range`, `empty`, `json_decode`. Граница `[1, 10]` стоит в schema, но `final_score=1` и `final_score=10` не покрыты.
**Что сделать**: два параметризованных теста на boundary 1 и 10.

### D12. test_scoring_strategy vs test_scoring_dispatcher — граница чистая — info
**Где**: [tests/test_scoring_strategy.py](../tests/test_scoring_strategy.py), [tests/test_scoring_dispatcher.py](../tests/test_scoring_dispatcher.py).
**Что**: strategy = pure unit, dispatcher = integration через `run_scoring` + tmp_path. Пересечений нет.
**Что сделать**: ничего; зафиксировать назначение в module docstring.

---

## Что чисто, и стоит зафиксировать

- `old/`, `full/`, `compact/` папки промптов удалены полностью.
- `_legacy`/`consolidated_*` fixtures в тестах не осталось.
- D15 fallback header в `fluency.md` снят, как и обещано в D16 changelog.
- `JudgeConfig.variant` миграция завершена (нет осиротевших `variant:` в YAML).
- Path leakage вне `paths.py` есть только в aggregation-функциях `scoring.py` (см. [A2](#a2)); в `scripts/` хардкодов путей нет.

---

## Рекомендованный порядок чинения

**Перед мержем в feat/project** (HIGH + критичные MED):

1. [C4](#c4) — fail-loud KeyError для API key.
2. [D1](#d1) — выровнять `fluency.md` по структуре и переименовать `suggested_improvement` → `suggestion`.
3. [B5](#b5) — `load_prompts` filter / whitelist.
4. [B4](#b4) — явные `supports_structured_output: false` для local vLLM (или комментарий).
5. [B6](#b6) — `warnings.warn` вместо `print(stderr)` в validator.
6. [C7](#c7) — atomic rename для `build_merged_jsonl`.
7. [D9](#d9) — тест на D16 toggle (response_format gating end-to-end).
8. [D7](#d7) — fix docstring «Stage 04» → «Stage 03» (1 секунда).

**Следующий рефакторинг-PR** (архитектура):

9. [A1](#a1) + [A2](#a2) — разрезать `scoring.py` на подпакет, унести pathи в `paths.py`.
10. [B7](#b7) / [C5](#c5) — убрать дубль `LLMConfig` ↔ `ModelConfig`.
11. [A7](#a7) — общий runner-каркас для дисptcher'ов.
12. [B1](#b1) — config bloat: defaults block / `_base.yaml`.

**Чистка / housekeeping**:

13. [D6](#d6) — удалить `03_cleanup_minus_one.py` после применения миграции.
14. [D5](#d5) — заменить hardcoded bucket list на glob.
15. [D8](#d8) — `--force` → `scoring.clear_run()`.
16. [B9](#b9) — снять prompts-snapshot из meta.json.

**Остальное** — LOW-нитпики, можно по мере касания.
