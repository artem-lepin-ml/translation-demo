# APPROVED — 2026-07-05-model-comparison

Owner approval given in chat, 2026-07-05 (batch Q&A):

1. Corpus: **full v2-100 for all models** (GT built in background).
2. Candidate model takes **both roles** — extractor and judge.
3. Baseline `google/gemini-3.1-flash-lite@provider-9` included as the 4th comparison row.
4. Hard budget cap: **$60** for the whole experiment.

5. LLM-concurrency cap for the matrix runs raised **4 → 16 per process** (owner answer, 2026-07-05,
   after ticket 002b measured ~6 s real per-call latency → cap-4 meant ~14 h/model).

Execution mode: autonomous through the final report (owner directive in the same conversation).
