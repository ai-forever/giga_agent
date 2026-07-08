---
title: "Extending GigaAgent"
description: "Add modules, tools, routes, and subgraphs."
---

# Extending GigaAgent

Extend GigaAgent through `BaseModule` so new functionality enters routes, tools, system instructions, migrations, and LangGraph development server configuration consistently.

## Minimal module

```python
from giga_agent.core.module import BaseModule

class MyModule(BaseModule):
    id = "my_module"
    label = "My module"
    description = "What the module does"
    icon = "Sparkles"
```

Register the module in `GigaAgent.get_modules()` or pass it when creating a custom agent instance. Keep `id` unique.

## Integrations and widgets

Ready-made layers exist for external services and visual results: an integration module with a connection provider enters the connectors catalog automatically (see [Integration modules](./integrations.md)), and a tool returning a payload with the `widget` marker renders as a card in the chat (see [GenUI](./genui.md)).

## Before documenting a new capability

1. Verify that the module is registered.
2. Verify that routes, tools, or subgraphs appear through the real execution path.
3. Document provider, secret, UI, and CLI conditions.
4. Update documentation with the code change.
