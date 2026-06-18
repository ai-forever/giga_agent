---
title: "Shared server"
description: "Run GigaAgent for more than one user."
---

# Shared server

A shared server needs stricter defaults than a local demo.

## Minimum checklist

- Set a long random `GIGA_AGENT_SECRET_KEY`.
- Change the initial administrator password.
- Restrict access to administration pages.
- Review sandbox permissions and Docker socket exposure.
- Store provider secrets outside documentation and screenshots.
- Decide which users can access files, collections, memory, and tools.
