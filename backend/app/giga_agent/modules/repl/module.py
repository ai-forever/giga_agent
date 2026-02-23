"""REPL модуль — предоставляет инструмент выполнения Python кода в sandbox."""

from __future__ import annotations

import keyword
import uuid
from typing import Any, List, Coroutine

from giga_agent.modules.repl.repl_tools.llm import summarize
from giga_agent.modules.repl.repl_tools.sentiment import (
    predict_sentiments,
    get_embeddings,
)
from giga_agent.modules.repl.repl_tools.utils import describe_repl_tool
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
from giga_agent.modules.repl.tools import python, shell
from giga_agent.modules.repl.prompts import JUPYTER_REPL_INSTRUCTIONS, SECRETS_PROMPTS
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def _is_valid_python_identifier(name: str) -> bool:
    return bool(name and name.isidentifier() and not keyword.iskeyword(name))


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


def generate_repl_tools_description(repl_tools: List[Coroutine], tools: List[BaseTool]):
    repl_tool_descriptions = []
    for repl_tool in repl_tools:
        repl_tool_descriptions.append(describe_repl_tool(repl_tool))
    llm_tools: list[str] = []
    for tool in tools:
        tool_name = getattr(tool, "name", None)
        if not isinstance(tool_name, str) or not tool_name:
            continue
        if tool_name == "python":
            continue
        extras = getattr(tool, "extras", None) or {}
        if extras.get("repl_skip"):
            continue
        if not _is_valid_python_identifier(tool_name):
            continue
        llm_tools.append(tool_name)
    repl_tools_str = "\n".join(repl_tool_descriptions)
    return f"""В sandbox доступны дополнительные Python-функции (repl_tools):

```
{repl_tools_str}
```

Также в Python-коде доступны LLM-инструменты (tools) агента: {llm_tools}.

Правило вызова: вызывай любые функции/инструменты **только через именованные аргументы (kwargs)**.
- Правильно: `func(arg=value, other=value2)`
- Неправильно: `func(value, value2)` (позиционные аргументы запрещены)

Имена аргументов и их описание смотри в сигнатуре/описании конкретной функции.
"""


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

        current_kernel_id = state.get("kernel_id")
        need_sandbox = current_kernel_id is None
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
    _repl_tools: List[Coroutine] = [predict_sentiments, summarize, get_embeddings]

    async def get_tools(self, user: UserShort, agent: BaseAgent) -> List[BaseTool]:
        if python.extras is None:
            python.extras = {"repl_tools": self._repl_tools}
        else:
            python.extras["repl_tools"] = self._repl_tools
        return [python, shell]

    async def get_instructions(self, user: UserShort, agent: BaseAgent) -> str | None:
        return (
            JUPYTER_REPL_INSTRUCTIONS
            + get_user_secrets_prompt(user)
            + generate_repl_tools_description(
                self._repl_tools, await agent.get_tools(user)
            )
        )

    def get_middleware(self) -> AgentMiddleware:
        return ReplMiddleware()
