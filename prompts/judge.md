# LLM-as-judge — six-criterion evaluation

Score the English translation against the Russian source on six criteria (each on a 1–5 scale, 5 = best). Then give a one-paragraph rationale.

- **accuracy** — semantic fidelity; facts, numbers, names unchanged.
- **terminology** — correct domain/academic term choice.
- **consistency** — same term rendered the same; steady register and tense.
- **fluency** — natural, grammatical English.
- **style** — encyclopedic voice; author's tone preserved.
- **culture** — realia adapted for an EN reader.

Return strict JSON — no prose outside the object:

```json
{"accuracy": 0, "terminology": 0, "consistency": 0, "fluency": 0, "style": 0, "culture": 0, "rationale": "..."}
```
