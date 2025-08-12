import asyncio
import json
import os
import uuid
from typing import Annotated

from langchain_core.tools import tool
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState
from langgraph_sdk import get_client

from giga_agent.agents.presentation_agent.config import PresentationState, ConfigSchema
from giga_agent.agents.presentation_agent.nodes.images import image_node
from giga_agent.agents.presentation_agent.nodes.plan import plan_node
from giga_agent.agents.presentation_agent.nodes.slides import slides_node
from giga_agent.utils.env import load_project_env

workflow = StateGraph(PresentationState, ConfigSchema)

workflow.add_node("plan_node", plan_node)
workflow.add_node("image", image_node)
workflow.add_node("slides_node", slides_node)

workflow.add_edge(START, "plan_node")
workflow.add_edge("plan_node", "image")
workflow.add_edge("image", "slides_node")
workflow.add_edge("slides_node", END)

graph = workflow.compile()


@tool(parse_docstring=True)
async def generate_presentation(
    presentation_task: str,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Этот инструмент создает презентации. В task передай задачу для создания презентации.

    Args:
        presentation_task: Описание презентации
    """
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {
            "agent": "generate_presentation",
            "node": "__start__",
        },
    )
    last_mes = state["messages"][-1].model_copy()
    last_mes.tool_calls = None
    last_mes.additional_kwargs["function_call"] = None
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="presentation",
        input={
            "messages": state["messages"][:-1] + [last_mes],
            "task": presentation_task,
        },
        stream_mode=["values", "updates"],
        on_disconnect="cancel",
    ):
        if chunk.event == "values":
            state = chunk.data
        elif chunk.event == "updates":
            push_ui_message(
                "agent_execution",
                {
                    "agent": "generate_presentation",
                    "node": list(chunk.data.keys())[0],
                },
            )
    code = state["presentation_html"]
    for name, value in state.get("images_base_64", {}).items():
        code = code.replace(name, f"data:image/jpeg;base64, {value}")
    file_id = str(uuid.uuid4())
    return {
        "message": f'В результате выполнения была сгенерирована HTML страница {file_id}. Покажи её пользователю через "![HTML-страница](html:{file_id})" и напиши куда двигаться пользователю дальше',
        "giga_attachments": [{"type": "text/html", "file_id": file_id, "data": code}],
    }


async def main():
    load_project_env()
    messages = json.load(open("data/messages.json", "r"))
    async for event in graph.astream(
        {"messages": messages},
        config={
            "configurable": {
                "thread_id": str(uuid.uuid4()),
                "print_messages": True,
                "save_files": True,
            }
        },
    ):
        pass
    key = list(event.keys())[0]
    with open("page.html", "w") as f:
        f.write(event[key]["presentation_html"])


if __name__ == "__main__":
    asyncio.run(main())
