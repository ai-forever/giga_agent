---
title: "Tools"
description: "How tools become available to the agent."
---

# Tools

Tools come from the base agent, active modules, runtime providers, sandboxes, and MCP state.

## Availability

A tool can require a model, embeddings, search, a sandbox, a secret, or a specific user permission. Documentation should describe these conditions instead of promising that every tool is always available.

## Execution guidance

- Review risky tool calls before exposing a shared server.
- Treat shell execution as privileged.
- Keep tool results small enough for the configured `GIGA_AGENT_TOOL_MAX_SIZE`.
- If a module is disabled for a user, its labeled tools are filtered out.
