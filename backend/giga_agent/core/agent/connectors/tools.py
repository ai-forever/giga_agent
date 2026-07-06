"""The two built-in connector meta-tools: ``connector_get_info`` / ``connector_call_tool``.

These are the only connector-related tools bound to the model. The set of
connectors is surfaced in the system prompt (see
:func:`giga_agent.core.agent.connectors.prompt.build_connectors_prompt`); the
per-connector tool detail is fetched here at runtime. Output and errors are
tuned for weak models — flat ``required`` lists, a concrete ``params_example``
per tool, and explicit next-action error hints.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage

from giga_agent.core.agent.connectors.sources import (
    ToolSource,
    collect_sources,
    match_source,
)
from giga_agent.core.agent.tool_results import build_error_tool_message
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

# Names of the two built-in connector meta-tools. Single source of truth — used
# for the @tool names, error hints and any prompt that references them, so the
# tools can be renamed in one place.
GET_INFO_TOOL_NAME = "connector_get_info"
CALL_TOOL_NAME = "connector_call_tool"


async def _resolve_context(
    runtime: ToolRuntime,
) -> tuple[Any, UserShort | None, uuid.UUID]:
    """Return ``(agent, user, user_id)`` for the calling runtime."""
    user_id = get_user_id_from_config(runtime.config)
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    agent = getattr(runtime, "agent", None)
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
    return agent, user, owner_id


def _names(sources: list[ToolSource]) -> str:
    return ", ".join(s.name for s in sources) or "<нет коннекторов>"


@tool(
    GET_INFO_TOOL_NAME,
    description=(
        "Получить список инструментов конкретного коннектора и схему их аргументов. "
        f"Вызывай это ПЕРЕД {CALL_TOOL_NAME}, чтобы узнать имена инструментов и поля params. "
        "Аргумент connector — имя коннектора из списка доступных коннекторов."
    ),
)
async def connector_get_info(
    connector: Annotated[str, "Имя коннектора из списка доступных"],
    runtime: ToolRuntime,
) -> dict | ToolMessage:
    _, user, owner_id = await _resolve_context(runtime)
    agent = getattr(runtime, "agent", None)
    sources = (
        await collect_sources(agent, user, runtime.config)
        if agent is not None and user is not None
        else []
    )
    target = match_source(sources, connector)
    if target is None:
        return build_error_tool_message(
            content=f"connector '{connector}' not found; available: {_names(sources)}",
            runtime=runtime,
            tool_name=GET_INFO_TOOL_NAME,
        )
    specs = await target.list_tools(user_id=owner_id)
    return {
        "connector": target.name,
        "tools": [s.as_dict() for s in specs],
        "hint": (
            f"Вызов: {CALL_TOOL_NAME}(connector='{target.name}', tool='<имя>', "
            "params='<JSON-строка из params_example>')"
        ),
    }


@tool(
    CALL_TOOL_NAME,
    description=(
        "Вызвать инструмент коннектора. connector — имя коннектора, tool — имя инструмента "
        f"(узнай через {GET_INFO_TOOL_NAME}), params — JSON-строка с аргументами, например "
        '\'{"a": 1, "b": 2}\'. Если аргументы не нужны — params можно не передавать.'
    ),
)
async def connector_call_tool(
    connector: Annotated[str, "Имя коннектора"],
    tool: Annotated[str, "Имя инструмента коннектора"],
    runtime: ToolRuntime,
    params: Annotated[
        str | None,
        'JSON-строка с аргументами инструмента, например \'{"a": 1}\'. По умолчанию пусто.',
    ] = None,
) -> dict | ToolMessage:
    def _error(message: str) -> ToolMessage:
        return build_error_tool_message(
            content=message, runtime=runtime, tool_name=CALL_TOOL_NAME
        )

    parsed_params: dict[str, Any] = {}
    if params:
        try:
            parsed_params = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            return _error(
                'params должен быть JSON-строкой объекта, например \'{"key": "value"}\''
            )
        if not isinstance(parsed_params, dict):
            return _error(
                'params должен быть JSON-объектом, например \'{"key": "value"}\''
            )

    _, user, owner_id = await _resolve_context(runtime)
    agent = getattr(runtime, "agent", None)
    sources = (
        await collect_sources(agent, user, runtime.config)
        if agent is not None and user is not None
        else []
    )
    target = match_source(sources, connector)
    if target is None:
        return _error(
            f"connector '{connector}' not found; available: {_names(sources)}"
        )

    # Validate the tool name against the connector's catalog before calling.
    specs = await target.list_tools(user_id=owner_id)
    tool_names = [s.name for s in specs]
    if tool not in tool_names:
        available = ", ".join(tool_names) or "<нет>"
        return _error(
            f"connector '{target.name}' has no tool '{tool}'; "
            f"available: {available}; call {GET_INFO_TOOL_NAME}('{target.name}')"
        )

    outcome = await target.call_tool(
        tool, parsed_params, runtime, user_id=owner_id
    )

    if outcome.is_error:
        text = (
            outcome.content
            if isinstance(outcome.content, str)
            else json.dumps(outcome.content, ensure_ascii=False)
        )
        return _error(
            f"tool '{tool}' on '{target.name}' returned an error: {text}"
        )

    content = outcome.content
    content_str = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False)
    )

    attachments = list(outcome.attachments)
    if outcome.extra_attachment is not None:
        attachments.append(outcome.extra_attachment)

    additional_kwargs: dict[str, Any] = {
        "tool_name": outcome.inner_name or CALL_TOOL_NAME,
        "tool_args": parsed_params,
        "tool_attachments": attachments,
    }
    # Carry the wrapped tool's extras so ToolResultMiddleware applies its
    # semantics (not_process / not_compress / result-file naming) instead of
    # connector_call_tool's own. Absent for MCP sources (no inner BaseTool).
    if outcome.inner_extras is not None:
        additional_kwargs["effective_extras"] = outcome.inner_extras
    # Пробрасываем сигнал размещения дальше — ToolResultMiddleware._process_tool_message
    # прочитает его отсюда и сохранит при финальной пересборке ToolMessage.
    if outcome.response_widget:
        additional_kwargs["response_widget"] = True

    return ToolMessage(
        tool_call_id=runtime.tool_call_id,
        content=content_str,
        additional_kwargs=additional_kwargs,
    )
