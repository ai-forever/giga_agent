---
title: "Developer tools"
description: "Define, collect, and filter tools."
---

# Developer tools

A tool is usually a function decorated with `@tool` from `langchain_core.tools`, but it becomes available only after the agent collects it from a module or provider.

## Collection order

1. `BaseAgent.get_tools()` collects base tools and module tools.
2. Module wrappers mark tools with `module_id` when a module has a label.
3. The graph adds service tools such as `think` and `multi_tool_use` when enabled.
4. Runtime providers and sandboxes can add more tools.
5. MCP tools from dialog state are converted and appended.

Document the required provider, secret, and permission for each tool.
