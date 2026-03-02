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
# UI (frontend bundle sync)
# =============================================================================

UI_DIST_SRC=../front/dist
UI_DIST_DST=giga_agent/ui_dist

# Sync built frontend (`front/dist`) into the python package (`giga_agent/ui_dist`)
ui-sync:
	@test -d "$(UI_DIST_SRC)" || (echo "Missing $(UI_DIST_SRC). Build frontend first (e.g. in ../front: npm ci && npm run build)." && exit 1)
	@mkdir -p "$(UI_DIST_DST)"
	@rsync -a --delete "$(UI_DIST_SRC)/" "$(UI_DIST_DST)/"

# Remove packaged UI bundle from the python package tree
ui-clean:
	@rm -rf "$(UI_DIST_DST)"

# =============================================================================
# Development
# =============================================================================

# Run development server with test agent
dev:
	uv run giga_agent dev
