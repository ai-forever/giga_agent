---
title: "Docker quickstart"
description: "Run GigaAgent with supporting services through Docker Compose."
---

# Docker quickstart

Docker Compose is useful when you want a server-like setup with separate services: nginx, PostgreSQL, Redis, and Qdrant. For a minimal local chat, use [Local quickstart](./local.md).

## When to choose Docker Compose

Use this path to test PostgreSQL, Qdrant-backed RAG and memory, nginx routing, persistent volumes, or container-based sandbox execution.

## Services

| Service | Purpose |
|---|---|
| `nginx` | Serves the UI and proxies backend requests. |
| `giga-agent` | GigaAgent backend and LangGraph API. |
| `giga-agent-postgres` | Application database. |
| `langgraph-postgres` | LangGraph database. |
| `langgraph-redis` | Queues, cache, and locks. |
| `qdrant` | Vector store for RAG and memory. |

Nginx is published on `http://localhost:8123`.

## Prepare environment

```bash
cp .env.example .env
```

Set at least:

```env
GIGA_AGENT_SECRET_KEY=<long-random-value>
GIGA_AGENT_HOST_PROJECT_PATH=<absolute-project-path>
```

`GIGA_AGENT_HOST_PROJECT_PATH` is needed for local Docker sandbox scenarios.

## Run

```bash
docker compose up --build
```

Or use:

```bash
make build
make up
```

## Important limits

Docker Compose uses data volumes, and the `giga-agent` container can mount the host Docker socket. Treat that socket as a privileged boundary.
