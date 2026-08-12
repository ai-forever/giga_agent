"""Учёт использования LLM: пишет usage_metadata каждого ответа модели.

Fire-and-forget: любая ошибка учёта логируется и не влияет на ответ.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.conf import get_settings
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.logging import get_logger
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

logger = get_logger(__name__)


def _resolve_user_id(config: RunnableConfig | dict[str, Any]) -> uuid.UUID | None:
    identity = get_user_id_from_config(config)
    if isinstance(identity, uuid.UUID):
        return identity
    if isinstance(identity, str):
        try:
            return uuid.UUID(identity)
        except ValueError:
            return None
    return None


async def _record(user_id: uuid.UUID, model: str | None, usage: dict) -> None:
    try:
        from giga_agent.core.db import get_session_factory
        from giga_agent.models.usage import UsageEvent

        factory = await get_session_factory()
        async with factory() as session:
            session.add(
                UsageEvent(
                    user_id=user_id,
                    model=(model or None),
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                )
            )
            await session.commit()
    except Exception:
        logger.exception("UsageTracking: failed to record usage")


def schedule_usage_record(
    config: RunnableConfig | dict[str, Any],
    model: str | None,
    usage: dict[str, Any],
) -> None:
    """Record an out-of-band LLM call without delaying the graph."""
    if get_settings().giga_agent_runtime == "cli":
        return
    user_id = _resolve_user_id(config)
    if user_id is not None:
        asyncio.create_task(_record(user_id, model, usage))


class UsageTrackingMiddleware(AgentMiddleware):
    async def after_model(
        self,
        state: AgentState,
        runtime: Runtime[Context],
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        _ = runtime
        try:
            message = state["messages"][-1] if state.get("messages") else None
            if not isinstance(message, AIMessage):
                return None
            usage = getattr(message, "usage_metadata", None)
            if not usage:
                return None
            model = None
            meta = getattr(message, "response_metadata", None)
            if isinstance(meta, dict):
                model = meta.get("model_name") or meta.get("model")
            # Не задерживаем основной поток записью в БД.
            schedule_usage_record(config, model, dict(usage))
        except Exception:
            logger.exception("UsageTracking: after_model failed")
        return None
