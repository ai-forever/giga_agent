---
title: "Chat"
description: "How chat requests are processed."
---

# Chat

A chat request combines the user message, selected model, enabled modules, configured providers, available tools, and conversation state.

## Basic flow

1. The UI sends a message to the API.
2. The backend resolves the user settings.
3. The graph collects tools from the agent, modules, providers, sandboxes, and MCP state.
4. The selected model answers, optionally calling tools.
5. The UI receives streamed events and final messages.

## Practical tips

- Configure a default model before the first real chat.
- Keep secrets in connectors or environment variables, not in messages.
- If a tool is unavailable, check the related provider and user permissions.
