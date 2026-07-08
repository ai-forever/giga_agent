---
title: "GigaAgent overview"
description: "What GigaAgent 0.1.9 is and where to start."
---

# GigaAgent overview

`giga-agent==0.1.9` is a modular agent package. It installs as `giga-agent`, exposes the `giga_agent` command, and serves both the API and the bundled web UI through `giga_agent dev` on port `9090`.

## Main parts

| Part | Purpose |
|---|---|
| `giga_agent` Python package | CLI command, backend, graph, modules, and migrations. |
| Web UI | Chat, settings, RAG collections, memory, administration, and files. |
| Execution graph | Controls model calls, tool calls, streaming, and callbacks. |
| Modules | Add authentication, RAG, Mem0 memory, search, images, integrations, and legacy subagents kept for compatibility (landing page, presentation, meme, and more). |

Start with [Local quickstart](./quickstart/local.md), then configure a model in [First chat](./quickstart/first-chat.md).
