run_tool_server:
	uv run uvicorn giga_agent.tool_server.tool_server:app --reload --port 8811

run_graph:
	uv run langgraph dev --no-browser

run_giga_agent_api:
	uv run uvicorn giga_agent.tasks_app:app --reload --port 8822

PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=backend/graph/giga_agent --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	uv run ruff check .
	uv run ruff format $(PYTHON_FILES) --diff

format format_diff:
	uv run --all-groups ruff format $(PYTHON_FILES)
	uv run --all-groups ruff check --fix $(PYTHON_FILES)