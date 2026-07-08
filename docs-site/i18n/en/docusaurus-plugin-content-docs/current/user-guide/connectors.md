---
title: "Connectors"
description: "Connecting external services and MCP servers through the in-chat catalog."
---

# Connectors

A connector is an external service that adds tools to the agent. Connectors come in two kinds: [MCP](https://modelcontextprotocol.io/) servers and built-in integrations — Yandex Mail, Yandex Calendar, Yandex Disk, VK. All of them are managed in one place: the connectors catalog.

## Where to find it

Open the plus menu next to the message input and choose **Connectors**. The submenu lists already connected services with switches, so you can quickly remove a service's tools from the conversation and bring them back. The **Manage connectors** item opens the catalog window with two tabs: **Catalog** and **Connected**.

## Catalog

The **Catalog** tab shows cards for every available service: built-in integrations first, then MCP servers. Cards can be searched by name and description and filtered by category: development, documentation, search, shopping, travel, and more.

The MCP catalog of the current `main` branch includes: VkusVill, Tutu.ru, Bitrix24, GitHub, DeepWiki, Context7, Excalidraw, Hugging Face, Tavily Search, Sentry, and Replicate. The catalog contents come from `modules/mcp/catalog.json`, so the list may change between builds.

## Connecting a service

The steps depend on how the service authorizes access.

**A service with OAuth** (for example, Yandex Mail). Press the connect button on the card — the service's authorization window pops up. Confirm access, the window closes, and the card is marked as connected. Access tokens refresh automatically.

**A service with a token** (for example, VK or an MCP server with a bearer token). The first press expands a form on the card. Fill in the requested fields — fields carry hints and links to pages where the key can be obtained — and confirm. The form rejects empty required fields.

**An MCP server with OAuth.** The server is added first, and the authorization window opens right after.

For Yandex integrations, an administrator specifies the OAuth application credentials in the server settings beforehand — see [Configuration](../operations/configuration.md). Until the application is configured, the cards explain how to enable it.

## Custom connector

The **Custom connector** button on the Catalog tab adds an arbitrary MCP server: specify a name, an address (`https://mcp.example.com/mcp`), and the authorization kind — none, bearer token, or OAuth. For OAuth, a scope can be set when needed.

## The Connected tab

This tab gathers all connected connectors. Each one offers:

- a switch — temporarily remove the service's tools from conversations;
- a list of the server's available tools — expands on the card;
- an **Authorize** button — when the service asks for re-authorization;
- disconnection — with a confirmation; the link to the service is removed.

The "needs re-authorization" state means the stored access expired or was revoked: press **Authorize** and sign in to the service again.

## How connectors work in chat

The agent uses tools of connected connectors alongside the built-in ones. Keep in mind:

- the tool set depends on which connectors are enabled, so it may differ between conversations;
- a service switched off in the chat menu is unavailable to the agent in that conversation;
- user permissions and tool execution rules are enforced by the backend.

Results of some tools are rendered visually — as mail cards, a calendar, or a file list. For developers, the catalog internals are described in [Architecture](../developer/architecture.md).
