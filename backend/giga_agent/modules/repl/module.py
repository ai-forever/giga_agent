"""REPL модуль — предоставляет инструмент выполнения Python кода в sandbox."""

from __future__ import annotations

import keyword
import uuid
from typing import Any, List, Coroutine, Optional

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
from pydantic import BaseModel, Field

logger = get_logger(__name__)


def _is_valid_python_identifier(name: str) -> bool:
    return bool(name and name.isidentifier() and not keyword.iskeyword(name))


class ToolUse(BaseModel):
    recipient_name: str = Field(description="Имя инструмента, который будет вызван")
    parameters: str = Field(description="JSON-строка с параметрами инструмента")


def get_user_secrets_prompt(user: UserShort):
    user_secrets = (user.settings or {}).get("contextSecrets")
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

    async def get_instructions(
        self,
        user: UserShort,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        **kwargs: Any,
    ) -> str | None:
        _ = state, kwargs
        return (
            JUPYTER_REPL_INSTRUCTIONS
            + get_user_secrets_prompt(user)
            + generate_repl_tools_description(
                self._repl_tools, await agent.get_tools(user)
            )
        )
