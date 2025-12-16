from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from giga_agent.tools.python import ExecuteTool


@tool(parse_docstring=True)
async def shell(
    command: str,
    state: Annotated[dict, InjectedState],
    config: RunnableConfig,
):
    """Выполняет Shell-команду в Jupyter ноутбуке.
    Используй, если нужно выполнить shell-комманду в ОС пользователя. Также обязательно используй, если нужно что-то установить из pipy.

    Args:
        command: Shell-команда

    """
    jupyter_executor = ExecuteTool(
        kernel_id=state["kernel_id"],
        thread_id=config["configurable"]["thread_id"],
    )
    return (
        await jupyter_executor.ainvoke(
            {"code": f"!{command}" if not command.startswith("!") else command},
        )
    )["message"]
