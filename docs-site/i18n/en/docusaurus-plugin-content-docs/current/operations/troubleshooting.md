---
title: "Troubleshooting"
description: "Debug startup, model, RAG, and Docker Compose issues."
---

# Troubleshooting

## Server does not start: secret key

If startup reports that `GIGA_AGENT_SECRET_KEY` is missing, set it for shared servers. Local `giga_agent dev` can prepare a key automatically.

## Chat opens but messages fail

Check that a connection to a model provider exists, a language model is created and selected, provider credentials are valid, the server uses `/api`, and required providers are configured.

## RAG returns no results

Check user embeddings, Qdrant availability, collection indexing, and collection permissions.

## Docker Compose starts but UI is unavailable

Run:

```bash
docker compose ps
```

The nginx entrypoint is usually `http://localhost:8123`.

## A Yandex service fails to connect or dropped off

Check in order:

1. The OAuth button is inactive — `YANDEX_OAUTH_CLIENT_ID` and `YANDEX_OAUTH_CLIENT_SECRET` are not set (Mail needs its own pair). See [Configuration](./configuration.md).
2. An `invalid_scope` error during authorization — the application scopes at oauth.yandex.ru do not match the requested ones: verify the application has the rights of the needed service, and that Mail has a separate application.
3. The card shows the re-authorization state — the stored token expired or was revoked: press Authorize on the Connected tab.
4. The authorization window does not open — the browser blocked the popup; allow it for the server address.
