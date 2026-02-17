import json
import uuid

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig

from giga_agent.modules.subagents_legacy.agents.landing_agent.config import (
    LandingState,
    llm,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.prompts.ru import (
    PLANNER_PROMPT,
)
from giga_agent.utils.messages import filter_tool_messages


async def plan_node(state: LandingState, config: RunnableConfig):
    plan_messages = filter_tool_messages(state.get("plan_messages", []))
    new_message = HumanMessage(content=state["task"])
    additional_info = (
        state["agent_messages"][-1].tool_calls[0].get("args", {}).get("additional_info")
    )
    if additional_info:
        new_message.content += f"\nДополнительная информация: {additional_info}"

    new_message.content += (
        "\nПомни, что тебе нужно составить план веб-страницы! "
        "Точно следуй своим инструкциям по составлению плана!"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", PLANNER_PROMPT), MessagesPlaceholder("messages")],
    ).partial(language="ru")

    chain = (prompt | llm).with_retry()

    resp = await chain.ainvoke({"messages": plan_messages + [new_message]})
    if config["configurable"].get("print_messages", False):
        resp.pretty_print()
    action = state["agent_messages"][-1].tool_calls[0]
    return {
        "plan_messages": [new_message, resp],
        "plan": resp.content,
        "coder_plan_loaded": False,
        "image_plan_loaded": False,
        "agent_messages": ToolMessage(
            tool_call_id=action.get("id", str(uuid.uuid4())),
            content=json.dumps(
                {
                    "plan": resp.content,
                    "message": "Оцени текущий шаг! И реши какой будет следующим!!",
                },
                ensure_ascii=False,
            ),
        ),
    }
