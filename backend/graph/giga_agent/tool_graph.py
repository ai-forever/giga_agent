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
from langgraph.types import interrupt
from langgraph.config import RunnableConfig

from giga_agent.config import (
    AgentState,
    REPL_TOOLS,
    SERVICE_TOOLS,
    AGENT_MAP,
    load_llm,
    TOOLS_AGENT_CHECKS,
    run_checks,
)
from giga_agent.prompts.few_shots import FEW_SHOTS_ORIGINAL, FEW_SHOTS_UPDATED
from giga_agent.prompts.main_prompt import SYSTEM_PROMPT
from giga_agent.repl_tools.utils import describe_repl_tool
from giga_agent.tool_server.tool_client import ToolClient
from giga_agent.tool_server.utils import transform_tool
from giga_agent.tools.rag import get_rag_info
from giga_agent.settings import settings

from giga_agent.utils.jupyter import JupyterClient, prepend_code
from giga_agent.utils.lang import LANG
from giga_agent.utils.mcp import process_mcp_content
from giga_agent.utils.memory import format_memories, get_memory


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
    instructions = ""
    if not state["messages"]:
        instructions = state.get("instructions", "")
    return f"<user_info>\nТекущая дата: {datetime.today().strftime('%d.%m.%Y %H:%M')}{lang}{instructions}</user_info>"


def get_code_arg(message):
    regex = r"```python(.+?)```"
    matches = re.findall(regex, message, re.DOTALL)
    if matches:
        return "\n".join(matches).strip()


client = JupyterClient()


