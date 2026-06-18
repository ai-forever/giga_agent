---
title: "Configuration"
description: "Environment variables and defaults."
---

# Configuration

:::info Current documentation
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

Environment variable names are kept as code because they are used in commands and `.env` files.

## Base settings

| Variable | Default | Purpose |
|---|---:|---|
| `GIGA_AGENT_PREFIX_API` | `/agent` | Internal API prefix. |
| `GIGA_AGENT_BASE_URL` | empty | Public base URL. |
| `GIGA_AGENT_FRONTEND_DIR` | empty | Override UI directory. |
| `GIGA_AGENT_UI` | `true` | Serve the bundled UI. |
| `GIGA_AGENT_RUNTIME` | `local` | Runtime mode. |
| `GIGA_AGENT_DATABASE_URL` | empty | SQLAlchemy database URL; SQLite is used by default. |
| `GIGA_AGENT_SECRET_KEY` | empty | Authentication secret; set explicitly for shared servers. |
| `GIGA_AGENT_LANGGRAPH_DEV_PORT` | `9090` | Development server port. |

## Tools and providers

`GIGA_AGENT_TOOL_MAX_SIZE`, `GIGA_AGENT_ENABLE_THINK_TOOL`, `GIGA_AGENT_ENABLE_MULTI_TOOL_USE`, `GIGA_AGENT_SCRAPER_TOTAL_CONCURRENCY`, and `GIGA_AGENT_QDRANT_POOL_SIZE` control tool output, service tools, scraping, and vector storage behavior.
