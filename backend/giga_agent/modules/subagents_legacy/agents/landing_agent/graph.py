import json
import uuid
from typing import Literal

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    RunnableConfig,
)
from langchain_core.tools import tool
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.models.file import FileResponse
from giga_agent.modules.subagents_legacy.agents.landing_agent.config import (
    ConfigSchema,
    LandingState,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.nodes.coder import (
    coder_node,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.nodes.image import (
    image_node,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.nodes.plan import (
    plan_node,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.prompts.ru import (
    AGENT_PROMPT,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.tools import (
    coder,
    done,
    image,
    plan,
)
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)
from giga_agent.modules.subagents_legacy.uploads import build_tool_message
from giga_agent.utils.langgraph_sdk import client_session
from giga_agent.utils.messages import filter_tool_messages


async def agent(state: LandingState, config: RunnableConfig):
    prompt = ChatPromptTemplate.from_messages(
        [("system", AGENT_PROMPT), MessagesPlaceholder("messages")],
    ).partial(language="ru")
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        llm = await resolve_user_llm(user, session=session, config=config)
    chain = prompt | llm.with_config(tags=["nostream"]).bind_tools(
        [plan, image, coder, done],
        parallel_tool_calls=False,
    )
    resp = await chain.ainvoke(
        {"messages": filter_tool_messages(state.get("agent_messages", []))},
        config={"callbacks": []},
    )
    if config["configurable"].get("print_messages", False):
        resp.pretty_print()
    return {
        "agent_messages": resp,
        "image_plan_loaded": state.get("image_plan_loaded", False),
        "coder_plan_loaded": state.get("coder_plan_loaded", False),
    }


def write_to_file(file_name: str, mode: str, data):
    with open(file_name, mode) as f:
        f.write(data)


async def done_node(state: LandingState, config: RunnableConfig):
    resp = state["agent_messages"][-1]
    if resp.tool_calls and resp.tool_calls[0]["name"] == "done":
        done_str = resp.tool_calls[0]["args"]["message"]
        action = resp.tool_calls[0]
    else:
        done_str = resp.content
        action = {}

    if config["configurable"].get("save_files", False):
        raise Exception("TODO: переделать")
        # await asyncio.to_thread(Path("html").mkdir, parents=True, exist_ok=True)
        # await asyncio.to_thread(write_to_file, "html/index.html", "w", state["html"])
        # for name, value in state["images_base_64"].items():
        #     await asyncio.to_thread(
        #         write_to_file, f"html/{name}", "wb", base64.b64decode(value)
        #     )
    return {
        "agent_messages": ToolMessage(
            tool_call_id=action.get("id", str(uuid.uuid4())),
            content=json.dumps({"success": True}, ensure_ascii=False),
        ),
        "done": done_str,
    }


def router(
    state: LandingState,
) -> Literal["image", "coder", "plan_node", "done_node", "__end__"]:
    tools_calls = state["agent_messages"][-1].tool_calls
    if tools_calls:
        if tools_calls[0]["name"] == "image":
            return "image"
        if tools_calls[0]["name"] == "plan":
            return "plan_node"
        if tools_calls[0]["name"] == "coder":
            return "coder"
        return "done_node"
    return "__end__"


workflow = StateGraph(LandingState, ConfigSchema)

workflow.add_node("agent", agent)
workflow.add_node("plan_node", plan_node)
workflow.add_node("image", image_node)
workflow.add_node("coder", coder_node)
workflow.add_node("done_node", done_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", router)
workflow.add_edge("plan_node", "agent")
workflow.add_edge("image", "agent")
workflow.add_edge("coder", "agent")
workflow.add_edge("done_node", "__end__")

graph = workflow.compile()


@tool(parse_docstring=True)
async def create_landing(
    task: str, thread_id: str | None = None, runtime: ToolRuntime = None
):
    """Создает веб-страницу/лендинг.
    В task передавай максимальное детальное задания
    с учетом предыдущих сообщений пользователя

    Args:
        task: Детальное описание веб-страницы, которую пользователь хочет сделать
        thread_id: Предыдущий thread_id. Используй, если пользователю,
        нужно продолжить работу над веб-страницей

    """
    action = runtime.state["messages"][-1].tool_calls[0]
    input_data = {
        "agent_messages": [
            {
                "role": "user",
                "content": task
                + (
                    f"\nДополнительная информация: "
                    f"{runtime.state['messages'][-1].content}"
                ),
            },
        ],
        "task": task
        + f"\nДополнительная информация: {runtime.state['messages'][-1].content}",
        "plan_messages": runtime.state["messages"][:]
        + [
            ToolMessage(
                tool_call_id=action.get("id", str(uuid.uuid4())),
                content=json.dumps(
                    {"message": "Приступаю к работе!"},
                    ensure_ascii=False,
                ),
            ),
        ],
    }

    if get_settings().giga_agent_runtime == "cli":
        from giga_agent.modules.subagents_legacy.runtime import invoke_subgraph_cli

        result_state = await invoke_subgraph_cli(
            graph, input_data, runtime, thread_id=thread_id
        )
        if not thread_id:
            thread_id = str(uuid.uuid4())
    else:
        result_state = {}
        async with client_session(runtime.config) as client:
            if not thread_id:
                thread = await client.threads.create()
                thread_id = thread["thread_id"]
            push_ui_message(
                "agent_execution",
                {
                    "agent": "create_landing",
                    "node": "__start__",
                    "tool_call_id": runtime.tool_call_id,
                },
            )
            async for chunk in client.runs.stream(
                thread_id=thread_id,
                if_not_exists="create",
                assistant_id="landing",
                input=input_data,
                stream_mode=["values", "updates"],
                on_disconnect="cancel",
            ):
                if chunk.event == "values":
                    result_state = chunk.data
                elif chunk.event == "updates":
                    if "agent" in chunk.data:
                        message = chunk.data["agent"]["agent_messages"]
                        if message["tool_calls"]:
                            if message["tool_calls"][0]["name"] != "done":
                                push_ui_message(
                                    "agent_execution",
                                    {
                                        "agent": "create_landing",
                                        "node": message["tool_calls"][0]["name"],
                                        "tool_call_id": runtime.tool_call_id,
                                    },
                                )
    html_page = FileResponse.model_validate(result_state["html"])
    message = (
        f"В результате выполнения была сгенерирована HTML страница {html_page.sandbox_path}."
        f" Покажи её пользователю через "
        f'"![alt-описание](attachment:{html_page.sandbox_path})" и напиши '
        f"ответ с использованием информации из `text` и "
        f'куда двигаться пользователю дальше\nТекущий thread_id: "{thread_id}" '
        f"используй его, если пользователю нужно будет продолжить работу над страницей."
        f" Ни в коем случае не пиши thread_id пользователю — "
        f"он нужен только для параметра thread_id!"
    )
    return build_tool_message(
        runtime,
        tool_name="create_landing",
        payload={
            "text": result_state.get("done", "Страница готова"),
            "message": message,
            "thread_id": thread_id,
        },
        attachments=[html_page],
    )


# coffee = (
#     "Разработать лендинг одностраничник для продажи кофе, "
#     "ориентированного на любителей качественного кофе и тех, "
#     "кто предпочитает удобство онлайн-покупок. "
#     "Лендинг должен подчеркивать проблему отсутствия быстрого доступа"
#     " к качественному кофе и сложности выбора среди множества предложений."
#     " Основное предложение — удобный интерфейс для легкого выбора"
#     " идеального сорта и быстрая покупка высококачественной продукции."
# )
#
# async def main():
#     async for event in graph.astream(
#         {
#             "task": coffee,
#             "agent_messages": HumanMessage(content=coffee),
#         },
#         config={
#             "configurable": {"thread_id": str(uuid.uuid4()), "print_messages": False}
#         },
#     ):
#         print(event)
#     # s = await app.ainvoke(
#     #     {
#     #         "task": coffee,
#     #         "messages": HumanMessage(content=coffee),
#     #     },
#     #     config={
#     #         "configurable": {"thread_id": str(uuid.uuid4()), "print_messages": True}
#     #     },
#     # )
#     # with open("page.html", "w") as f:
#     #     f.write(s["html"])
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