async def before_agent(state: AgentState):
    tool_client = ToolClient()
    memory = await get_memory()
    kernel_id = state.get("kernel_id")
    tools = state.get("tools")
    if not kernel_id:
        kernel_id = (await client.start_kernel())["id"]
        await client.execute(kernel_id, "function_results = []\nSECRETS = {}")
    if not tools:
        tools = await tool_client.get_tools()
    if state["messages"][-1].type == "human":
        user_input = state["messages"][-1].content
        files = state["messages"][-1].additional_kwargs.get("files", [])
        file_prompt = []
        for idx, file in enumerate(files):
            file_prompt.append(f"""Файл загружен по пути: '{file['path']}'""")
            if "image_path" in file:
                file_prompt[
                    -1
                ] += f"\nФайл является изображением его можно отобразить с помощью: '![алт-текст](attachment:{file['image_path']})'."
        file_prompt = (
            "<files_data>" + "\n----\n".join(file_prompt) + "</files_data>"
            if len(file_prompt)
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
        retrieved_memories = await memory.search(user_input, user_id="default_user")
        memory_context = format_memories(retrieved_memories)
        state["messages"][
            -1
        ].content = f"<task>{user_input}</task> Активно планируй и следуй своему плану! Действуй по простым шагам!{generate_user_info(state)}\n<memory>{memory_context}</memory>\n{file_prompt}\n{selected_prompt}\nСледующий шаг: "
    filtered_tools = []
    for tool in tools:
        if tool["name"] in TOOLS_AGENT_CHECKS:
            if not await run_checks(tool_name=tool["name"], state=state):
                continue
        filtered_tools.append(tool)
    return {
        "messages": [state["messages"][-1]],
        "kernel_id": kernel_id,
        "tools": filtered_tools,
    }


NOTES_PROMPT = """
====

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ

Эти инструкции уточняют стиль и ожидания пользователя. Ты ОБЯЗАН учитывать их при выполнении каждой задачи.

---
{0}
---

====
"""

SECRETS_PROMPTS = """
====

СЕКРЕТЫ (SECRETS)

Пользователь предоставил тебе доступ к конфиденциальным данным (токенам, API ключам, паролям и другим секретам).

# Правила работы с секретами

1. **Доступ в коде**: Все секреты доступны в инструменте `python` через словарь `SECRETS`.
2. **Синтаксис использования**: 
   ```python
   # Получение значения секрета
   api_key = SECRETS["название_секрета"]
   token = SECRETS["github_token"]
   ```
3. **БЕЗОПАСНОСТЬ (КРИТИЧНО)**:
   - НИКОГДА не выводи значения секретов в открытом виде
   - НИКОГДА не включай значения секретов в print(), return или любой другой вывод
   - НИКОГДА не передавай значения секретов в сообщениях пользователю
   - МОЖНО упоминать названия секретов (например: "Использую секрет 'api_key'")
   - МОЖНО упоминать описания секретов
   - МОЖНО говорить о типе секрета (токен, пароль, ключ)
4. **Обработка ошибок**: Если секрет не найден, сообщи пользователю название отсутствующего секрета, но НЕ его значение.

# Доступные секреты

{0}
====
"""


def get_user_notes(state: AgentState):
    instructions = settings.llm.giga_agent_user_notes + state.get("instructions", "")
    if instructions:
        return NOTES_PROMPT.format(instructions)
    return ""


async def get_user_secrets(state: AgentState):
    user_secrets = state.get("secrets", [])
    if not user_secrets:
        return ""
    secret_parts = []
    code_parts = []
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
        code_parts.append(f"SECRETS['{name}'] = '{value}'")
    await client.execute(state.get("kernel_id"), "\n".join(code_parts))
    return SECRETS_PROMPTS.format("\n".join(secret_parts))


async def agent(state: AgentState):
    mcp_tools = [
        transform_tool(
            {
                "name": tool["name"],
                "description": tool.get("description", "."),
                "parameters": tool.get("inputSchema", {}),
            }
        )
        for tool in state.get("mcp_tools", [])
    ]
    ch = (
        prompt | llm.bind_tools(state["tools"] + mcp_tools, parallel_tool_calls=False)
    ).with_retry()
    message = await ch.ainvoke(
        {
            "messages": state["messages"],
            "rag_info": get_rag_info(state.get("collections", [])),
            "user_instructions": get_user_notes(state),
            "user_secrets": await get_user_secrets(state),
        }
    )
    message.additional_kwargs.pop("function_call", None)
    message.additional_kwargs["rendered"] = True
    return {"messages": [message]}


async def tool_call(state: AgentState, config: RunnableConfig):
    action = copy.deepcopy(state["messages"][-1].tool_calls[0])
    is_frontend_tool = False
    for tool in state.get("mcp_tools", []):
        if tool.get("name") == action.get("name"):
            is_frontend_tool = True
            break
    if is_frontend_tool:
        value = interrupt(
            {
                "type": "tool_call",
                "tool_name": action.get("name"),
                "args": action.get("args"),
            }
        )
    else:
        value = interrupt({"type": "approve"})
    tool_client = ToolClient()
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
    if action.get("name") == "python" and not is_frontend_tool:
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
        action["args"]["code"] = prepend_code(
            action["args"]["code"],
            state,
            config["metadata"]["thread_id"],
            config["metadata"]["checkpoint_id"],
        )
    try:
        tool_attachments = []
        if not is_frontend_tool:
            message = ""
            state_ = copy.deepcopy(state)
            state_.pop("messages")
            tool_client.set_state_data(
                config["metadata"]["thread_id"], config["metadata"]["checkpoint_id"]
            )
            if action.get("name") not in AGENT_MAP:
                result = await tool_client.aexecute(
                    action.get("name"), action.get("args")
                )
            else:
                tool_node = ToolNode(tools=list(AGENT_MAP.values()))
                injected_args = tool_node.inject_tool_args(
                    {
                        "name": action.get("name"),
                        "args": action.get("args"),
                        "id": "123",
                    },
                    state,
                    None,
                )["args"]
                result = await AGENT_MAP[action.get("name")].ainvoke(injected_args)
            try:
                result = json.loads(result)
            except Exception as e:
                pass
        else:
            result, tool_attachments, message = await process_mcp_content(
                value.get("result", {}).get("content", {}),
                config["metadata"]["thread_id"],
            )
        tool_call_index += 1

        if result:
            add_data = {
                "data": result,
                "message": message
                + f"Результат функции сохранен в переменную `function_results[{tool_call_index}]['data']` ",
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
                add_data[
                    "message"
                ] += f"Результат функции вышел слишком длинным изучи результат функции в переменной с помощью python. Схема данных:\n"
                add_data["schema"] = schema.to_schema()
            if action.get("name") == "get_urls":
                add_data["message"] += result.pop("attention")
        else:
            if message:
                result = {"result": result, "message": message}
            add_data = result
        if isinstance(result, dict) and "giga_attachments" in result:
            add_data = result
            tool_attachments = result.pop("giga_attachments")
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
    }


async def save_memory(state: AgentState):
    """
    Сохраняет сообщения пользователя
    """
    messages = state["messages"]
    last_human = next((m for m in reversed(messages) if m.type == "human"), None)
    last_ai = messages[-1]

    if last_human and last_ai.type == "ai":
        memory = await get_memory()
        interaction = [
            {"role": "user", "content": last_human.content},
            {"role": "assistant", "content": last_ai.content},
        ]
        await memory.add(interaction, user_id="default_user")
    return {}


def router(state: AgentState) -> Literal["tool_call", "save_memory"]:
    if state["messages"][-1].tool_calls:
        return "tool_call"
    else:
        return "save_memory"


workflow = StateGraph(AgentState)
workflow.add_node(before_agent)
workflow.add_node(agent)
workflow.add_node(tool_call)
workflow.add_node(save_memory)
workflow.add_edge("__start__", "before_agent")
workflow.add_edge("before_agent", "agent")
workflow.add_conditional_edges(
    "agent", router, {"tool_call": "tool_call", "save_memory": "save_memory"}
)
workflow.add_edge("tool_call", "agent")
workflow.add_edge("save_memory", "__end__")

graph = workflow.compile()
