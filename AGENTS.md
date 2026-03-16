# GigaAgent

## Cursor Cloud specific instructions

### Overview

GigaAgent is a full-stack conversational AI agent platform (LangGraph/LangChain) with 30+ tools/sub-agents. It runs entirely via Docker Compose with 8 required services: PostgreSQL 16, Redis 6, Aegra (LangGraph API server), REPL (Jupyter kernel), Upload Server, Tool Server, GigaAgent Server, and Frontend (Nginx + React).

### Running the application

All services run via Docker Compose. See `README.md` for the full quick-start guide.

```
make init_files        # Copy mock data to files/ (first time only)
make build_dev         # Build Docker images (dev mode with hot-reload)
make up_dev            # Start all services
make down_dev          # Stop all services
```

The frontend is accessible at `http://localhost:8502` (production Nginx proxy) and `http://localhost:8081` (Vite dev server with hot-reload).

### Environment configuration

Copy an env template from `env_examples/` to `.docker.env` in the project root. Two templates are available: `env_examples/openai/.docker.env.example` (OpenAI) and `env_examples/gigachat/.docker.env.example` (GigaChat). An LLM API key (e.g. `OPENAI_API_KEY`) is required for the agent to process messages; without it, the UI loads but chat requests fail with a 401 error.

### Linting

- **Frontend**: `cd front && npm run format:check` (Prettier)
- **Backend graph**: `cd backend/graph && make lint` (ruff check + format diff)
- **Backend REPL**: `cd backend/repl && make lint` (ruff check + format diff)

### Building

- **Frontend**: `cd front && npm run build` (TypeScript check + Vite build)

### Key gotchas

- The Aegra backend base image is `mikelarg/aegra:0.0.7` and runs Python 3.11. Local dev uses Python 3.12.9 (`.python-version`). Lint and local tooling use `uv` with the local Python version; Docker uses the Aegra image's Python.
- Docker daemon must be started manually in the VM: `sudo dockerd &` then `sudo chmod 666 /var/run/docker.sock`. Also requires `fuse-overlayfs` and `iptables-legacy` for nested Docker-in-Docker.
- The `make build_dev` step builds 4 Docker images and can take 2-3 minutes on first run.
- There are no automated tests in this project (noted in the roadmap). Lint is the primary code quality check.
