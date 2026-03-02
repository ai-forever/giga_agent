# GigaAgent Development

## Cursor Cloud specific instructions

### Overview

GigaAgent is a multi-agent AI chat application built on LangGraph / GigaChain. The entire stack runs in Docker via `docker compose`. See `README.md` for full documentation (in Russian).

### Services

All services are orchestrated via `docker-compose.yml` (production) and `docker-compose.dev.yml` (development overlay with hot-reload). Development mode uses `make build_dev` + `make up_dev`.

| Service | Port | Notes |
|---------|------|-------|
| frontend (Nginx proxy) | 8502 (host) | Proxies to Vite dev server |
| frontend-dev (Vite) | 8081 (host) | Hot-reload React/Vite |
| langgraph-api (Aegra) | 8000 (internal) | Core agent backend, runs Alembic migrations on start |
| repl (Jupyter kernel) | 9090 (internal) | Code execution sandbox |
| upload_server | 9092 (internal) | File upload for REPL outputs |
| tool_server | 9091 (internal) | Proxies tool calls with secrets |
| giga_agent_server | 8822 (internal) | Background tasks API |
| aegra-postgres | 5432 (internal) | PostgreSQL 16 state store |
| langgraph-redis | 6379 (internal) | Redis 6 message queue |
| qdrant | 6333 (internal) | Vector DB (optional, for RAG) |

### Environment setup

- `.docker.env` must exist in the repo root before `make build_dev` / `make up_dev`. Copy from `env_examples/openai/.docker.env.example` or `env_examples/gigachat/.docker.env.example` and fill in API keys.
- Run `make init_files` once to copy mock data into `files/`.
- GigaChat auth supports two modes: `GIGACHAT_CREDENTIALS` (OAuth token) OR `GIGACHAT_USER` + `GIGACHAT_PASSWORD` (basic auth). Both work; set the same creds for `MAIN_GIGACHAT_*` vars too.
- If using `GIGACHAT_BASE_URL`, set it in `.docker.env` as well as `MAIN_GIGACHAT_BASE_URL`.
- Without a valid LLM key, the UI loads and accepts messages but returns an error.

### Lint / Format / Build

| Component | Lint | Format | Build |
|-----------|------|--------|-------|
| `backend/graph` | `cd backend/graph && uv run ruff check .` | `cd backend/graph && make format` | N/A (Docker-only) |
| `backend/repl` | `cd backend/repl && uv run ruff check .` | `cd backend/repl && make format` | N/A (Docker-only) |
| `front` | `cd front && npx eslint src/` | `cd front && npm run format` | `cd front && npm run build` |
| `front` (format check) | `cd front && npm run format:check` | | |

### Docker gotchas

- This cloud VM runs Docker-in-Docker with `fuse-overlayfs` storage driver and `iptables-legacy`. These are configured in `/etc/docker/daemon.json` and via `update-alternatives`.
- The `dockerd` daemon must be running: `sudo dockerd &>/tmp/dockerd.log &`
- Use `sudo docker compose ...` or add your user to the `docker` group.
- First build pulls large base images (postgres:16, redis:6, qdrant, mikelarg/aegra:0.0.7). Subsequent builds use the cache.
