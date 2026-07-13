---
title: "First chat"
description: "Configure a model and send the first message."
---

# First chat

After startup, the web UI opens, but chat needs a selected language model. Without a model, a message can fail with a configuration error.

## 1. Sign in

Open `http://localhost:9090` and use the initial local administrator account:

- `admin@example.com`
- `giga_agent_admin`

## 2. Add a connector

Open **Settings → Connectors** and add a provider connection. A connector stores access parameters such as keys, base URLs, and provider-specific options.

## 3. Add a language model

Open **Settings → LLMs**, create a model linked to the connector, then select it in **Settings → General** as the default model.

## 4. Send a short message

```text
Briefly explain what you can do in this installation.
```

If the answer streams back, the basic setup works.

## What to configure next

| Task | Enable | Where |
|---|---|---|
| RAG over documents | Embeddings and, if needed, Qdrant. | [RAG](../user-guide/rag.md) |
| Long-term memory | User embeddings. | [Memory](../user-guide/memory.md) |
| Python and shell execution | A sandbox runtime. | [Tools](../user-guide/tools.md), [Sandbox and security](../operations/sandbox-security.md) |
| Image generation | Image generator provider. | [Images](../user-guide/images.md) |
| Web search | Search provider. | [External services](../user-guide/external-services.md) |
| GitHub, VK, weather, subagents | Related secrets. | [External services](../user-guide/external-services.md), [Subagents](../developer/subagents.md) |
