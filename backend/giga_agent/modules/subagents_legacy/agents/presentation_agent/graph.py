import asyncio
import json
import uuid

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.models.file import FileResponse
from giga_agent.modules.subagents_legacy.agents.presentation_agent.config import (
    ConfigSchema,
    PresentationState,
)
from giga_agent.modules.subagents_legacy.agents.presentation_agent.nodes.images import (
    image_node,
)
from giga_agent.modules.subagents_legacy.agents.presentation_agent.nodes.plan import (
    plan_node,
)
from giga_agent.modules.subagents_legacy.agents.presentation_agent.nodes.slides import (
    slides_node,
)
from giga_agent.modules.subagents_legacy.runtime import with_auth_from_runtime
from giga_agent.modules.subagents_legacy.uploads import build_tool_message
from giga_agent.utils.langgraph_sdk import get_client
from giga_agent.utils.messages import filter_tool_calls

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
    runtime: ToolRuntime,
):
    """Этот инструмент создает презентации.
    В task передай задачу для создания презентации.
    Если ты хочешь передать график/изображение в task,
    то передавай их в формате `attachment:<путь до вложения>`

    Args:
        presentation_task: Описание презентации

    """
    client = get_client(runtime.config)
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {
            "agent": "generate_presentation",
            "node": "__start__",
            "tool_call_id": runtime.tool_call_id,
        },
    )
    last_mes = filter_tool_calls(runtime.state["messages"][-1])
    state = {}
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="presentation",
        input={
            "messages": runtime.state["messages"][:-1] + [last_mes],
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
                    "tool_call_id": runtime.tool_call_id,
                },
            )
    code = FileResponse.model_validate(state["presentation_html"])
    return build_tool_message(
        runtime,
        tool_name="generate_presentation",
        payload={
            "message": (
                f"В результате выполнения была сгенерирована HTML страница "
                f"{code.sandbox_path}. Покажи её пользователю через "
                f'"![alt-описание](attachment:{code.sandbox_path})" '
                f"и напиши куда двигаться пользователю дальше"
            )
        },
        attachments=[code],
    )


async def main():
    messages = json.load(open("data/messages.json"))
    async for event in graph.astream(
        {"messages": messages},
        config={
            "configurable": {
                "thread_id": str(uuid.uuid4()),
                "print_messages": True,
                "save_files": True,
            },
        },
    ):
        pass
    key = list(event.keys())[0]
    with open("page.html", "w") as f:
        f.write(event[key]["presentation_html"])


if __name__ == "__main__":
    asyncio.run(main())
