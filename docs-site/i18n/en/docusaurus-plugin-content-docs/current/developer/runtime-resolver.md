---
title: "Provider resolution"
description: "How GigaAgent chooses models, embeddings, sandbox, search, and image generation."
---

# Provider resolution

The runtime resolver hides provider lookup details from the graph. It decides which language model, embeddings model, sandbox runtime, search service, and image generator are available to the current user.

## UI and database mode

Settings usually come from the current user: `user.llm_id`, `user.fast_llm_id`, `user.embedding_id`, `user.sandbox_provider_id`, `user.search_engine_id`, and `user.image_generator_id`.

## CLI mode

`CliRuntimeResolver` loads `giga_agent.conf.json` through `load_cli_conf()` and creates the service user `cli@giga-agent.local.dev`.

Modules should ask the resolver whether a provider is available instead of guessing from raw configuration.
