# Agent memory

Per-agent persistent state for agents declared with `memory: project` in their
`.claude/agents/*.md` frontmatter (e.g. `experiment-runner` writes
`.claude/agent-memory/experiment-runner/MEMORY.md`). Committed as text — this
is canonical memory, not a cache; see `docs/superpowers/specs/` for the memory
architecture spec.
