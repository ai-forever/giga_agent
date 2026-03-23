# AGENTS.md

## Cursor Cloud specific instructions

### Overview

GigaAgent is a universal AI agent framework with a Python/FastAPI backend and React/Vite frontend. In local dev mode it uses SQLite (no external DB required).

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| Backend (dev) | `cd backend && uv run giga_agent dev` | 9090 | Serves API + bundled frontend UI; uses SQLite in `.giga_agent/` |
| Frontend (dev) | `cd front && npm run dev` | 3000 | Vite dev server; proxies `/api` to `localhost:9090` |

### Running services

1. Start the backend first — it runs migrations automatically on startup.
2. The backend at `:9090` serves the built frontend bundle, so a separate frontend dev server is only needed when actively developing frontend code.
3. Default login after first init: `admin@example.com` / `giga_agent_admin`.
4. Sending a chat message will error unless at least one LLM connector is configured in Settings.

### Lint / Test / Build

See `backend/AGENTS.md` section 2 for full command reference. Quick summary:

- **Backend lint:** `cd backend && uv run ruff check .`
- **Backend format:** `cd backend && uv run ruff format .`
- **Backend tests:** `cd backend && uv run pytest`
- **Frontend format check:** `cd front && npm run format:check`
- **Frontend build:** `cd front && npm run build`

### Gotchas

- The backend build hook (`backend/hatch_build.py`) requires the frontend bundle to exist at `front/dist` or `backend/giga_agent/ui_dist`. Build the frontend (`cd front && npm ci && npm run build`) before running `uv sync` in the backend directory.
- The `uv` package manager must be installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`); it is not part of the standard system packages.
- Python 3.12 is required (see `backend/.python-version`).
- Node.js 22 is required for the frontend.
- Auth API endpoint is `/api/agent/auth/token` (OAuth2 form POST with `username` + `password`), not `/api/auth/token`. Module routes are prefixed with `/agent/{module.id}`.
- The backend has ~53 pre-existing ruff lint warnings and 1 pre-existing test failure (`test_patch_user_by_id_returns_422_for_self_flags_update`). These are not caused by new changes.
