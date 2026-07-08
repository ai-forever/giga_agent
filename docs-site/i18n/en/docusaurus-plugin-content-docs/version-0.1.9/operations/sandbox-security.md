---
title: "Sandbox and security"
description: "Trust boundaries for code and command execution in GigaAgent 0.1.9."
---

# Sandbox and security

Version 0.1.9 supports local Docker, local Jupyter, E2B, and shared sandbox lifecycle management. The REPL module can expose `python`, `shell`, and `await_shell` when the related sandbox is configured.

Treat code and shell execution as privileged. Limit file system access, resource usage, and user permissions before exposing a shared server.
