# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

GigaAgent is a universal AI agent chat application. It runs as a set of Docker containers orchestrated via Docker Compose. See `README.md` for full documentation.

### Running the application

The entire stack runs via Docker Compose. A `.docker.env` file must exist in the repo root with at least `OPENAI_API_KEY` set (or GigaChat credentials). An env template is at `env_examples/openai/.docker.env.example`.

**Dev mode** (hot-reload for backend + frontend):
```
make init_files     # one-time: copies mock data into ./files/
make build_dev      # builds Docker images
make up_dev         # starts all containers
```
App is accessible at `http://localhost:8502`. Frontend dev server with HMR is also on port 8081.

**Production mode**: `make build && make up` (no hot-reload).

### Services

All services are Docker containers. Key ones:
- `langgraph-api` (port 8000 internal) — core LangGraph agent server
- `repl` (port 9090 internal) — Jupyter REPL for code execution
- `tool_server` (port 9091 internal) — proxy server for tools with secrets
- `giga_agent_server` (port 8822 internal) — tasks API
- `upload_server` (port 9092 internal) — file uploads
- `frontend` (port 8502) — Nginx reverse proxy serving the React SPA
- `frontend-dev` (port 8081, dev mode only) — Vite dev server
- `aegra-postgres`, `langgraph-redis`, `qdrant` — data stores

### Linting

- **Python backend** (`backend/graph/`): `cd backend/graph && uv run ruff check .` (install lint group first: `uv sync --group lint`)
- **Python REPL** (`backend/repl/`): `cd backend/repl && uv run ruff check .` (install lint group: `uv sync --group lint`)
- **Frontend** (`front/`): `cd front && npx eslint src/`
- **Frontend formatting**: `cd front && npm run format:check`

### Building

- **Frontend**: `cd front && npm run build` (runs `tsc` then `vite build`)
- **Docker images**: `make build` or `make build_dev`

### Non-obvious caveats

- The `backend/graph/Dockerfile` uses base image `mikelarg/aegra:0.0.7` which is a custom LangGraph Platform replacement. It includes its own venv and alembic migrations.
- `ruff` is in a separate dependency group (`lint`). You must run `uv sync --group lint` before `uv run ruff check .` works.
- The `.docker.env` file is required but gitignored. Copy from `env_examples/openai/.docker.env.example` or `env_examples/gigachat/.docker.env.example` and fill in API keys.
- `make init_files` must be run once to populate the `./files/` directory with mock data before containers can start properly.
- Docker containers need `sudo` if the current user isn't in the `docker` group.
- Optional service API keys (Tavily, VK, GitHub, etc.) auto-disable their corresponding tools when not set — the app still works without them.
- The `GIGA_AGENT_MEMORY_ENABLED=1` env var enables Qdrant-based long-term memory. Set to `0` to disable.
- In the Cloud VM, Docker must be started with `sudo dockerd` and configured with `fuse-overlayfs` storage driver and `iptables-legacy`.
