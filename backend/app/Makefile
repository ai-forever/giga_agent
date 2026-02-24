# Makefile for giga_agent library development
# These commands are for library developers, not end users.

# =============================================================================
# Core Models Migrations (for library developers only)
# =============================================================================

# Create a new migration for core models (giga_agent/models)
# Usage: make core-migrations m="add users table"
core-migrations:
	uv run python -m giga_agent.scripts.make_core_migration -m "$(m)"

# Run arbitrary Alembic commands with core migration settings
# Usage:
#   make core-alembic args="upgrade head"
#   make core-alembic args="downgrade -1"
#   make core-alembic args="history"
#   make core-alembic args="current"
#   make core-alembic args="heads"
core-alembic:
	uv run python -m giga_agent.scripts.core_alembic $(args)

# =============================================================================
# Linting & Formatting
# =============================================================================

PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=backend/app/giga_agent --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	uv run ruff check .
	uv run ruff format $(PYTHON_FILES) --diff

format format_diff:
	uv run ruff format $(PYTHON_FILES)
	uv run ruff check --fix $(PYTHON_FILES)

# =============================================================================
# Testing
# =============================================================================

test:
	uv run pytest

test-cov:
	uv run pytest --cov=giga_agent --cov-report=html

# =============================================================================
# Development
# =============================================================================

# Run development server with test agent
dev:
	uv run giga_agent dev
