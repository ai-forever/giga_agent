---
title: "Modules"
description: "Active modules and the BaseModule contract."
---

# Modules

A module is a GigaAgent extension unit. It can add routes, database models, migrations, tools, system instructions, secrets, middleware, subgraphs, and startup handlers.

## BaseModule contract

Important fields and methods include `id`, `label`, `description`, `icon`, `get_api_router()`, `get_models()`, `_get_tools()` / `get_tools()`, `get_instructions()`, `extend_task()`, `get_secrets()`, `get_middleware()`, `get_subgraphs()`, `is_enabled()`, and `on_startup()`.

## Active modules in current main

`giga_agent dev` loads 21 modules, in the order of `GigaAgent.get_modules()`: `AuthModule`, `ClarifyModule` (clarifying questions with answer options via the `ask_questions` tool), `ReplModule`, `ImageModule`, `AnalyzeImagesModule`, `IOModule`, `ProjectsModule`, `ScraperModule`, `SearchModule`, `RagModule`, `MemoryModule`, `SkillsModule`, `McpModule` (external MCP servers plus the managed-server catalog in `modules/mcp/catalog.json`), `VKModule`, `YandexDiskModule`, `YandexMailModule`, `YandexCalendarModule`, `WeatherModule`, `DeepResearchModule`, `SchedulerModule` (scheduled tasks created and cancelled from chat), and `SubAgentLegacyModule`.

External-service modules live in the `modules/integrations/` package. Each carries its own OAuth support (`auth.py`, `provider.py`); users enable such services through the connections catalog in the UI. The former `GitHubModule` was removed from the repository: GitHub integration is available through the GitHub server in the MCP catalog.

`ProjectsModule` exposes the [projects](../user-guide/projects.md) management API and injects per-project instructions into the system instruction.

Routes returned by a module are mounted under `/agent/{module.id}`, or externally under `/api/agent/{module.id}` when using `giga_agent dev`.
