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
| [GitHub](./connectors.md) | No | The GitHub server from the connectors catalog and its token. |
| VK | No | A VK connection in the connectors catalog; the legacy `VK_TOKEN` also works. |
| Weather | No | `OWM_API_KEY`. |
| Subagents | Partly | Model and scenario-specific secrets. |
| [Connectors](./connectors.md) | No | Services and MCP servers connected through the catalog. |
| [Yandex services](./yandex-services.md) | No | A Yandex OAuth application set up by the administrator and a service connected in the catalog. |
| [Chat widgets](./widgets.md) | Yes | A connected service whose data the widget shows. |
| [Scheduled tasks](./scheduler.md) | Partly | A channel with a recipient for result delivery. |
| [Channels (Telegram)](./channels.md) | No | A Telegram bot and contact approval in the channel settings. |

For a shared server, set a long `GIGA_AGENT_SECRET_KEY`, change the initial admin password, and configure sandbox access conservatively.
