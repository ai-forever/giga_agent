---
title: "Architecture"
description: "Backend, UI, graph, modules, and API structure."
---

# Architecture

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

The current branch uses a FastAPI backend, a LangGraph execution graph, a module system, and a bundled React UI.

## Layers

```text
Browser and web UI
  ├─ page: /
  ├─ runtime UI config: /app-config.js
  └─ external API prefix: /api
LangGraph development server (`giga_agent dev`)
  ├─ LangGraph routes: /api/...
  └─ GigaAgent routes: /api/agent/...
GigaAgent FastAPI app
  ├─ internal prefix: /agent
  ├─ core routes: /agent/files, /agent/connectors, /agent/llms, ...
  ├─ module routes: /agent/{module.id}/...
  └─ BaseAgent + BaseModule + LangGraph graph
Providers
  ├─ language model and embeddings
  ├─ sandbox runtime
  ├─ search
  └─ image generation
```

## Graphs and subgraphs

The default graph path is `giga_agent.agents.run:graph:app`. Current `main` registers the main `giga_agent` graph, `deep_research`, and compatibility subgraphs: `landing`, `presentation`, `meme`, `lean_canvas`, and `podcast`.

## API prefixes

Inside FastAPI, routes start with `/agent`. Through `giga_agent dev`, browser calls usually use `/api/agent/...`.
