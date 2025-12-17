install:
	uv sync

run:
	uv run uvicorn app.main:app --reload --port 9090

run_u:
	uv run uvicorn app.upload_server:app --reload --port 9092

PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=backend/graph/giga_agent --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	uv run ruff check .
	uv run ruff format $(PYTHON_FILES) --diff

format format_diff:
	uv run --all-groups ruff format $(PYTHON_FILES)
	uv run --all-groups ruff check --fix $(PYTHON_FILES)