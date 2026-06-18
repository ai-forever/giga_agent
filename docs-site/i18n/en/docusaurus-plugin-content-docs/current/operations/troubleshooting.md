---
title: "Troubleshooting"
description: "Debug startup, model, RAG, and Docker Compose issues."
---

# Troubleshooting

## Server does not start: secret key

If startup reports that `GIGA_AGENT_SECRET_KEY` is missing, set it for shared servers. Local `giga_agent dev` can prepare a key automatically.

## Chat opens but messages fail

Check that a connector exists, a language model is created and selected, provider credentials are valid, the server uses `/api`, and required providers are configured.

## RAG returns no results

Check user embeddings, Qdrant availability, collection indexing, and collection permissions.

## Docker Compose starts but UI is unavailable

Run:

```bash
docker compose ps
```

The nginx entrypoint is usually `http://localhost:8123`.
