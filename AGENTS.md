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

### Key gotchas

- The dev server stores its state in `backend/.giga_agent/` (SQLite DB, secret key, sandbox state). This directory is auto-created on first run.
- `rsync` must be installed for `make ui-sync` to work.
- The backend `pyproject.toml` is in `backend/`, not the repo root.
- An LLM provider API key (e.g. `OPENAI_API_KEY`) must be configured for the agent to process chat messages. Without it, the UI loads and login works but chat requests fail.
