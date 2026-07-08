---
title: "Capabilities and requirements"
description: "What works immediately and what needs providers or secrets."
---

# Capabilities and requirements

GigaAgent combines a base UI with optional capabilities. Most useful scenarios need configured providers.

| Capability | Works immediately? | Required setup |
|---|---:|---|
| Sign in to the UI | Yes | Nothing for local setup. |
| Chat | No | Connection and language model. |
| Streaming output | Yes, after model selection | Language model. |
| [Projects](./projects.md) | Yes | Nothing for project instructions; embeddings for the project knowledge base. |
| File upload | Yes | User permissions; processing may need tools or a model. |
| RAG | No | Embeddings and vector store. |
| Memory | No | User embeddings and vector store. |
| Python or shell execution | No | Sandbox runtime. |
| Image generation | No | Image generator provider. |
| Image analysis | No | Vision-capable model. |
| Web search | No | Search provider. |
| GitHub | No | `GITHUB_PERSONAL_ACCESS_TOKEN`. |
| VK | No | `VK_TOKEN`. |
| Weather | No | `OWM_API_KEY`. |
| Subagents | Partly | Model and scenario-specific secrets. |
| MCP tools | No | Tools passed by the UI for the current dialog. |

For a shared server, set a long `GIGA_AGENT_SECRET_KEY`, change the initial admin password, and configure sandbox access conservatively.
