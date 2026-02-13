# Universal single-container Dockerfile for DigitalOcean App Platform
# Runs all GigaAgent services in one container via supervisord:
#   nginx (80), redis (6379), langgraph-api (8000), tool-server (9091),
#   tasks-api (8822), repl (9090), upload-server (9092)
#
# Build context: repository root (source_dir: / in app spec)

# ============================================================
# Stage 1: Build frontend
# ============================================================
FROM node:22.12.0-alpine AS frontend-builder
WORKDIR /build

COPY front/package.json front/package-lock.json ./
RUN npm ci

ARG VITE_LANGCONNECT_API_URL
ARG VITE_LANGCONNECT_API_SECRET_TOKEN
ARG VITE_MCP_PROXY_URL
ARG VITE_MEMORY_ENABLED
ENV VITE_LANGCONNECT_API_URL=$VITE_LANGCONNECT_API_URL
ENV VITE_LANGCONNECT_API_SECRET_TOKEN=$VITE_LANGCONNECT_API_SECRET_TOKEN
ENV VITE_MCP_PROXY_URL=$VITE_MCP_PROXY_URL
ENV VITE_MEMORY_ENABLED=$VITE_MEMORY_ENABLED

COPY front/ .
RUN npm run build

# ============================================================
# Stage 2: Runtime — aegra base + all services
# ============================================================
FROM mikelarg/aegra:0.0.7

USER root

# --- System packages: nginx, supervisord, redis, postgres, ffmpeg, nodejs ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx supervisor redis-server \
        postgresql \
        ffmpeg libavcodec-extra \
        curl ca-certificates \
        build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

# --- PostgreSQL: trust auth on localhost, ensure runtime dirs ---
RUN PG_VERSION=$(ls /usr/lib/postgresql/) \
    && sed -i 's/scram-sha-256/trust/g' /etc/postgresql/${PG_VERSION}/main/pg_hba.conf \
    && sed -i 's/peer/trust/g' /etc/postgresql/${PG_VERSION}/main/pg_hba.conf \
    && mkdir -p /var/run/postgresql \
    && chown -R postgres:postgres /var/run/postgresql /var/lib/postgresql

RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

# --- uv package manager ---
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
RUN mv /root/.local/bin/uv /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

# ============================================================
# Graph venv  (langgraph-api, tool-server, tasks-api)
# Matches backend/graph/Dockerfile layout exactly
# ============================================================
WORKDIR /

COPY backend/graph/pyproject.toml /pyproject.toml
COPY backend/graph/uv.lock        /uv.lock
COPY backend/graph/README.md       /README.md

RUN uv venv --system-site-packages
RUN uv sync --locked

ENV PATH="/.venv/bin:/app/.venv/bin:$PATH"

WORKDIR /app
COPY backend/graph/giga_agent ./giga_agent
COPY backend/graph/langgraph.json  ./aegra.json

# ============================================================
# Repl venv  (repl, upload-server)
# Isolated at /opt/repl so it does not conflict with graph deps
# ============================================================
WORKDIR /opt/repl

COPY backend/repl/pyproject.toml ./pyproject.toml
COPY backend/repl/uv.lock        ./uv.lock

RUN uv venv && uv sync --locked

COPY backend/repl/app/ ./app/
RUN touch ./__init__.py

# ============================================================
# Directories & jupyter user
# ============================================================
RUN mkdir -p /files /runs /kernel_states /home/jupyter /db /mnt /var/cache/uv

RUN useradd -ms /bin/bash jupyter \
    && chown -R jupyter:jupyter \
        /mnt /home/jupyter /files /runs /kernel_states /db \
        /var/cache/uv /opt/repl/.venv

# ============================================================
# Frontend static files
# ============================================================
COPY --from=frontend-builder /build/dist /usr/share/nginx/html

# ============================================================
# Configuration files
# ============================================================
COPY .do/nginx.do.conf    /etc/nginx/conf.d/default.conf
COPY .do/supervisord.conf /etc/supervisor/conf.d/giga-agent.conf
RUN rm -f /etc/nginx/sites-enabled/default

# ============================================================
# Default environment — all services on localhost
# ============================================================
ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/postgres \
    LANGGRAPH_API_URL=http://127.0.0.1:8000/ \
    JUPYTER_CLIENT_API=http://127.0.0.1:9090 \
    JUPYTER_UPLOAD_API=http://127.0.0.1:9092 \
    TOOL_CLIENT_API=http://127.0.0.1:9091 \
    GIGA_AGENT_API=http://127.0.0.1:8822 \
    FRONT_BASE_URL=http://127.0.0.1/files \
    REDIS_URI=redis://127.0.0.1:6379 \
    AUTH_TYPE=noop \
    FILES_DIR=/files \
    RUNS_DIR=/runs \
    STATE_DIR=/kernel_states \
    PLOTLY_RENDERER=plotly_mimetype \
    MAX_KERNEL_LIVE=300 \
    GIGA_AGENT_MEMORY_ENABLED=0

EXPOSE 80

ENTRYPOINT []
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/giga-agent.conf"]
