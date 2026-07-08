---
title: "GenUI: widgets"
description: "The data-to-widget contract between the backend and the UI."
---

# GenUI: widgets

:::info[Current documentation]
This page describes the current `main` branch. For the stable PyPI package, switch to version **0.1.9 (PyPI)**.
:::

The UI picks a widget by the `widget` marker in a tool result. The tool name plays no part in routing, so any data provider returning a normalized payload renders with an existing widget, with no UI changes.

## Registry

The mapping lives in `front/src/components/widgets/registry.ts`:

| `widget` marker | Component | What it shows |
|---|---|---|
| `mail_inbox` | `MailInbox` | A message list; message bodies load through a backend route |
| `calendar_agenda` | `CalendarAgenda` | Events of the coming days |
| `calendar_month` | `MonthGrid` | A month grid |
| `file_browser` | `FileBrowser` | A Yandex Disk folder with navigation and publishing |
| `issue_board` | `BoardWidget` | A tracker issue board |

Shared building blocks (the card shell, empty states, payload types) live in `front/src/components/widgets/kit/`.

## Backend side

A tool assembles data with a payload constructor — `inbox_payload()`, `agenda_payload()`, `month_payload()`, `file_browser_payload()`, `board_payload()` — and returns it through `build_widget_tool_message()` (`core/agent/tool_results.py`). The payload gets a `with_widget_note()` mark from `modules/integrations/widget_hint.py`: it asks the agent to skip restating the widget contents as text. In a Telegram channel the mark is omitted — the widget is invisible there, and the agent replies with text.

## Adding a widget

1. Define a payload with a new `widget` marker and build it in the tool through `build_widget_tool_message()`.
2. Write a component on top of the `kit/` building blocks.
3. Add the marker-to-component pair to `WIDGET_KIND_REGISTRY`.

A new data provider for an existing widget skips steps 2 and 3 — a normalized payload is enough.

## Generative board

Beyond static payloads there are compositions: `emit_composed_board()` from `tracker_base.py` pushes an issue grouping into `thread.values.ui` under the `issue_board_composed` name, and `BoardWidget` renders it live as the run proceeds. Issue status transitions go through the standard `BaseTrackerModule` backend routes, bypassing the model. The current `main` branch has no active trackers; see [Integration modules](./integrations.md) for the contract.
