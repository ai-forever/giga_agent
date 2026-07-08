---
title: "Channels"
description: "Talking to the agent through Telegram."
---

# Channels

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

A channel is a way to talk to the agent outside the web UI. Telegram is supported now: the agent replies in private and group chats through a connected bot. The channel design is extensible, and the channel type is chosen at creation time.

## Setup

Channels are configured in **Settings → Channels**. Create a bot with [@BotFather](https://t.me/BotFather), copy its token, then press **Create**, choose the channel type, and provide the token. Once started, the bot begins accepting messages.

## Contacts and access

Everyone who writes to the bot appears in the channel's contact list — and until approved, the bot ignores their messages. Approve a contact in the channel settings to grant the person access to the agent. There the contact can also be made a default recipient for [scheduled tasks](./scheduler.md) or deleted — after deletion the person has to write to the bot again.

## How a channel differs from the web chat

- In Telegram the agent replies with text; [widgets](./widgets.md) are available only in the web UI.
- Tool calls in Telegram run without confirmations — the conversation there is always autonomous. This includes irreversible actions such as sending mail: keep it in mind when approving contacts for an agent with connected [Yandex services](./yandex-services.md).
- In a group chat the agent sees the group context; scheduled tasks created in the chat deliver results to that same chat.
