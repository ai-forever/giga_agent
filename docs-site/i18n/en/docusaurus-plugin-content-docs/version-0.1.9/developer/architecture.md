---
title: "Architecture"
description: "Backend, UI, graph, modules, and API structure in GigaAgent 0.1.9."
---

# Architecture

GigaAgent uses a FastAPI backend, a LangGraph execution graph, a module system, and a bundled React UI.

The default graph path is `giga_agent.agents.run:graph:app`. The package registers the main `giga_agent` graph and compatibility subgraphs: `landing`, `presentation`, `meme`, `lean_canvas`, and `podcast`.

Inside FastAPI, routes start with `/agent`. Through `giga_agent dev`, browser calls usually use `/api/agent/...`. Examples include `/api/agent/auth/token`, `/api/agent/files`, `/api/agent/rag/collections`, and `/api/agent/mem_zero_memory/memories`.
