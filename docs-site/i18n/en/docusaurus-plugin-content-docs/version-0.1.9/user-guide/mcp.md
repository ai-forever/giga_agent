---
title: "MCP tools"
description: "Use MCP tools passed by the UI."
---

# MCP tools

MCP tools add external actions to a specific dialog or message. The backend can call only the tools that the UI passes for the current turn.

## Limits

- Available MCP tools can differ between dialogs.
- User permissions and sandbox rules still apply on the backend.
- If the UI does not pass a tool, the agent cannot call it for that turn.

Developers can read more in [Developer tools](../developer/tools.md).
