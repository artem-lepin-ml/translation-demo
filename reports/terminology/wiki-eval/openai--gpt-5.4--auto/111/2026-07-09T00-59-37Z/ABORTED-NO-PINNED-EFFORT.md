# Aborted: no article checkpointed, effort was implicit (not pinned)

This run dir was created 2026-07-09T00:59:37Z and killed at ~01:04Z after the
owner's new hard rule landed (GPT/Claude models require explicit,
demonstrably-honored `reasoning_effort`). No article had been checkpointed
(`progress.jsonl`/`pred.partial.jsonl` never existed) — zero recoverable
work, safe to abandon rather than resume.

Effort-settability probe (`docs/reports/ml-engineer-grounding-run-gpt54.md`)
found the implicit default (no `reasoning_effort` sent, which is what this
aborted run used) produces reasoning_tokens close to the explicit "low" arm
(~204 vs ~205-233 mean), not "medium" — so per the coordinator's own
branching rule this warranted a FRESH timestamped run with the parameter
pinned explicitly, not a resume of this dir. See the fresh run dir
(sibling under `../111/`) and the report above for the full probe evidence
and the continuation.
