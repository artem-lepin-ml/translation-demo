# Production image for the Palimpsest demo webapp (API + built frontend).
# Build context = repo root; frontend/dist must be built beforehand (npm run build).
FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
# Editable install keeps the package under /app/src so paths.ROOT resolves to /app
# (prompts/, data/ are looked up relative to it).
RUN pip install --no-cache-dir -e .

COPY prompts ./prompts
COPY glossary ./glossary
COPY frontend/dist ./frontend/dist

ENV DEMO_STATIC_DIR=/app/frontend/dist \
    PALIMPSEST_DB=/data/demo.db \
    PALIMPSEST_BUDGET_LOG=/data/budget_calls.jsonl

EXPOSE 8000
CMD ["uvicorn", "palimpsest.webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]
