---
title: "Overview"
description: "What GigaAgent is and where to start."
---

# GigaAgent overview

GigaAgent is a modular agent framework with a FastAPI backend, a LangGraph execution graph, and a bundled React web UI. The `giga_agent dev` command starts a local server on port `9090` and serves both the API and the UI.

## Main parts

| Part | Purpose |
|---|---|
| `giga_agent` Python package | CLI command, backend, execution graph, modules, and migrations. |
| Web UI | Chat, settings, RAG collections, memory, administration, and files. |
| Execution graph | Controls model calls, tool calls, streaming, and callbacks. |
| Modules | Add authentication, RAG, memory, search, images, file operations, skills, deep research, and integrations. |
| Providers | Language models, embeddings, search, image generation, and sandbox runtimes. |

## What the agent can do

Useful work requires a configured language model. Depending on user settings, the current branch can use chat streaming with clarifying questions, files, RAG, long-term memory, agent skills, deep research, images, code execution, weather, search, and compatibility subagents.

External services connect through the [connectors catalog](./user-guide/connectors.md): MCP servers, [Yandex Mail, Calendar, and Disk](./user-guide/yandex-services.md), VK, GitHub. Results of some tools render as [chat widgets](./user-guide/widgets.md). The agent also runs [scheduled tasks](./user-guide/scheduler.md) with delivery to a [Telegram channel](./user-guide/channels.md).

## Start here

1. Install and run the repository build: [Local quickstart](./quickstart/local.md).
2. Configure a model and send the first message: [First chat](./quickstart/first-chat.md).
3. Review feature prerequisites: [Capabilities and requirements](./user-guide/capabilities.md).
4. For shared installations, read [Shared server](./operations/shared-server.md).
5. For implementation details, read [Architecture](./developer/architecture.md).
