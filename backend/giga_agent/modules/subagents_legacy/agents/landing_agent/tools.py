from langchain_core.tools import tool
from pydantic import Field

from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    tool_extras,
)


_CONTROL_EXTRAS = tool_extras(ToolEffect.WRITE, plan_mode=ToolPlanMode.ALLOW)


@tool(parse_docstring=True, extras=_CONTROL_EXTRAS)
async def image(additional_info: str = ""):
    """Формирует список изображений

    Args:
        additional_info: Дополнительная информация

    """


@tool(parse_docstring=True, extras=_CONTROL_EXTRAS)
async def coder(additional_info: str = ""):
    """Пишет код веб-страницы

    Args:
        additional_info: Дополнительная информация

    """


@tool(parse_docstring=True, extras=_CONTROL_EXTRAS)
async def plan(additional_info: str = ""):
    """Планирует как нужно будет делать веб-страницу

    Args:
        additional_info: Дополнительная информация

    """


@tool(extras=_CONTROL_EXTRAS)
def done(message: str = Field(description="Краткая информация по проделанной работе")):
    """Завершает работу, когда результат удовлетворяет требованиям."""
