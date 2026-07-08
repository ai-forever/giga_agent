---
title: "Modules"
description: "Active modules in GigaAgent 0.1.9 and the BaseModule contract."
---

# Modules

A module is a GigaAgent extension unit. It can add routes, database models, migrations, tools, system instructions, secrets, middleware, subgraphs, and startup handlers.

`giga_agent dev` in `giga-agent==0.1.9` loads 12 modules: `AuthModule`, `ReplModule`, `ImageModule`, `AnalyzeImagesModule`, `ScraperModule`, `SearchModule`, `RagModule`, `MemZeroModule`, `GitHubModule`, `VKModule`, `WeatherModule`, and `SubAgentLegacyModule`.

Module routes are mounted under `/agent/{module.id}`, or externally under `/api/agent/{module.id}` through `giga_agent dev`. The Mem0 memory route is available under `/api/agent/mem_zero_memory/memories`.
