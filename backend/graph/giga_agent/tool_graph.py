import copy
import json
import re
import traceback
from datetime import datetime
from typing import Literal
from uuid import uuid4

from genson import SchemaBuilder

from langchain_core.messages import (
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph
from langgraph.prebuilt.tool_node import _handle_tool_error, ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from giga_agent.config import (
    AgentState,
    REPL_TOOLS,
    SERVICE_TOOLS,
    AGENT_MAP,
    load_llm,
)
from giga_agent.prompts.few_shots import FEW_SHOTS_ORIGINAL, FEW_SHOTS_UPDATED
from giga_agent.prompts.main_prompt import SYSTEM_PROMPT
from giga_agent.repl_tools.utils import describe_repl_tool
from giga_agent.tool_server.tool_client import ToolClient
from giga_agent.settings import settings

from giga_agent.utils.jupyter import JupyterClient
from giga_agent.utils.lang import LANG
from giga_agent.utils.python import prepend_code


llm = load_llm(is_main=True)


def generate_repl_tools_description():
    repl_tools = []
    for repl_tool in REPL_TOOLS:
        repl_tools.append(describe_repl_tool(repl_tool))
    service_tools = [tool.name for tool in SERVICE_TOOLS]
    repl_tools = "\n".join(repl_tools)
    return f"""В коде есть дополнительные функции:
```
{repl_tools}
```
Также ты можешь вызвать из кода следующие функции: {service_tools}. Аргументы и описания этих функций описаны в твоих функциях!
Вызывай эти методы, только через именованные агрументы"""


prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
    ]
    + (FEW_SHOTS_ORIGINAL if settings.features.repl_from_message else FEW_SHOTS_UPDATED)
    + [MessagesPlaceholder("messages", optional=True)]
).partial(repl_inner_tools=generate_repl_tools_description(), language=LANG)


def generate_user_info(state: AgentState):
    lang = ""
    if not LANG.startswith("ru"):
        lang = f"\nВыбранный язык пользователя: {LANG}\n"
    return f"<user_info>\nТекущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}{lang}</user_info>"


def get_code_arg(message):
    regex = r"```python(.+?)```"
    matches = re.findall(regex, message, re.DOTALL)
    if matches:
        return "\n".join(matches).strip()


client = JupyterClient(base_url=settings.internal.jupyter_client_api)


async def agent(state: AgentState):
    tool_client = ToolClient(base_url=settings.internal.tool_client_api)
    kernel_id = state.get("kernel_id")
    tools = state.get("tools")
    file_ids = []
    if not kernel_id:
        kernel_id = (await client.start_kernel())["id"]
        await client.execute(kernel_id, "function_results = []")
    if not tools:
        tools = await tool_client.get_tools()
    ch = (prompt | llm.bind_tools(tools, parallel_tool_calls=False)).with_retry()
    if state["messages"][-1].type == "human":
        user_input = state["messages"][-1].content
        files = state["messages"][-1].additional_kwargs.get("files", [])
        file_prompt = []
        for idx, file in enumerate(files):
            file_prompt.append(
                f"""Файл ![](graph:{idx})\nЗагружен по пути: '{file["path"]}'"""
            )
            if "file_id" in file:
                file_prompt[-1] += (
                    f"\nФайл является изображением его id: '{file['file_id']}'"
                )
                file_ids.append(file["file_id"])
        file_prompt = (
            "<files_data>" + "\n----\n".join(file_prompt) + "</files_data>"
            if len(file_prompt)
            else ""
        )
        selected = state["messages"][-1].additional_kwargs.get("selected", {})
        selected_items = []
        for key, value in selected.items():
            selected_items.append(f"""![{value}](graph:{key})""")
        selected_prompt = ""
        if selected_items:
            selected_items = "\n".join(selected_items)
            selected_prompt = (
                f"Пользователь указал на следующие вложения: \n{selected_items}"
            )
        state["messages"][
            -1
        ].content = f"<task>{user_input}</task> Активно планируй и следуй своему плану! Действуй по простым шагам!{generate_user_info(state)}\n{file_prompt}\n{selected_prompt}\nСледующий шаг: "
    message = await ch.ainvoke({"messages": state["messages"]})
    message.additional_kwargs.pop("function_call", None)
    message.additional_kwargs["rendered"] = True
    return {
        "messages": [state["messages"][-1], message],
        "kernel_id": kernel_id,
        "tools": tools,
        "file_ids": file_ids,
    }


