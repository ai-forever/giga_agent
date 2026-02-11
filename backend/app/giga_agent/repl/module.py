"""REPL модуль — предоставляет инструмент выполнения Python кода в sandbox."""

from __future__ import annotations

import uuid
import logging
from typing import Any, List

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.module import BaseModule
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.repl.tools import python
from giga_agent.repl.prompts import JUPYTER_REPL_INSTRUCTIONS

logger = logging.getLogger(__name__)


class ReplMiddleware(AgentMiddleware):
    """
    Middleware для REPL модуля.

    Перед запуском агента поднимает sandbox пользователя,
    создаёт Jupyter kernel и сохраняет kernel_id в state.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        if "kernel_id" not in state:
            user_id = config["configurable"]["langgraph_auth_user"]["identity"]
            owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

            factory = await get_session_factory()
            async with factory() as session:
                manager = SandboxManager(session)
                sandbox_runtime = await manager.ensure_running_for_user(owner_id)

            # Создаём/восстанавливаем Jupyter kernel
            await sandbox_runtime._ensure_kernel()
            kernel_id = sandbox_runtime._kernel_id

            logger.info(f"Sandbox ready for user {owner_id}, kernel_id={kernel_id}")
            return {"kernel_id": kernel_id}
        return {}


class ReplModule(BaseModule):
    """
    Модуль REPL для выполнения Python кода.

    Предоставляет инструмент `python`, который выполняет код
    в Jupyter sandbox пользователя и возвращает результат.

    Также включает системный промпт с инструкциями по написанию
    REPL-кода для Jupyter.
    """

    id: str = "repl"

    def get_tools(self) -> List[BaseTool]:
        return [python]

    def get_instructions(self) -> str | None:
        return JUPYTER_REPL_INSTRUCTIONS

    def get_middleware(self) -> AgentMiddleware:
        return ReplMiddleware()
