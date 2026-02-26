from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.modules.mem_zero_memory.memory import (
    MemZeroEmbeddingsNotConfigured,
    format_memories,
    get_memory_for_user,
)
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


async def _background_save_memory(
    human_content: str, ai_content: str, config: RunnableConfig
):
    try:
        user_id = config["configurable"]["langgraph_auth_user"]["identity"]
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        factory = await get_session_factory()
        async with factory() as session:
            user = await UserRepository.get_cached_or_db(user_uuid, session=session)
            if user is None:
                return
            if user.embedding_id is None:
                # Module is disabled for users without embeddings configured.
                return

            memory = await get_memory_for_user(user=user, session=session)
        interaction = [
            {"role": "user", "content": human_content},
            {"role": "assistant", "content": ai_content},
        ]
        await memory.add(
            interaction,
            user_id=str(user.id),
        )
    except MemZeroEmbeddingsNotConfigured:
        # Disabled for this user.
        return
    except Exception:
        logger.exception("Failed to save mem0 memory in background")


class MemZeroMiddleware(AgentMiddleware):
    async def after_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        messages = state["messages"]
        last_ai = next((m for m in reversed(messages) if m.type == "ai"), None)
        if last_ai is None:
            return {}

        # Find the nearest human message before the last AI message.
        last_human = None
        found_ai = False
        for m in reversed(messages):
            if m is last_ai:
                found_ai = True
                continue
            if not found_ai:
                continue
            if m.type == "human":
                last_human = m
                break

        if last_human is not None:
            asyncio.create_task(
                _background_save_memory(last_human.content, last_ai.content, config),
            )
        return {}


class MemZeroModule(BaseModule):
    id: str = "mem_zero_memory"

    def get_api_router(self) -> APIRouter:
        from giga_agent.modules.mem_zero_memory.api import router

        return router

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: "AgentState",
        agent: "BaseAgent",
    ) -> str | None:
        _ = state, agent
        if user is None or user.embedding_id is None:
            return None

        factory = await get_session_factory()
        async with factory() as session:
            try:
                memory = await get_memory_for_user(user=user, session=session)
            except MemZeroEmbeddingsNotConfigured:
                return None

        retrieved_memories = await memory.search(
            query=task, user_id=str(user.id), limit=5
        )
        formatted = format_memories(retrieved_memories)
        if not formatted.strip():
            return None
        return f"<memory>{formatted}</memory>\n"

    def get_middleware(self) -> AgentMiddleware:
        return MemZeroMiddleware()
