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

### Runtime Resolver & CLI mode

Runtimes (LLM, embedding, sandbox, search engine, image generator) are resolved through `RuntimeResolver` (`backend/giga_agent/core/agent/runtime_resolver.py`). There are two modes:

- **DB mode** (default, `GIGA_AGENT_RUNTIME=local|docker`): Runtimes are loaded from the database via user's `*_id` fields.
- **CLI mode** (`GIGA_AGENT_RUNTIME=cli`): Runtimes are loaded from `giga_agent.conf.json` (searched in CWD, then `.giga_agent/`). No DB user lookup — a synthetic `UserShort` with `is_synthetic=True` is created. See `CliRuntimeResolver` in the same file.

**When adding a new runtime type** (e.g. a new kind of generator, tool provider, etc.):

1. Add a `has_<runtime>` property to `RuntimeResolver` (checks `user.*_id`).
2. Override that property in `CliRuntimeResolver` (checks `conf.*`).
3. Add a `get_<runtime>()` method to both classes (DB-based in `RuntimeResolver`, registry-based in `CliRuntimeResolver`).
4. If the new runtime needs a config entry, add a Pydantic model to `cli_conf.py` and a field to `CliRuntimeConf`.
5. Modules should check runtime availability via `resolver.has_<runtime>` (obtained from `RuntimeResolver.from_config(config)`), **not** via `user.*_id` directly.

**`giga_agent.conf.json` format** — flat, user-friendly; uses `__type` as discriminator, extra keys become settings:

```json
{
  "llm": {
    "connector": { "__type": "openai", "api_key": "sk-..." },
    "__type": "openai",
    "model_id": "gpt-4o"
  },
  "fast_llm": null,
  "embedding": null,
  "sandbox": "local_jupyter",
  "search_engine": null,
  "image_generator": null,
  "user_settings": {}
}
```

This file contains secrets and is in `.gitignore`.

### Gotchas

- The backend build hook (`backend/hatch_build.py`) requires the frontend bundle to exist at `front/dist` or `backend/giga_agent/ui_dist`. Build the frontend (`cd front && npm ci && npm run build`) before running `uv sync` in the backend directory.
- The `uv` package manager must be installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`); it is not part of the standard system packages.
- Python 3.12 is required (see `backend/.python-version`).
- Node.js 22 is required for the frontend.
