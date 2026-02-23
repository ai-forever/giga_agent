import asyncio
import collections
import copy
import json
import re
import traceback
import uuid
from datetime import datetime
from typing import Literal
from uuid import uuid4

from genson import SchemaBuilder
from langchain.tools import ToolRuntime
from langchain_core.messages import (
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.config import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.prebuilt.tool_node import _handle_tool_error
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from giga_agent.config import (
    AGENT_MAP,
    REPL_TOOLS,
    SERVICE_TOOLS,
    TOOLS_AGENT_CHECKS,
    AgentState,
    load_llm,
    run_checks,
)
from giga_agent.prompts.few_shots import FEW_SHOTS_ORIGINAL, FEW_SHOTS_UPDATED
from giga_agent.prompts.main_prompt import SYSTEM_PROMPT
from giga_agent.repl_tools.utils import describe_repl_tool
from giga_agent.settings import settings
from giga_agent.tool_server.tool_client import ToolClient
from giga_agent.tool_server.utils import transform_tool
from giga_agent.tools.rag import get_rag_info
from giga_agent.utils.jupyter import JupyterClient, prepend_code
from giga_agent.utils.lang import LANG
from giga_agent.utils.mcp import process_mcp_content
from giga_agent.utils.memory import format_memories, get_memory
from giga_agent.utils.tools import inject_tool_args

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
Вызывай эти методы, только через именованные аргументы"""  # noqa: E501


prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
    ]
    + (FEW_SHOTS_ORIGINAL if settings.features.repl_from_message else FEW_SHOTS_UPDATED)
    + [MessagesPlaceholder("messages", optional=True)],
).partial(repl_inner_tools=generate_repl_tools_description(), language=LANG)


def generate_user_info(state: AgentState):
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


def get_code_arg(message):
    regex = r"```python(.+?)```"
    matches = re.findall(regex, message, re.DOTALL)
    if matches:
        return "\n".join(matches).strip()


client = JupyterClient()


async def before_agent(state: AgentState):
    tool_client = ToolClient()
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
        if settings.llm.giga_agent_memory_enabled:
            memory = await get_memory()
            retrieved_memories = await memory.search(user_input, user_id="default_user")
            memory_context = f"<memory>{format_memories(retrieved_memories)}</memory>\n"
        else:
            memory_context = ""
        state["messages"][-1].content = (
            f"<task>{user_input}</task> "
            f"Активно планируй и следуй своему плану! "
            f"Действуй по простым шагам!"
            f"{generate_user_info(state)}\n"
            f"{memory_context}"
            f"{file_prompt}\n"
            f"{selected_prompt}\n"
            f"Следующий шаг: "
        )
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
"""  # noqa: E501

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
"""  # noqa: E501


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
            },
        )
        for tool in state.get("mcp_tools", [])
    ]
    ch = (prompt | llm.bind_tools(state["tools"] + mcp_tools)).with_retry()
    message = await ch.ainvoke(
        {
            "messages": state["messages"],
            "rag_info": get_rag_info(state.get("collections", [])),
            "user_instructions": get_user_notes(state),
            "user_secrets": await get_user_secrets(state),
        },
    )
    message.additional_kwargs.pop("function_call", None)
    message.additional_kwargs["rendered"] = True
    for call in message.tool_calls:
        # Проставляем ID вызовов тулов, если их нет, как в гиге
        call.setdefault("id", str(uuid.uuid4()))
    return {"messages": [message]}


async def process_tool_result(
    state, result, action, tool_attachments, tool_call_index, message=""
):
    if result:
        add_data = {
            "data": result,
            "message": message
            + (
                f"Результат функции сохранен в переменную "
                f"`function_results[{tool_call_index}]['data']` "
            ),
        }
        await client.execute(
            state.get("kernel_id"),
            f"function_results.append({add_data!r})",
        )
        if (
            len(json.dumps(result, ensure_ascii=False)) > 10000 * 4
            and action.get("name") not in AGENT_MAP
        ):
            schema = SchemaBuilder()
            schema.add_object(obj=add_data.pop("data"))
            add_data["message"] += (
                "Результат функции вышел слишком длинным изучи результат функции в "
                "переменной с помощью python. Схема данных:\n"
            )
            add_data["schema"] = schema.to_schema()
        if action.get("name") == "get_urls":
            add_data["message"] += result.pop("attention")
    else:
        if message:
            result = {"result": result, "message": message}
        add_data = result
    return ToolMessage(
        tool_call_id=action.get("id"),
        content=json.dumps(add_data, ensure_ascii=False),
        additional_kwargs={
            "tool_attachments": tool_attachments,
            "tool_name": action.get("name"),
        },
    )


async def tool_call(state: AgentState, config: RunnableConfig, runtime: Runtime):
    actions = copy.deepcopy(state["messages"][-1].tool_calls)
    action_map = {action.get("id"): action for action in actions}
    mcp_tool_names = [tool.get("name") for tool in state.get("mcp_tools", [])]
    frontend_actions = [
        action for action in actions if action.get("name") in mcp_tool_names
    ]
    backend_actions = [
        action for action in actions if action.get("name") not in mcp_tool_names
    ]
    if frontend_actions:
        value = interrupt(
            {
                "type": "tool_call",
                "tools": frontend_actions,
            },
        )
    else:
        value = interrupt({"type": "approve"})
    if value.get("type") == "comment":
        tool_message = (
            f"Пользователь оставил комментарий к твоему вызову инструмента. "
            f'Прочитай его и реши, как действовать дальше: "{value.get("message")}"'
        )
        tools_response = [
            ToolMessage(
                tool_call_id=action.get("id", str(uuid4())),
                content=json.dumps(
                    {
                        "message": tool_message,
                    },
                    ensure_ascii=False,
                ),
                additional_kwargs={"tool_name": action.get("name")},
            )
            for action in actions
        ]
        return {
            "messages": tools_response,
        }

    tool_client = ToolClient()
    tool_client.set_state_data(
        config["metadata"]["thread_id"],
        config["metadata"]["checkpoint_id"],
    )
    tool_call_index = state.get("tool_call_index", -1)
    tool_responses = []
    if frontend_actions:
        for result in value.get("results", []):
            data, tool_attachments, message = await process_mcp_content(
                result.get("result", {}).get("content", {}),
                config["metadata"]["thread_id"],
            )
            tool_call_index += 1
            tool_responses.append(
                await process_tool_result(
                    state,
                    data,
                    action_map[result.get("id")],
                    tool_attachments,
                    tool_call_index,
                    message,
                )
            )
    tool_tasks = {}
    python_tasks = collections.OrderedDict()
    for action in backend_actions:
        if action.get("name") == "python":
            if settings.features.repl_from_message:
                action["args"]["code"] = get_code_arg(state["messages"][-1].content)
            else:
                # На случай если гига отправить в аргумент ```python(.+)``` строку
                code_arg = get_code_arg(action["args"].get("code", ""))
                if code_arg:
                    action["args"]["code"] = code_arg
            if "code" not in action["args"] or not action["args"]["code"]:
                tool_responses.append(
                    ToolMessage(
                        tool_call_id=action.get("id"),
                        content=json.dumps(
                            {"message": "Напиши код в своем сообщении!"},
                            ensure_ascii=False,
                        ),
                        additional_kwargs={"tool_name": action.get("name")},
                    ),
                )
                continue
            action["args"]["code"] = prepend_code(
                action["args"]["code"],
                state,
                config["metadata"]["thread_id"],
                config["metadata"]["checkpoint_id"],
            )
        tasks = tool_tasks
        if action.get("name") == "python":
            tasks = python_tasks
        if action.get("name") not in AGENT_MAP:
            tasks[action.get("id")] = tool_client.aexecute(
                action.get("name"),
                action.get("args"),
            )
        else:
            injected_args = inject_tool_args(
                AGENT_MAP[action.get("name")],
                action,
                ToolRuntime(
                    state=state,
                    tool_call_id=action.get("id"),
                    config=config,
                    context=runtime.context,
                    store=runtime.store,
                    stream_writer=runtime.stream_writer,
                ),
            )["args"]
            tasks[action.get("id")] = AGENT_MAP[action.get("name")].ainvoke(
                injected_args
            )
    results = await asyncio.gather(*tool_tasks.values(), return_exceptions=True)
    # Задачи на python выполняем последовательно
    if python_tasks:
        for action_id, task in python_tasks.items():
            try:
                results.append(await task)
            except Exception as e:
                results.append(e)
            if settings.features.repl_from_message:
                break
        # Если мы выполняем код из сообщения (что вообще странно),
        # то мы выполняем тул только один раз
        if settings.features.repl_from_message:
            results += [{"message": "Смотри результат первого тула python"}] * (
                len(python_tasks.keys()) - 1
            )
    for result, action_id in zip(
        results, list(tool_tasks.keys()) + list(python_tasks.keys())
    ):
        action = action_map[action_id]
        if isinstance(result, Exception):
            tool_responses.append(
                ToolMessage(
                    tool_call_id=action.get("id"),
                    content=_handle_tool_error(result, flag=True),
                    additional_kwargs={"tool_name": action.get("name")},
                    status="error",
                )
            )
        else:
            try:
                result = json.loads(result)
            except Exception:
                pass
            tool_call_index += 1
            tool_responses.append(
                await process_tool_result(
                    state,
                    result,
                    action,
                    (
                        result.pop("giga_attachments") or []
                        if isinstance(result, dict) and "giga_attachments" in result
                        else []
                    ),
                    tool_call_index,
                )
            )

    return {
        "messages": tool_responses,
        "tool_call_index": tool_call_index,
    }


async def _background_save_memory(human_content, ai_content):
    try:
        memory = await get_memory()
        interaction = [
            {"role": "user", "content": human_content},
            {"role": "assistant", "content": ai_content},
        ]
        await memory.add(interaction, user_id="default_user")
    except Exception:
        traceback.print_exc()


async def save_memory(state: AgentState):
    """Сохраняет сообщения пользователя"""
    if not settings.llm.giga_agent_memory_enabled:
        return {}
    messages = state["messages"]
    last_human = next((m for m in reversed(messages) if m.type == "human"), None)
    last_ai = messages[-1]

    if last_human and last_ai.type == "ai":
        asyncio.create_task(
            _background_save_memory(last_human.content, last_ai.content),
        )
    return {}


def router(state: AgentState) -> Literal["tool_call", "save_memory"]:
    if state["messages"][-1].tool_calls:
        return "tool_call"
    return "save_memory"


workflow = StateGraph(AgentState)
workflow.add_node(before_agent)
workflow.add_node(agent)
workflow.add_node(tool_call)
workflow.add_node(save_memory)
workflow.add_edge("__start__", "before_agent")
workflow.add_edge("before_agent", "agent")
workflow.add_conditional_edges(
    "agent",
    router,
    {"tool_call": "tool_call", "save_memory": "save_memory"},
)
workflow.add_edge("tool_call", "agent")
workflow.add_edge("save_memory", "__end__")

graph = workflow.compile()
