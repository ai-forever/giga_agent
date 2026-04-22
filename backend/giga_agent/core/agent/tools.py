"""Core agent tools available to all agents."""

from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, Field


class ThinkArgsSchema(BaseModel):
    thoughts: str = Field(
        description="Твои рассуждения"
    )


@tool(
    extras={"repl_skip": True, "repl_save": False, "not_process": True},
    args_schema=ThinkArgsSchema,
)
def think(thoughts: str) -> str:
    """Твой внутренний голос для рассуждений. Вызывай часто: перед началом задачи, после каждого результата инструмента, при ошибках, на переходах между этапами и перед финальным ответом. Используй для планирования, анализа результатов, проверки корректности и выбора следующего действия.

    Args:
        thoughts: Твои рассуждения
    """
    return {}


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
    extras={"repl_skip": True, "repl_save": False, "not_process": True},
    args_schema=MultiToolUseArgsSchema,
)
async def multi_tool_use(tool_uses: list[ToolUse]) -> dict[str, Any]:
    """Инструмент для параллельного вызова нескольких инструментов.

    Args:
        tool_uses: Список вызовов инструментов. Каждый элемент должен содержать
            recipient_name и parameters.
    """
    return {"ok": True, "tool_uses": tool_uses, "mock": True}
