---
title: "Configuration"
description: "Environment variables and defaults."
---

# Configuration

:::info[Current documentation]
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

## Yandex OAuth application

Yandex integrations ([Mail, Calendar, Disk](../user-guide/yandex-services.md)) connect via OAuth. An administrator registers an application once at [oauth.yandex.ru](https://oauth.yandex.ru/) and provides its credentials through environment variables:

| Variable | Purpose |
|---|---|
| `YANDEX_OAUTH_CLIENT_ID` | The application identifier; shared by Calendar and Disk. |
| `YANDEX_OAUTH_CLIENT_SECRET` | The application secret. |
| `YANDEX_OAUTH_REDIRECT_URI` | An optional explicit callback address; without it, the address is assembled from `GIGA_AGENT_BASE_URL` and the API prefix. |
| `YANDEX_OAUTH_CLIENT_ID_YANDEX_MAIL` | A separate application for Mail: Yandex requires its own application for the mail scope. Without this pair, Mail uses the shared credentials above. |
| `YANDEX_OAUTH_CLIENT_SECRET_YANDEX_MAIL` | The mail application secret. |

Until the variables are set, the OAuth connect button in the [connectors catalog](../user-guide/connectors.md) stays inactive, and the service cards explain how to enable the application. Integrations keep working on manual tokens.

## Channels

Channel bots ([Telegram](../user-guide/channels.md)) are created in **Settings → Channels**: the channel type and the bot token are set in the form, with no environment variables involved. Contact access is granted manually — the bot stays silent until a contact is approved.

## Per-user limits

| Variable | Default | Purpose |
|---|---:|---|
| `GIGA_AGENT_MAX_ACTIVE_THREADS_PER_USER` | `5` | Maximum number of simultaneously active (busy) graph chats per user. `0` or less disables the limit. |
| `GIGA_AGENT_LOCAL_JUPYTER_MAX_KERNELS_PER_USER` | `5` | Maximum number of simultaneous local Jupyter kernels per user. When the limit is reached, the owner's least-recently-used kernel is evicted before a new one is created. `0` disables the limit. |
