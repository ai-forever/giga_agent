import asyncio
import base64
import uuid

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph_sdk import get_client

from giga_agent.modules.subagents_legacy.agents.meme_agent.config import (
    ConfigSchema,
    MemeState,
)
from giga_agent.modules.subagents_legacy.agents.meme_agent.nodes.images import (
    image_node,
)
from giga_agent.modules.subagents_legacy.agents.meme_agent.nodes.text import text_node
from giga_agent.utils.messages import filter_tool_calls

workflow = StateGraph(MemeState, ConfigSchema)

workflow.add_node("text", text_node)
workflow.add_node("image", image_node)

workflow.add_edge(START, "text")
workflow.add_edge("text", "image")
workflow.add_edge("image", END)

graph = workflow.compile()


@tool
async def create_meme(task: str, runtime: ToolRuntime):
    """Создает мем. Если пользователю нужно создать мем, вызывай этот инструмент

    Args:
        task: Описание мема

    """
    from giga_agent.settings import settings

    last_mes = filter_tool_calls(runtime.state["messages"][-1])
    client = get_client()
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {
            "agent": "create_meme",
            "node": "__start__",
            "tool_call_id": runtime.tool_call_id,
        },
    )
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="meme",
        input={
            "task": task,
            "messages": runtime.state["messages"][:-1]
            + [
                last_mes,
                (
                    "user",
                    task + "\nПомни, что тебе нужно сгенерировать идею для мема. "
                    "Отвечай в формате JSON согласно инструкции.",
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
                    "tool_call_id": runtime.tool_call_id,
                },
            )
    return {
        "meme_text": state["meme_idea"],
        "message": (
            f"В результате выполнения было сгенерировано изображение "
            f"{state['meme_image']['path']}. "
            f"Покажи его пользователю через "
            f'"![alt-описание](attachment:{state["meme_image"]["path"]})" '
            f"и напиши куда двигаться пользователю дальше"
        ),
        "giga_attachments": [state["meme_image"]],
    }


async def main():
    conf = {
        "configurable": {
            "thread_id": str(uuid.uuid4()),
            "print_messages": True,
        },
    }
    async for event in graph.astream(
        {
            "messages": [
                ("user", "Когда положили прод и тебе надо в ночь делать план б"),
            ],
        },
        config=conf,
    ):
        pass
    state = graph.get_state(config=conf).values
    with open("im.jpeg", "wb") as f:
        f.write(base64.b64decode(state["meme_image"]))


if __name__ == "__main__":
    asyncio.run(main())
