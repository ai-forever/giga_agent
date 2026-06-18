---
title: "Subagents"
description: "Compatibility subgraphs in GigaAgent 0.1.9."
---

# Subagents

:::info Stable PyPI documentation
This page describes the published PyPI package `giga-agent==0.1.9`. For the repository state, switch to version **main**.
:::

In version 0.1.9, compatibility subagents live in `giga_agent.modules.subagents_legacy`.

| ID | Entry point |
|---|---|
| `landing` | `giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph` |
| `presentation` | `giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph` |
| `meme` | `giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph` |
| `lean_canvas` | `giga_agent.modules.subagents_legacy.agents.lean_canvas:app` |
| `podcast` | `giga_agent.modules.subagents_legacy.agents.podcast.graph:graph` |

Tools can require a language model, 2GIS, SaluteSpeech, or an image generator.
