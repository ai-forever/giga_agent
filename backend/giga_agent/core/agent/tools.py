"""Core agent tools available to all agents."""

from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from giga_agent.core.agent.think import (
    MAX_FORCED_THINK_FOLLOWUPS,
    THINK_HOP_RESULT,
    _count_trailing_think_tool_pairs,
    _is_shallow_think,
)
from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras


class ThinkArgsSchema(BaseModel):
    thoughts: str = Field(
        description=(
            "Кратко: что нового узнал (1-2 предложения), следующий шаг и зачем. "
            "Если есть реальный риск или развилка — назови; если нет — пропусти, "
            "не выдумывай. Не повторяй данные из результатов инструментов."
        )
    )


@tool(
    extras=tool_extras(
        ToolEffect.READ,
        repl_skip=True,
        repl_save=False,
        not_process=True,
    ),
    args_schema=ThinkArgsSchema,
)
def think(thoughts: str, runtime: ToolRuntime) -> str:
    """Твой внутренний голос для рассуждений. Вызывай там, где это реально помогает: на сложных задачах с несколькими шагами, при ошибке/неожиданном результате, на развилке между подходами, перед необратимым действием и перед финальным ответом по комплексной задаче. На очевидных и одношаговых запросах — не нужен.

    Args:
        thoughts: Твои рассуждения
    """
    messages = runtime.state.get("messages", [])
    if isinstance(messages, list) and messages:
        # state ends with the current AIMessage (think call); completed pairs
        # are counted from everything *before* it, then +1 for this call.
        preceding = messages[:-1]
        trailing = _count_trailing_think_tool_pairs(preceding)
        # Force a second hop only when the first think looks shallow —
        # a long, structured first think gets to act immediately.
        if trailing + 1 < MAX_FORCED_THINK_FOLLOWUPS and _is_shallow_think(thoughts):
            return THINK_HOP_RESULT
    return ""


MULTI_TOOL_USE_NAME = "multi_tool_use"


class ToolUse(BaseModel):
    recipient_name: str = Field(description="Имя инструмента, который будет вызван")
    parameters: str = Field(description="JSON-строка с параметрами инструмента")


class MultiToolUseArgsSchema(BaseModel):
    tool_uses: list[ToolUse] = Field(
        description="Список вызовов инструментов. "
        "Каждый элемент содержит recipient_name и parameters."
    )


@tool(
    extras=tool_extras(
        ToolEffect.DELEGATED,
        repl_skip=True,
        repl_save=False,
        not_process=True,
    ),
    args_schema=MultiToolUseArgsSchema,
)
async def multi_tool_use(tool_uses: list[ToolUse]) -> dict[str, Any]:
    """Инструмент для параллельного вызова нескольких инструментов.

    Args:
        tool_uses: Список вызовов инструментов. Каждый элемент должен содержать
            recipient_name и parameters.
    """
    return {"ok": True, "tool_uses": tool_uses, "mock": True}
