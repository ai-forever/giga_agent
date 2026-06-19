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

## Stopping a response

While the agent is answering, the UI offers a stop button. It interrupts the current run; the already generated part of the answer is kept in history, so the conversation does not lose context.

Stopping frees an active execution thread. The number of simultaneously active chats per user is capped by `GIGA_AGENT_MAX_ACTIVE_THREADS_PER_USER` (see [Configuration](../operations/configuration.md)).

## Practical tips

- Configure a default model before the first real chat.
- Keep secrets in connectors or environment variables, not in messages.
- If a tool is unavailable, check the related provider and user permissions.
