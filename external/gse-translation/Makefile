.PHONY: install fmt test parse pipeline judge serve

install:
	uv sync --extra dev

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -q

parse:
	uv run python scripts/01_parse_pdf.py $(FILE)

pipeline:
	uv run python scripts/02_run_pipeline.py

judge:
	uv run python scripts/03_run_judge.py

serve:
	uv run python scripts/04_serve_webapp.py
