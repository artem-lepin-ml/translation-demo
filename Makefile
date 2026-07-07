.PHONY: install fmt test parse reseed serve

install:
	uv sync --extra dev

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -q

parse:
	uv run python scripts/01_parse_pdf.py $(FILE)

# Canonical demo reseed: fresh demo.db from seed_paragraphs.jsonl, then the real
# disambiguated Term[] (terminology_out.json) loaded over the mock rotation.
reseed:
	uv run python -m palimpsest.webapp.seed
	uv run python scripts/load_terms.py

serve:
	uv run uvicorn palimpsest.webapp.app:app --port 8000 --workers 1
