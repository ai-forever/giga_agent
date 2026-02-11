from datetime import datetime
from typing import Any, Callable, Awaitable

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command


def generate_user_info(state: AgentState):
    # TODO: Вынести это в настройки пользователя и подтягивать оттуда
    LANG = "ru"
    lang = ""
    if not LANG.startswith("ru"):
        lang = f"\nВыбранный язык пользователя: {LANG}\n"
    instructions = ""
    if not state["messages"]:
        instructions = state.get("instructions", "")
    return (
        f"<user_info>\n"
        f"Текущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}"
        f"{lang}{instructions}</user_info>"
    )


class CoreFirstMiddleware(AgentMiddleware):
    """
    Здесь хранится логика,
    где мы передаем информацию о файлах просим выполнять задачу по шагам и т.д.
    """

    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        if state["messages"][-1].type == "human":
            user_input = state["messages"][-1].content
            files = state["messages"][-1].additional_kwargs.get("files", [])
            file_prompt = []
            for idx, file in enumerate(files):
                file_prompt.append(f"""Файл загружен по пути: '{file["path"]}'""")
                if "image_path" in file:
                    file_prompt[-1] += (
                        f"\nФайл является изображением его можно отобразить с помощью: "
                        f"'![алт-текст](attachment:{file['image_path']})'."
                    )
            file_prompt = (
                "<files_data>" + "\n----\n".join(file_prompt) + "</files_data>"
                if file_prompt
                else ""
            )
            selected = state["messages"][-1].additional_kwargs.get("selected", {})
            selected_items = []
            for key, value in selected.items():
                selected_items.append(f"""![{value}](attachment:{key})""")
            selected_prompt = ""
            if selected_items:
                selected_items = "\n".join(selected_items)
                selected_prompt = (
                    f"Пользователь указал на следующие вложения: \n{selected_items}"
                )
            state["messages"][-1].content = (
                f"<task>{user_input}</task> "
                f"{generate_user_info(state)}\n"
                f"{file_prompt}\n"
                f"{selected_prompt}\n"
            )
            return {"messages": state["messages"][-1]}
        return None


class CoreLastMiddleware(AgentMiddleware):
    async def before_agent(
        self, state: AgentState, runtime: Runtime[Context], config: RunnableConfig
    ) -> dict[str, Any] | None:
        if state["messages"][-1].type == "human":
            state["messages"][-1].content += (
                f"Активно планируй и следуй своему плану! "
                f"Действуй по простым шагам!"
                f"Следующий шаг: "
            )
            return {"messages": state["messages"][-1]}
        return None
