---
title: "Architecture"
description: "Backend, UI, graph, modules, and API structure in GigaAgent 0.1.9."
---

# Architecture

:::info[Stable PyPI documentation]
This page describes the published PyPI package `giga-agent==0.1.9`. For the repository state, switch to version **main**.
:::

GigaAgent 0.1.9 uses a FastAPI backend, a LangGraph execution graph, a module system, and a bundled React UI.

The default graph path is `giga_agent.agents.run:graph:app`. Version 0.1.9 registers the main `giga_agent` graph and compatibility subgraphs: `landing`, `presentation`, `meme`, `lean_canvas`, and `podcast`.

Inside FastAPI, routes start with `/agent`. Through `giga_agent dev`, browser calls usually use `/api/agent/...`. Examples include `/api/agent/auth/token`, `/api/agent/files`, `/api/agent/rag/collections`, and `/api/agent/mem_zero_memory/memories`.
