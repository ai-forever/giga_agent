from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.logging import get_logger
from giga_agent.memory.runtime import build_memory_service, is_memory_disabled


logger = get_logger(__name__)


_MEMORY_TOOL_NAMES = frozenset({"write_file", "edit_file", "delete_file"})


def _tool_name(msg: ToolMessage) -> str | None:
    name = getattr(msg, "name", None)
    if name:
        return name
    kwargs = getattr(msg, "additional_kwargs", None) or {}
    return kwargs.get("tool_name")


def _last_round_has_memory_changes(state: AgentState) -> bool:
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return False

    # Scan the trailing ToolMessage block; if any tool call in that block
    # targets memory mutations, a reindex is warranted. ``reindex_changed`` is
    # idempotent so a false positive is harmless.
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            return False
        if _tool_name(msg) in _MEMORY_TOOL_NAMES:
            return True
    return False


class MemoryMiddleware(AgentMiddleware):
    async def before_model(
        self,
        state: AgentState,
        runtime: Runtime[Context],
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        _ = runtime
        if is_memory_disabled(config):
            return None
        if not _last_round_has_memory_changes(state):
            return None
        try:
            service = await build_memory_service(config, include_fast_llm=False)
        except Exception:
            logger.exception("MemoryMiddleware: failed to build service")
            return None
        if not service.has_embeddings:
            return None
        try:
            count = await service.reindex_changed()
            if count:
                logger.info("MemoryMiddleware: reindexed %d memory files", count)
        except Exception:
            logger.exception("MemoryMiddleware: reindex_changed failed")
        return None


__all__ = ["MemoryMiddleware"]
