---
title: "External services"
description: "GitHub, VK, weather, search, and other integrations."
---

# External services

Some tools call external services. They are not enabled just by installing the package; the user or server must configure a provider or secret.

| Service | Typical requirement |
|---|---|
| GitHub | The GitHub server from the [connectors catalog](./connectors.md) and its token |
| VK | A VK connection in the [connectors catalog](./connectors.md); the legacy `VK_TOKEN` secret also works |
| Weather | `OWM_API_KEY` |
| Search | Search provider configuration |

Yandex Mail, Calendar, and Disk are covered on a separate page — [Yandex services](./yandex-services.md).

Keep keys out of server logs and out of anything you share: instructions, screenshots, messages.
