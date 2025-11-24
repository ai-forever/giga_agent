import asyncio
import base64
import json
import uuid
from pathlib import Path
from typing import Literal, Optional, Annotated

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    RunnableConfig,
)
from langchain_core.tools import tool
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState
from langgraph_sdk import get_client

from giga_agent.agents.landing_agent.config import LandingState, llm, ConfigSchema
from giga_agent.agents.landing_agent.nodes.coder import coder_node
from giga_agent.agents.landing_agent.nodes.image import image_node
from giga_agent.agents.landing_agent.nodes.plan import plan_node
from giga_agent.agents.landing_agent.tools import plan, image, coder, done
from giga_agent.agents.landing_agent.prompts.ru import AGENT_PROMPT
from giga_agent.utils.messages import filter_tool_messages
from giga_agent.settings import settings


async def agent(state: LandingState, config: RunnableConfig):
    prompt = ChatPromptTemplate.from_messages(
        [("system", AGENT_PROMPT), MessagesPlaceholder("messages")]
    ).partial(language=settings.llm.giga_agent_lang)
    chain = prompt | llm.bind_tools(
        [plan, image, coder, done], parallel_tool_calls=False
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
        await asyncio.to_thread(Path("html").mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(write_to_file, "html/index.html", "w", state["html"])
        for name, value in state["images_base_64"].items():
            await asyncio.to_thread(
                write_to_file, f"html/{name}", "wb", base64.b64decode(value)
            )
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
        elif tools_calls[0]["name"] == "plan":
            return "plan_node"
        elif tools_calls[0]["name"] == "coder":
            return "coder"
        else:
            return "done_node"
    else:
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


coffee = "Разработать лендинг одностраничник для продажи кофе, ориентированного на любителей качественного кофе и тех, кто предпочитает удобство онлайн-покупок. Лендинг должен подчеркивать проблему отсутствия быстрого доступа к качественному кофе и сложности выбора среди множества предложений. Основное предложение — удобный интерфейс для легкого выбора идеального сорта и быстрая покупка высококачественной продукции."


@tool(parse_docstring=True)
async def create_landing(
    task: str,
    thread_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Создает веб-страницу/лендинг. В task передавай максимальное детальное задания с учетом предыдущих сообщений пользователя

    Args:
        task: Детальное описание веб-страницы, которую пользователь хочет сделать
        thread_id: Предыдущий thread_id. Используй, если пользователю, нужно продолжить работу над веб-страницей
    """
    client = get_client(url=settings.llm.langgraph_api_url)
    if not thread_id:
        thread_id = str(uuid.uuid4())
    result_state = {}
    action = state["messages"][-1].tool_calls[0]
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        if_not_exists="create",
        assistant_id="landing",
        input={
            "agent_messages": [
                {
                    "role": "user",
                    "content": task
                    + f"\nДополнительная информация: {state['messages'][-1].content}",
                }
            ],
            "task": task
            + f"\nДополнительная информация: {state['messages'][-1].content}",
            "html": "",
            "plan_messages": state["messages"][:]
            + [
                ToolMessage(
                    tool_call_id=action.get("id", str(uuid.uuid4())),
                    content=json.dumps(
                        {"message": "Приступаю к работе!"},
                        ensure_ascii=False,
                    ),
                )
            ],
        },
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
                            },
                        )
    code = result_state["html"]
    for name, value in result_state.get("images_base_64", {}).items():
        code = code.replace(name, f"data:image/jpeg;base64, {value}")
    file_id = str(uuid.uuid4())
    return {
        "text": result_state.get("done", "Страница готова"),
        "message": f'В результате выполнения была сгенерирована HTML страница {file_id}. Покажи её пользователю через "![HTML-страница](html:{file_id})" и напиши ответ с использованием информации из `text` и куда двигаться пользователю дальше\nТекущий thread_id: "{thread_id}" используй его, если пользователю нужно будет продолжить работу над страницей. Ни в коем случае не пиши thread_id пользователю — он нужен только для параметра thread_id!',
        "giga_attachments": [{"type": "text/html", "file_id": file_id, "data": code}],
        "thread_id": thread_id,
    }


async def main():
    async for event in graph.astream(
        {
            "task": coffee,
            "agent_messages": HumanMessage(content=coffee),
        },
        config={
            "configurable": {"thread_id": str(uuid.uuid4()), "print_messages": False}
        },
    ):
        print(event)
    # s = await app.ainvoke(
    #     {
    #         "task": coffee,
    #         "messages": HumanMessage(content=coffee),
    #     },
    #     config={
    #         "configurable": {"thread_id": str(uuid.uuid4()), "print_messages": True}
    #     },
    # )
    # with open("page.html", "w") as f:
    #     f.write(s["html"])


if __name__ == "__main__":
    asyncio.run(main())
