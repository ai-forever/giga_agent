---
title: "Subagents"
description: "Deep research and compatibility subgraphs."
---

# Subagents

The standard agent has `DeepResearchModule` for the `deep_research` subgraph and `SubAgentLegacyModule` for compatibility subgraphs.

| ID | Source | Entry point |
|---|---|---|
| `deep_research` | `DeepResearchModule` | `giga_agent.modules.deep_research.graph:graph` |
| `landing` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph` |
| `presentation` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph` |
| `meme` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph` |
| `lean_canvas` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.lean_canvas:app` |
| `podcast` | `SubAgentLegacyModule` | `giga_agent.modules.subagents_legacy.agents.podcast.graph:graph` |

`run_deep_research` requires a language model and a search provider. Compatibility tools can require 2GIS, SaluteSpeech, an image generator, or a language model.
