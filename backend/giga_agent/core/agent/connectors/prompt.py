"""System-prompt section listing the connectors available to the model."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from giga_agent.core.logging import get_logger

if TYPE_CHECKING:
    from giga_agent.core.agent.connectors.sources import ToolSource

logger = get_logger(__name__)


async def _tool_names(source: "ToolSource", user_id: uuid.UUID) -> list[str]:
    """Tool names advertised by *source*, or ``[]`` if listing fails.

    Best-effort: an unreachable / unauthorized server must not break the whole
    prompt — it just shows up without its tool list.
    """
    try:
        specs = await source.list_tools(user_id=user_id)
    except Exception as exc:  # noqa: BLE001 — listing is best-effort
        logger.debug("connector '%s' tool listing failed: %s", source.name, exc)
        return []
    return [spec.name.strip() for spec in specs if spec.name and spec.name.strip()]


async def build_connectors_prompt(
    sources: "list[ToolSource]", *, user_id: uuid.UUID
) -> str | None:
    """Render the «Доступные коннекторы» block, or ``None`` if there are none.

    Each line shows the exact name the model must pass to ``connector_get_info``
    followed by that connector's available tool names. Tool lists are fetched
    concurrently and are best-effort (a failing source is still listed, just
    without its tools).
    """
    if not sources:
        return None

    names_per_source = await asyncio.gather(
        *(_tool_names(source, user_id) for source in sources)
    )

    lines: list[str] = []
    for source, tool_names in zip(sources, names_per_source):
        label = (source.label or "").strip()
        name = source.name.strip()
        if label and label.lower() != name.lower():
            head = f"- {name} ({label})"
        else:
            head = f"- {name}"
        if tool_names:
            lines.append(f"{head}: {', '.join(tool_names)}")
        else:
            lines.append(head)
    listing = "\n".join(lines)
    return (
        "Доступные коннекторы (с их инструментами):\n"
        f"{listing}\n"
        "Чтобы узнать параметры инструмента коннектора, вызови "
        "connector_get_info('<имя>'). "
        "Затем вызывай инструмент через "
        "connector_call_tool('<имя>', '<инструмент>', params='<JSON>')."
    )
