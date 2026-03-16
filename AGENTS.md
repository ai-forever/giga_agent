# AGENTS.md

## Cursor Cloud specific instructions

### Quick start (returning after previous setup)

If Docker is already installed and images built from a previous session:
```bash
sudo dockerd &>/tmp/dockerd.log &    # start Docker daemon
sleep 5
cd /workspace && sudo docker compose up -d   # start all containers
```
App is at `http://localhost:8123`. Login: `admin@example.com` / `giga_agent_admin`.

If images need rebuilding (code changed):
```bash
cd /workspace/front && npm ci && npm run build
cp -r dist ../backend/giga_agent/ui_dist
cd /workspace && sudo docker compose build && sudo docker compose up -d
```

### Project overview

GigaAgent is a universal AI agent chat application. It runs as a set of Docker containers orchestrated via Docker Compose. See `README.md` for full documentation.

### Running the application

The entire stack runs via Docker Compose. A `.env` file must exist in the repo root (see `.env.example`). At minimum set `GIGA_AGENT_SECRET_KEY` and `GIGA_AGENT_HOST_PROJECT_PATH`.

**Production mode**:
```
make build    # builds Docker images (requires frontend pre-built, see below)
make up       # starts all containers
```

**Dev mode** (hot-reload for backend):
```
make build_dev
make up_dev
```

App is accessible at `http://localhost:8123`.

### Pre-build step: frontend dist

The backend Docker image (`deployments/local/Dockerfile`) expects the frontend to be pre-built. Before running `make build`, you must:
```
cd front && npm ci && npm run build
cp -r dist ../backend/giga_agent/ui_dist
```
Without this, the Docker build will fail with "UI bundle not found".

### Authentication

The app has user authentication. On first startup, an admin user is created automatically:
- Email: `admin@example.com`
- Password: `giga_agent_admin`

### First-time LLM configuration

After login, the agent requires LLM configuration via the API or UI settings. Without this, chat messages fail with "User has no default LLM configured". Configure via API:
1. Get token: `POST /api/agent/auth/token` with `username=admin@example.com&password=giga_agent_admin`
2. Create connector: `POST /api/agent/connectors` with type `openai` and `settings.api_key`
3. Create LLM: `POST /api/agent/llms` with connector_id and model_id (e.g. `gpt-4o-mini`)
4. Set default: `PATCH /api/agent/auth/users/me` with `llm_id`

### Services

All services are Docker containers:
- `giga-agent` (port 8000 internal) — unified backend: LangGraph agent + tasks API + tool server
- `nginx` (port 8123) — reverse proxy serving React SPA + backend API
- `langgraph-postgres` — PostgreSQL for Aegra state
- `giga-agent-postgres` — PostgreSQL for GigaAgent data
- `langgraph-redis` — Redis for pub/sub
- `qdrant` — vector DB for memory (optional)

### Linting

- **Python backend**: `cd backend && uv sync --group dev && uv run ruff check .`
- **Frontend**: `cd front && npx eslint src/`
- **Frontend formatting**: `cd front && npm run format:check`

### Building

- **Frontend**: `cd front && npm run build` (runs `tsc` then `vite build`)
- **Docker images**: `make build` or `make build_dev`

### Non-obvious caveats

- Backend is now a single package at `backend/` (not the old `backend/graph` + `backend/repl` split).
- The Dockerfile uses base image `mikelarg/aegra:0.0.9` with Alembic migrations baked in.
- `ruff` is in the `dev` dependency group: `uv sync --group dev` is needed before linting.
- The `.env` file is gitignored. Copy from `.env.example` and fill in secrets.
- `GIGA_AGENT_SECRET_KEY` must be set for JWT auth to work.
- The sandbox/REPL for code execution requires a sandbox provider (local Docker or E2B). Create one via the API: `POST /api/agent/sandboxes/providers` with `type=local_docker`.
- In the Cloud VM, Docker must be started with `sudo dockerd` and configured with `fuse-overlayfs` storage driver and `iptables-legacy`.
- The Cloud VM's cgroup v2 is in threaded mode, which prevents Docker containers from using memory cgroup limits. The env var `GIGA_AGENT_LOCAL_DOCKER_NO_CGROUP_LIMITS=true` in `docker-compose.yml` disables memory/CPU/pids cgroup limits for sandbox containers to work around this.
