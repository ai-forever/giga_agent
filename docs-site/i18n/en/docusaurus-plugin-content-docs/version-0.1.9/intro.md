---
title: "GigaAgent overview"
description: "What GigaAgent 0.1.9 is and where to start."
---

# GigaAgent overview

:::info[Stable PyPI documentation]
This page describes the published PyPI package `giga-agent==0.1.9`. For the repository state, switch to version **main**.
:::

`giga-agent==0.1.9` is a modular agent package. It installs as `giga-agent`, exposes the `giga_agent` command, and serves both the API and the bundled web UI through `giga_agent dev` on port `9090`.

## Main parts

| Part | Purpose |
|---|---|
| `giga_agent` Python package | CLI command, backend, graph, modules, and migrations. |
| Web UI | Chat, settings, RAG collections, memory, administration, and files. |
| Execution graph | Controls model calls, tool calls, streaming, and callbacks. |
| Modules | Add authentication, RAG, Mem0 memory, search, images, integrations, and compatibility subagents. |

Start with [Local quickstart](./quickstart/local.md), then configure a model in [First chat](./quickstart/first-chat.md).

## Added after 0.1.9

Development continues on the `main` branch, and some capabilities are not part of the `giga-agent==0.1.9` package:

- projects — grouping conversations around shared instructions and a dedicated knowledge base;
- a stop button for responses and per-user limits;
- connecting external services via OAuth: Yandex Mail, Yandex Calendar, Yandex Disk;
- a connections catalog with managed MCP servers;
- interactive chat widgets: inbox, calendar, files;
- scheduled tasks;
- channels: talking to the agent through Telegram;
- clarifying questions from the agent.

These capabilities are covered in the **main** version of the documentation — switch the version in the dropdown at the top of the page. The 0.1.9 documentation has no pages for them: installing the package from PyPI does not include them.
