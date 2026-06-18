---
title: "Local quickstart"
description: "Install and run the current repository build."
---

# Local quickstart

:::info Current/main
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

Use this path when you want the current repository state rather than the released PyPI package.

## Requirements

- Python 3.11 or newer; Python 3.12 is recommended for local reproducibility.
- `uv` for a separate environment.
- Git.
- Free local port `9090`.

## Run in a few minutes

```bash
git clone https://github.com/trashchenkov/giga_agent.git
cd giga_agent
uv venv --python python3.12 .venv
source .venv/bin/activate
uv pip install -e "backend[jupyter]"
giga_agent dev
```

Open:

```text
http://localhost:9090
```

The first start can take time while dependencies, a local secret key, migrations, and the development server are prepared.

## First login

| Field | Value |
|---|---|
| Email | `admin@example.com` |
| Password | `giga_agent_admin` |

For a shared server, replace the password and set an explicit secret key.

## Migration check

```bash
giga_agent migrate
giga_agent check
```

If `check` runs before migrations on an empty database, apply migrations and run the check again.

## Useful URLs

| URL | Purpose |
|---|---|
| `http://localhost:9090/` | Web UI. |
| `http://localhost:9090/app-config.js` | Runtime UI configuration. |
| `http://localhost:9090/api/info` | LangGraph server information. |
| `http://localhost:9090/api/agent/...` | GigaAgent routes. |
