"""Shared helpers for resolving project context from a runtime config."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from langchain_core.runnables import RunnableConfig

from giga_agent.core.logging import get_logger
from giga_agent.utils.langgraph_sdk import get_client

logger = get_logger(__name__)


def _coerce_uuid(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _project_id_from_dict(d: Mapping[str, Any] | None) -> uuid.UUID | None:
    if not isinstance(d, Mapping):
        return None
    return _coerce_uuid(d.get("project_id"))


def _thread_id_from_config(
    config: RunnableConfig | dict[str, Any] | None,
) -> str | None:
    if not isinstance(config, dict):
        return None
    for source in ("metadata", "configurable"):
        section = config.get(source) or {}
        if not isinstance(section, Mapping):
            continue
        thread_id = section.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip().strip("/")
    return None


async def resolve_project_id(
    config: RunnableConfig | dict[str, Any] | None,
) -> uuid.UUID | None:
    """Resolve the project_id for the current run.

    Looks at config.metadata / config.configurable first, then falls back
    to fetching thread metadata via the LangGraph SDK (because thread
    metadata is not merged into the runtime config by default).
    """
    if not isinstance(config, dict):
        return None
    for source in ("metadata", "configurable"):
        section = config.get(source) or {}
        candidate = _project_id_from_dict(section)
        if candidate is not None:
            return candidate

    thread_id = _thread_id_from_config(config)
    if not thread_id:
        return None
    try:
        client = get_client(config)
        thread = await client.threads.get(thread_id)
    except Exception:
        logger.exception(
            "resolve_project_id: failed to fetch thread metadata for %s",
            thread_id,
        )
        return None
    return _project_id_from_dict(thread.get("metadata"))
