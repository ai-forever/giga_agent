import asyncio
import json
import os
import re
import uuid

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.modules.subagents_legacy.agents.landing_agent.config import (
    LandingState,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.prompts.ru import (
    CODER_PROMPT,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.tools import done
from giga_agent.output_parsers.html_parser import HTMLParser
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)
from giga_agent.modules.subagents_legacy.uploads import upload_files_for_config_user

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", CODER_PROMPT),
        MessagesPlaceholder("messages"),
    ],
).partial(language="ru")

async def coder_node(state: LandingState, config: RunnableConfig):
    user = await get_current_user_from_config(config)
    llm = await resolve_user_llm(user)
    coder_chain = (
        prompt
        | llm.with_config(tags=["nostream"])
        | RunnableParallel({"message": RunnablePassthrough(), "html": HTMLParser()})
    ).with_retry()
    coder_messages = state.get("coder_messages", [])
    new_message = HumanMessage(content=state["task"])
    additional_info = (
        state["agent_messages"][-1].tool_calls[0].get("args", {}).get("additional_info")
    )
    if additional_info:
        new_message.content += f"\nДополнительная информация: {additional_info}"
    plan = state.get("plan", "")
    if not state["coder_plan_loaded"] and plan:
        new_message.content += "\nПлан веб-страницы\n" + plan

    image_lines = []
    for i in state["images"]:
        image_lines.append(
            f"""Изображение: '{i["name"]}'
Описание: '{i["description"]}'
Ширина: {i["width"]}px
Высота: {i["height"]}px""",
        )
    resp = await coder_chain.ainvoke(
        {
            "messages": coder_messages + [new_message],
            "images": "\n----\n".join(image_lines),
        },
    )
    if config["configurable"].get("print_messages", False):
        resp["message"].pretty_print()
    html = resp["html"]
    for image in state["images"]:
        html = html.replace(
            image["name"],
            f"/files/runs/{config['configurable']['thread_id']}/{image['name']}",
        )
    html_counter = ""
    if state.get("html"):
        prev_path = state["html"].get("sandbox_path")
        if prev_path:
            filename = os.path.basename(prev_path)
            match = re.match(r"^(?P<name>.+?)(?:_(?P<idx>\d+))?\.html$", filename)
            if match:
                idx = match.group("idx")
                next_idx = int(idx) + 1 if idx else 2
                html_counter = f"_{next_idx}"
    upload_resp = await upload_files_for_config_user(
        config,
        files=[
            {
                "file_name": f"{config['configurable']['thread_id']}/page{html_counter}.html",
                "file_type": "html",
                "content": html.encode("utf-8"),
            }
        ],
    )
    uploaded = upload_resp[0].model_dump(mode="json")
    action = state["agent_messages"][-1].tool_calls[0]
    return {
        "coder_messages": [new_message, resp["message"]],
        "agent_messages": ToolMessage(
            tool_call_id=action.get("id", str(uuid.uuid4())),
            content=json.dumps(
                {
                    "code": resp["html"],
                    "message": "Оцени текущий шаг! И реши какой будет следующим!!",
                },
                ensure_ascii=False,
            ),
            artifact=resp["html"],
        ),
        "html": uploaded,
        "coder_plan_loaded": True,
    }
