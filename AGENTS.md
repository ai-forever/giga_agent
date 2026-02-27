# AGENTS.md

## Cursor Cloud specific instructions

### Overview

GigaAgent is a universal AI agent built on GigaChain/LangGraph. It uses Docker Compose to orchestrate ~10 services: PostgreSQL, Redis, LangGraph API (Aegra), REPL (Jupyter kernel), Upload Server, Tool Server, GigaAgent Server, Frontend (Nginx + React), and optionally Qdrant and a frontend dev server.

### Running the application

All services run via Docker Compose in dev mode. See the root `Makefile` for commands:
- `make build_dev` / `make up_dev` — build and start in dev mode (hot-reload)
- `make build` / `make up` — production mode
- `make down_dev` / `make down` — stop services

The app is accessible at `http://localhost:8502` (Nginx) or `http://localhost:8081` (Vite dev server direct).

A `.docker.env` file must exist in the repo root before running. Copy from `env_examples/openai/.docker.env.example` or `env_examples/gigachat/.docker.env.example` and fill in API keys. The app starts without API keys but LLM calls will fail.

Run `make init_files` once to copy mock CSV data into `./files/`.

### Docker in Cloud Agent VM

Docker requires special setup in Cloud Agent VMs (nested containers). Key steps already performed:
- `fuse-overlayfs` storage driver configured in `/etc/docker/daemon.json`
- `iptables-legacy` set as default (required for nested Docker networking)
- Docker daemon started with `sudo dockerd`

If Docker is not running, start it: `sudo dockerd &>/tmp/dockerd.log &`

All `docker` / `docker compose` commands require `sudo`.

### Lint

- **backend/graph**: `cd backend/graph && uv run ruff check . && uv run ruff format . --diff` (or `make lint`)
- **backend/repl**: `cd backend/repl && uv run ruff check . && uv run ruff format . --diff` (or `make lint`)
- **frontend**: `cd front && npx prettier --check "src"` (format check)

### Build

- **frontend**: `cd front && npm run build` (runs `tsc && vite build`)
- **Docker images**: `make build_dev` (from repo root)

### Tests

The codebase does not have automated tests yet (noted in README roadmap). Validate changes via lint + build + manual testing.

### Python dependency management

Both `backend/graph` and `backend/repl` use `uv` with lockfiles (`uv.lock`). Run `uv sync --all-groups` in each directory to install deps (including the `lint` dependency group for `ruff`).

### Frontend dependency management

The `front/` directory uses `npm` with `package-lock.json`. Run `npm install` in `front/`.

### Key gotchas

- The LangGraph API container (`langgraph-api`) runs Alembic DB migrations on startup. If it crashes on start, check PostgreSQL health first.
- The `giga_agent_server` container seeds demo task data into SQLite on startup.
- `LANGCONNECT_API_URL`, `LANGCONNECT_API_SECRET_TOKEN`, and `MCP_PROXY_URL` warnings during `docker compose` are harmless when those features are not used.
- The frontend Vite dev server (port 8081) proxies API calls to backend services. When running locally outside Docker, configure proxy targets in `front/vite.config.ts`.
