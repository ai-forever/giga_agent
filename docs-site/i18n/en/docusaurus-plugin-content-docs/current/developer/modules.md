---
title: "Modules"
description: "Active modules and the BaseModule contract."
---

# Modules

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

A module is a GigaAgent extension unit. It can add routes, database models, migrations, tools, system instructions, secrets, middleware, subgraphs, and startup handlers.

## BaseModule contract

Important fields and methods include `id`, `label`, `description`, `icon`, `get_api_router()`, `get_models()`, `_get_tools()` / `get_tools()`, `get_instructions()`, `extend_task()`, `get_secrets()`, `get_middleware()`, `get_subgraphs()`, `is_enabled()`, and `on_startup()`.

## Active modules in current main

`giga_agent dev` loads 15 modules: `AuthModule`, `ReplModule`, `ImageModule`, `AnalyzeImagesModule`, `IOModule`, `ScraperModule`, `SearchModule`, `RagModule`, `MemoryModule`, `SkillsModule`, `GitHubModule`, `VKModule`, `WeatherModule`, `DeepResearchModule`, and `SubAgentLegacyModule`.

Routes returned by a module are mounted under `/agent/{module.id}`, or externally under `/api/agent/{module.id}` when using `giga_agent dev`.
