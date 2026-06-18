---
title: "Sandbox and security"
description: "Trust boundaries for code and command execution."
---

# Sandbox and security

GigaAgent can run code and commands through sandbox runtimes. Treat this as a trust boundary.

## Supported options

The codebase includes local Docker, local Jupyter, E2B, and shared sandbox lifecycle management.

## Practical checklist

- Enable code execution only for users who need it.
- Treat shell access as privileged.
- Limit file system access.
- Configure memory, process, and path limits.
- Keep `GIGA_AGENT_SECRET_KEY` secret.
- Do not copy demo settings to a shared server without review.
