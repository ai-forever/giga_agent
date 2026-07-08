---
title: "Chat widgets"
description: "Interactive cards in agent replies: mail, calendar, files."
---

# Chat widgets

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

The agent renders results of some tools as interactive cards right in the reply. A widget beats a retelling: the data is visible at once, and actions run without extra chat messages.

## Available widgets

**Inbox.** A list of Yandex Mail messages: sender, subject, date. A message expands on click, and its body loads immediately, with no model round-trip. The message markup renders in an isolated frame: scripts are blocked, links open in a new tab.

**Calendar agenda.** Events of the coming days as a list.

**Month grid.** A month calendar with events per day.

**File browser.** Contents of a Yandex Disk folder. Folders can be navigated inside the widget; files carry buttons to publish under a public link and to unpublish.

## How they work

A widget appears automatically when a tool returns suitable data: ask the agent to show the inbox, the week's schedule, or a folder's contents — and you get a card. Actions inside a widget (expand a message, open a folder) run directly through backend routes. Actions with consequences — sending mail, deleting — stay with the agent and go through the usual [tool-call confirmation](./yandex-services.md#action-confirmations).

Widgets are unavailable in a Telegram channel: there the agent replies with text.

For developers: the data-to-widget mapping lives in `front/src/components/widgets/registry.ts`; the design is described in [Architecture](../developer/architecture.md).
