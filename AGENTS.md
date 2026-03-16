# GigaAgent

## Cursor Cloud specific instructions

### Overview

GigaAgent (v0.1-2 branch) is a modular AI agent framework with a unified Python backend and React frontend. It supports two run modes: **local dev** (SQLite, single process) and **Docker Compose** (PostgreSQL, Redis, Nginx).

### Running the application (local dev mode)

The fastest way to run GigaAgent for development:

```bash
cd backend
uv run giga_agent dev --host 0.0.0.0 --port 9090
```

This starts the LangGraph dev server with SQLite on port 9090. Default login: `admin@example.com` / `giga_agent_admin`.

For the UI to be served, the frontend must first be built and synced:

```bash
cd front && npx vite build
cd ../backend && make ui-sync
```

Note: `npm run build` (which runs `tsc && vite build`) has a pre-existing TypeScript error in `DemoChat.tsx`. Use `npx vite build` directly to skip the tsc check.

### Running via Docker Compose

```bash
cp .env.example .env   # fill in GIGA_AGENT_SECRET_KEY
make build && make up   # UI at http://localhost:8123
```

Dev variant with hot-reload: `make build_dev && make up_dev`.

Docker requires `fuse-overlayfs` and `iptables-legacy` in the cloud VM for nested Docker-in-Docker. Start Docker daemon: `sudo dockerd &` then `sudo chmod 666 /var/run/docker.sock`.

### Linting

- **Backend**: `cd backend && uv run ruff check .` (or `make lint` for check + format diff)
- **Frontend**: `cd front && npm run format:check` (Prettier)

Note: the v0.1-2 branch has pre-existing lint/format issues in both backend (55 ruff errors) and frontend (23 prettier warnings).

### Testing

- **Backend**: `cd backend && uv run pytest` (466 tests)
- No frontend tests exist.

### Project-specific AGENTS.md files

- `backend/AGENTS.md` — backend development rules, CLI commands, migration policies
- `front/AGENTS.md` — frontend API client conventions

### Configuring an LLM provider

Having `OPENAI_API_KEY` in the environment alone is **not sufficient**. The v0.1-2 branch uses a connector/LLM registry system. After starting the dev server, you must:

1. Get an auth token: `curl -s -X POST http://localhost:9090/api/agent/auth/token -F 'username=admin@example.com' -F 'password=giga_agent_admin'`
2. Create a connector: `POST /api/agent/connectors` with `{"type":"openai","name":"OpenAI","settings":{"api_key":"<key>"},"check_connection":false}`
3. Create an LLM: `POST /api/agent/llms` with `{"type":"openai","model_id":"gpt-4o-mini","connector_id":"<id>","check_connection":false}`
4. Assign LLM to user: `PATCH /api/agent/auth/users/me` with `{"llm_id":"<id>","fast_llm_id":"<id>"}`

Alternatively, configure these through the Settings page in the UI (`/settings/`).

### Key gotchas

- The dev server stores its state in `backend/.giga_agent/` (SQLite DB, secret key, sandbox state). This directory is auto-created on first run.
- `rsync` must be installed for `make ui-sync` to work.
- The backend `pyproject.toml` is in `backend/`, not the repo root.
- `npm run build` in `front/` fails due to a pre-existing TypeScript error in `DemoChat.tsx`. Use `npx vite build` to skip tsc.
- The agent uses a human-in-the-loop tool approval system. When a tool is invoked, the user must click the green checkmark to approve execution (or enable "Автономность" / Autonomy mode).