async def tool_call(
    state: AgentState,
    store: BaseStore,
):
    tool_client = ToolClient(base_url=settings.internal.tool_client_api)
    action = copy.deepcopy(state["messages"][-1].tool_calls[0])
    value = interrupt({"type": "approve"})
    if value.get("type") == "comment":
        return {
            "messages": ToolMessage(
                tool_call_id=action.get("id", str(uuid4())),
                content=json.dumps(
                    {
                        "message": f'Пользователь оставил комментарий к твоему вызову инструмента. Прочитай его и реши, как действовать дальше: "{value.get("message")}"'
                    },
                    ensure_ascii=False,
                ),
            )
        }
    tool_call_index = state.get("tool_call_index", -1)
    if action.get("name") == "python":
        if settings.features.repl_from_message:
            action["args"]["code"] = get_code_arg(state["messages"][-1].content)
        else:
            # На случай если гига отправить в аргумент ```python(.+)``` строку
            code_arg = get_code_arg(action["args"].get("code"))
            if code_arg:
                action["args"]["code"] = code_arg
        if "code" not in action["args"] or not action["args"]["code"]:
            return {
                "messages": ToolMessage(
                    tool_call_id=action.get("id", str(uuid4())),
                    content=json.dumps(
                        {"message": "Напиши код в своем сообщении!"},
                        ensure_ascii=False,
                    ),
                )
            }
        action["args"]["code"] = prepend_code(action["args"]["code"], state)
    file_ids = []
    try:
        state_ = copy.deepcopy(state)
        state_.pop("messages")
        tool_client.set_state(state_)
        if action.get("name") not in AGENT_MAP:
            result = await tool_client.aexecute(action.get("name"), action.get("args"))
        else:
            tool_node = ToolNode(tools=list(AGENT_MAP.values()))
            injected_args = tool_node.inject_tool_args(
                {"name": action.get("name"), "args": action.get("args"), "id": "123"},
                state,
                None,
            )["args"]
            result = await AGENT_MAP[action.get("name")].ainvoke(injected_args)
        tool_call_index += 1
        try:
            result = json.loads(result)
        except Exception as e:
            pass
        if result:
            add_data = {
                "data": result,
                "message": f"Результат функции сохранен в переменную `function_results[{tool_call_index}]['data']` ",
            }
            await client.execute(
                state.get("kernel_id"), f"function_results.append({repr(add_data)})"
            )
            if (
                len(json.dumps(result, ensure_ascii=False)) > 10000 * 4
                and action.get("name") not in AGENT_MAP
            ):
                schema = SchemaBuilder()
                schema.add_object(obj=add_data.pop("data"))
                add_data["message"] += (
                    f"Результат функции вышел слишком длинным изучи результат функции в переменной с помощью python. Схема данных:\n"
                )
                add_data["schema"] = schema.to_schema()
            if action.get("name") == "get_urls":
                add_data["message"] += result.pop("attention")
        else:
            add_data = result
        tool_attachments = []
        if isinstance(result, dict) and "giga_attachments" in result:
            add_data = result
            attachments = result.pop("giga_attachments")
            file_ids = [attachment["file_id"] for attachment in attachments]
            for attachment in attachments:
                if attachment["type"] == "text/html":
                    await store.aput(
                        ("html",),
                        attachment["file_id"],
                        attachment,
                        ttl=None,
                        index=False,
                    )
                elif attachment["type"] == "audio/mp3":
                    await store.aput(
                        ("audio",),
                        attachment["file_id"],
                        attachment,
                        ttl=None,
                        index=False,
                    )
                else:
                    await store.aput(
                        ("attachments",),
                        attachment["file_id"],
                        attachment,
                        ttl=None,
                        index=False,
                    )

                tool_attachments.append(
                    {
                        "type": attachment["type"],
                        "file_id": attachment["file_id"],
                    }
                )
        message = ToolMessage(
            tool_call_id=action.get("id", str(uuid4())),
            content=json.dumps(add_data, ensure_ascii=False),
            additional_kwargs={"tool_attachments": tool_attachments},
        )
    except Exception as e:
        traceback.print_exc()
        message = ToolMessage(
            tool_call_id=action.get("id", str(uuid4())),
            content=_handle_tool_error(e, flag=True),
        )

    return {
        "messages": [message],
        "tool_call_index": tool_call_index,
        "file_ids": file_ids,
    }


def router(state: AgentState) -> Literal["tool_call", "__end__"]:
    if state["messages"][-1].tool_calls:
        return "tool_call"
    else:
        return "__end__"


workflow = StateGraph(AgentState)
workflow.add_node(agent)
workflow.add_node(tool_call)
workflow.add_edge("__start__", "agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("tool_call", "agent")


graph = workflow.compile()
