---
title: "Integration modules"
description: "How external-service integrations work and how to build one."
---

# Integration modules

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

An external-service integration is an ordinary agent module from the `modules/integrations/` package, extended with a connection provider. The module contributes tools; the provider describes the card in the connectors catalog and the authorization method. Yandex Mail, Yandex Calendar, Yandex Disk, and VK are built this way.

## Connection provider

A provider is built from `StaticOAuthConfig` (`core/integrations/static_provider.py`). Its fields describe both the card and the protocol:

- `key`, `label`, `icon` — the identifier and the look of the catalog card;
- `auth_kind` — `oauth2`, `manual_token`, or `both`;
- `authorization_endpoint`, `token_endpoint`, `scope` — OAuth endpoints;
- `manual_fields` — form fields for token-based connection, with hints and links;
- `validate_url` — a token liveness probe (GET with the token; a 2xx response means the token works);
- `auth_header_scheme` — the header scheme; Yandex uses `Authorization: OAuth <token>` with the `OAuth` scheme in place of the usual `Bearer`.

## Provider registry

The registry in `core/integrations/registry.py` collects providers by walking the loaded agent's modules: the agent registers itself at startup via `set_current_agent()`, and the UI catalog reads the card list from the registry. A module with a provider added to `get_modules()` appears in the catalog on its own.

## OAuth flow

Authorization runs through a popup with PKCE and a one-time `state`; the service response lands on a server callback shared by all integrations. The obtained token is stored per user and renews automatically. If the service refuses or the token is revoked, the service card switches to the re-authorization state.

OAuth application credentials come from environment variables (see [Configuration](../operations/configuration.md)): the shared `YANDEX_OAUTH_CLIENT_ID` and `YANDEX_OAUTH_CLIENT_SECRET`, an optional `YANDEX_OAUTH_REDIRECT_URI`, and a separate pair for Yandex Mail — Yandex requires a separate application for the mail scope. Until the variables are set, the OAuth button stays inactive and integrations work on manual tokens.

## Building your own integration

1. Create a `modules/integrations/<service>/` package with three parts: `module.py` (the module class with tools and a connection check in `is_enabled()`), `provider.py` (provider assembly from `StaticOAuthConfig`), `auth.py` (obtaining the user token inside tools).
2. Register the module in `GigaAgent.get_modules()`.
3. If tools return widget data, build the response with a payload constructor carrying the `widget` marker and wrap it in `with_widget_note()` so the agent does not restate the contents (see [GenUI](./genui.md)).

## Trackers

Task services share a common layer, `modules/integrations/tracker_base.py`: a normalized issue contract (`make_issue`), board and single-card payloads, the generative composition `emit_composed_board()`, and the `BaseTrackerModule` base with standard backend routes for status transitions. A provider returning the normalized payload renders with the existing widgets, with no UI changes. The current `main` branch has no active tracker modules — the contract is ready for the next service.
