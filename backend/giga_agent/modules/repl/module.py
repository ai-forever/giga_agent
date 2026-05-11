"""REPL модуль — предоставляет инструмент выполнения Python кода в sandbox."""

from __future__ import annotations

import keyword
from typing import Any, List, Coroutine, Optional

from giga_agent.modules.repl.repl_tools.llm import summarize
from giga_agent.modules.repl.repl_tools.sentiment import (
    predict_sentiments,
    get_embeddings,
)
from giga_agent.modules.repl.repl_tools.utils import describe_repl_tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.core.agent.types import AgentState
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserShort
from giga_agent.sandbox.manager import ProviderNotFoundError, SandboxManager
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.sandbox.registry import SandboxRegistry
from giga_agent.modules.repl.tools import (
    await_shell,
    normalize_secret_env_name,
    python,
    shell,
)
from giga_agent.modules.repl.prompts import (
    JUPYTER_REPL_INSTRUCTIONS,
    SECRETS_PROMPTS,
    SHELL_INSTRUCTIONS,
)
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
        if not name or value is None:
            continue
        env_name = normalize_secret_env_name(name)
        secret_part = f"Название: {name}\nENV: {env_name}"
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


async def get_sandbox_prompt(
    user: UserShort,
    agent: BaseAgent,
    state: Optional[AgentState] = None,
    config: RunnableConfig | None = None,
    **kwargs: Any,
) -> str:
    session_factory = await get_session_factory()

    try:
        async with session_factory() as session:
            resolved = await SandboxManager.get_cached_or_db(
                user_id=user.id,
                session=session,
            )
    except ProviderNotFoundError:
        return ""
    except Exception as e:
        logger.warning(
            "failed_to_resolve_sandbox_prompt user_id=%s reason=%s",
            user.id,
            e,
        )
        return ""

    try:
        runtime = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
        return runtime.get_prompt(
            user=user,
            agent=agent,
            state=state,
            config=config,
            **kwargs,
        )
    except Exception as e:
        logger.warning(
            "failed_to_build_sandbox_prompt user_id=%s provider_type=%s reason=%s",
            user.id,
            resolved.provider.type,
            e,
        )
        return ""


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

    async def get_tools(
        self, user: UserShort, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        if python.extras is None:
            python.extras = {"repl_tools": self._repl_tools}
        else:
            python.extras["repl_tools"] = self._repl_tools

        tools: List[BaseTool] = [python, shell, await_shell]

        try:
            session_factory = await get_session_factory()
            async with session_factory() as session:
                resolved = await SandboxManager.get_cached_or_db(
                    user_id=user.id,
                    session=session,
                )
            runtime_cls = SandboxRegistry.get(resolved.provider.type)
            tools.extend(runtime_cls.get_tools())
        except Exception:
            pass

        return tools

    async def get_instructions(
        self,
        user: UserShort,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        sandbox_prompt = await get_sandbox_prompt(
            user,
            agent=agent,
            state=state,
            config=config,
            **kwargs,
        )
        return (
            JUPYTER_REPL_INSTRUCTIONS
            + SHELL_INSTRUCTIONS
            + sandbox_prompt
            + get_user_secrets_prompt(user)
            + generate_repl_tools_description(
                self._repl_tools, await agent.get_tools(user, config=config)
            )
        )
