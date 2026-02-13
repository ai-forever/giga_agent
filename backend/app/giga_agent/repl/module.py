"""REPL модуль — предоставляет инструмент выполнения Python кода в sandbox."""

from __future__ import annotations

import uuid
import logging
from typing import Any, List

from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserShort, UserRepository
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.repl.tools import python
from giga_agent.repl.prompts import JUPYTER_REPL_INSTRUCTIONS, SECRETS_PROMPTS

logger = logging.getLogger(__name__)


def get_user_secrets_prompt(user: UserShort):
    user_secrets = user.settings["contextSecrets"]
    if not user_secrets:
        return ""
    secret_parts = []
    for user_secret in user_secrets:
        name = user_secret.get("name")
        value = user_secret.get("value")
        description = user_secret.get("description")
        if not name or not value:
            continue
        secret_part = (
            f"Название: {user_secret['name']}\nЗначение: {user_secret['value'][:4]}..."
        )
        if description:
            secret_part += f"\nОписание: {description}"
        secret_parts.append(secret_part)
    return SECRETS_PROMPTS.format("\n".join(secret_parts))


def get_user_secrets_code(user: UserShort):
    user_secrets = user.settings["contextSecrets"]
    if not user_secrets:
        return None
    code_parts = []
    for user_secret in user_secrets:
        name = user_secret.get("name")
        value = user_secret.get("value")
        if not name or not value:
            continue
        code_parts.append(f"SECRETS['{name}'] = '{value}'")
    if not code_parts:
        return None
    return "SECRETS = {}\n" + "\n".join(code_parts)


class ReplMiddleware(AgentMiddleware):
    """
    Middleware для REPL модуля.

    Перед запуском агента поднимает sandbox пользователя,
    создаёт Jupyter kernel и сохраняет kernel_id в state.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        user_id = config["configurable"]["langgraph_auth_user"]["identity"]
        owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        user = await UserRepository.get_from_cache(owner_id)
        if user is None:
            factory = await get_session_factory()
            async with factory() as session:
                user_repo = UserRepository(session)
                user = await user_repo.get_by_id(owner_id, use_cache=False)
                if user is None:
                    raise ValueError(f"User with id {user_id} not found")
        secrets_code = get_user_secrets_code(user)
        current_kernel_id = state.get("kernel_id")
        need_sandbox = current_kernel_id is None or secrets_code is not None
        if not need_sandbox:
            return {}

        factory = await get_session_factory()
        async with factory() as session:
            manager = SandboxManager(session)
            sandbox_runtime = await manager.ensure_running_for_user(owner_id)

        # Важно: если kernel_id уже есть в state, синхронизируем его с runtime,
        # иначе secrets могут загрузиться в другой (новосозданный) kernel.
        if current_kernel_id:
            sandbox_runtime._kernel_id = current_kernel_id
        else:
            # Создаём/восстанавливаем Jupyter kernel и фиксируем kernel_id в state
            await sandbox_runtime._ensure_kernel()
            current_kernel_id = sandbox_runtime._kernel_id
            logger.info(
                f"Sandbox ready for user {owner_id}, kernel_id={current_kernel_id}"
            )

        if secrets_code is not None:
            async for _ in sandbox_runtime.run_code(secrets_code):
                pass
            # Если kernel создался во время run_code (на всякий случай), берём актуальный
            current_kernel_id = sandbox_runtime._kernel_id or current_kernel_id

        return {"kernel_id": current_kernel_id} if current_kernel_id else {}


class ReplModule(BaseModule):
    """
    Модуль REPL для выполнения Python кода.

    Предоставляет инструмент `python`, который выполняет код
    в Jupyter sandbox пользователя и возвращает результат.

    Также включает системный промпт с инструкциями по написанию
    REPL-кода для Jupyter.
    """

    id: str = "repl"

    def get_tools(self, user: UserShort, agent: BaseAgent) -> List[BaseTool]:
        return [python]

    def get_instructions(self, user: UserShort, agent: BaseAgent) -> str | None:
        return JUPYTER_REPL_INSTRUCTIONS + get_user_secrets_prompt(user)

    def get_middleware(self) -> AgentMiddleware:
        return ReplMiddleware()
