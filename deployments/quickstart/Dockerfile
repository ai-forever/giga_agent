FROM node:22-bookworm-slim AS frontend

USER root

WORKDIR /front

COPY front/package.json front/package-lock.json ./
RUN npm ci

COPY front/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV BROWSER_PATH=/usr/bin/chromium
ENV GIGA_AGENT_PROJECT_ROOT=/data/.giga_agent

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    chromium \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY README.md ./README.md
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/hatch_build.py ./backend/hatch_build.py
COPY backend/hatch_metadata.py ./backend/hatch_metadata.py
COPY backend/giga_agent/ ./backend/giga_agent/
COPY --from=frontend /front/dist ./front/dist

RUN pip install "./backend[jupyter]"

EXPOSE 9090
VOLUME ["/data/.giga_agent"]

CMD ["giga_agent", "dev", "--host", "0.0.0.0", "--no-reload"]
