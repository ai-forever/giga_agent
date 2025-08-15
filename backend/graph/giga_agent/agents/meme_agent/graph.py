import asyncio
import base64
import os
import uuid
from typing import Annotated

from langchain_core.tools import tool
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.prebuilt import InjectedState
from langgraph_sdk import get_client

from giga_agent.agents.meme_agent.config import MemeState, ConfigSchema
from giga_agent.agents.meme_agent.nodes.images import image_node
from giga_agent.agents.meme_agent.nodes.text import text_node
from giga_agent.utils.llm import is_llm_image_inline
from giga_agent.utils.env import load_project_env
from giga_agent.utils.messages import filter_tool_calls

load_project_env()

workflow = StateGraph(MemeState, ConfigSchema)

workflow.add_node("text", text_node)
workflow.add_node("image", image_node)

workflow.add_edge(START, "text")
workflow.add_edge("text", "image")
workflow.add_edge("image", END)

graph = workflow.compile()


@tool
async def create_meme(
    task: str,
    state: Annotated[dict, InjectedState] = None,
):
    """
    Создает мем. Если пользователю нужно создать мем, вызывай этот инструмент

    Args:
        task: Описание мема
    """
    from giga_agent.config import llm

    last_mes = filter_tool_calls(state["messages"][-1])
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {"agent": "create_meme", "node": "__start__"},
    )
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="meme",
        input={
            "task": task,
            "messages": state["messages"][:-1]
            + [
                last_mes,
                (
                    "user",
                    task
                    + "\nПомни, что тебе нужно сгенерировать идею для мема. Отвечай в формате JSON согласно инструкции.",
                ),
            ],
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
                    "agent": "create_meme",
                    "node": list(chunk.data.keys())[0],
                },
            )
    if is_llm_image_inline():
        uploaded_file_id = (
            await llm.aupload_file(("image.png", base64.b64decode(state["meme_image"])))
        ).id_
    else:
        uploaded_file_id = str(uuid.uuid4())
    return {
        "meme_text": state["meme_idea"],
        "message": f'В результате выполнения было сгенерировано изображение {uploaded_file_id}. Покажи его пользователю через "![мем](graph:{uploaded_file_id})" и напиши куда двигаться пользователю дальше',
        "giga_attachments": [
            {
                "type": "image/png",
                "file_id": uploaded_file_id,
                "data": state["meme_image"],
            }
        ],
    }


async def main():
    conf = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            "print_messages": True,
        }
    }
    async for event in graph.astream(
        {
            "messages": [
                ("user", "Когда положили прод и тебе надо в ночь делать план б")
            ]
        },
        config=conf,
    ):
        pass
    state = graph.get_state(config=conf).values
    with open("im.jpeg", "wb") as f:
        f.write(base64.b64decode(state["meme_image"]))


if __name__ == "__main__":
    asyncio.run(main())
