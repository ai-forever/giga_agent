---
title: "Yandex services"
description: "How the agent works with Yandex Mail, Yandex Calendar, and Yandex Disk."
---

# Yandex services

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

The agent can read and send mail, manage a calendar, and work with files on Disk on behalf of your Yandex account. Services are enabled one by one: each connects through the [connectors catalog](./connectors.md) via OAuth, and access can be revoked at any moment on the Connected tab.

Prerequisite: a server administrator specifies the Yandex OAuth application credentials in the [configuration](../operations/configuration.md) beforehand. This is a one-time application setup; after it, users connect with a button.

## Yandex Mail

The agent searches messages by folder, sender, and subject ("show recent letters from the bank"), reads a whole message on request, and sends mail from your mailbox. The message list is rendered as an inbox card right in the chat; see [Widgets](./widgets.md) for details.

Sending happens only on an explicit request and goes through tool-call confirmation.

## Yandex Calendar

The agent shows events for the coming days ("what's on my week"), renders a month grid, creates events with a title, start, and end time, and deletes events. The agenda and the month grid appear as calendar widgets in the chat.

## Yandex Disk

The agent lists folders, reads text files, creates folders, saves text into a file, publishes a file under a public link and unpublishes it, and deletes files. Folder contents appear as a file browser in the chat.

## Action confirmations

While autonomous mode is off, every tool call waits for your confirmation — this covers sending mail, creating and deleting events, and deleting files. In autonomous mode tool-call confirmation is off: the agent acts immediately, including irreversible actions. Keep this in mind when enabling autonomous mode in a conversation with connected mail or Disk.

## If a service stops responding

Stored access can expire or be revoked on the Yandex side. The service card on the Connected tab will show the re-authorization state — press Authorize and sign in again. During normal use tokens renew automatically.
