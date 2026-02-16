from langchain_core.tools import tool
from pydantic import Field


@tool(parse_docstring=True)
async def image(additional_info: str = ""):
    """Формирует список изображений

    Args:
        additional_info: Дополнительная информация

    """


@tool(parse_docstring=True)
async def coder(additional_info: str = ""):
    """Пишет код веб-страницы

    Args:
        additional_info: Дополнительная информация

    """


@tool(parse_docstring=True)
async def plan(additional_info: str = ""):
    """Планирует как нужно будет делать веб-страницу

    Args:
        additional_info: Дополнительная информация

    """


@tool
def done(message: str = Field(description="Краткая информация по проделанной работе")):
    """Завершает работу, когда результат удовлетворяет требованиям."""
