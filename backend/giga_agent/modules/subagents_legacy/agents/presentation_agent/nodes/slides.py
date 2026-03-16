import asyncio
import os
import re

from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.core.db import get_session_factory
from giga_agent.modules.subagents_legacy.agents.presentation_agent.config import (
    PresentationState,
)
from giga_agent.modules.subagents_legacy.agents.presentation_agent.prompts.ru import (
    SLIDE_PROMPT,
)
from giga_agent.output_parsers.html_parser import HTMLParser
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)
from giga_agent.modules.subagents_legacy.uploads import (
    build_file_content_by_path_url,
    upload_files_for_config_user,
    build_file_content_by_path_api,
)

slide_sem = asyncio.Semaphore(4)

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

with open(os.path.join(__location__, "presentation.html")) as f:
    presentation_html = f.read()


async def _generate_slide(messages, llm):
    async with slide_sem:
        ch_2 = (
            SLIDE_PROMPT
            | llm
            | RunnableParallel(
                {"message": RunnablePassthrough(), "html": HTMLParser(tag="section")}
            )
        ).with_retry()
        slide_resp = await ch_2.ainvoke({"messages": messages})
        html = slide_resp.get("html", "")
        reg = r",\s*"
        html = re.sub(
            r'data-background-gradient="linear-gradient\(([^)]*)\)"',
            lambda m: f"data-background-gradient="
            f'"linear-gradient({re.sub(reg, ", ", m.group(1))})"',
            html,
        )
        return html


async def slides_node(state: PresentationState, config: RunnableConfig):
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        llm = await resolve_user_llm(user, session=session)
    llm = llm.with_config(tags=["nostream"]).bind(top_p=0.2)
    slide_tasks = []
    for idx, slide in enumerate(state["slides"]):
        user_message = (
            f"Придумай {idx + 1} слайд '{slide.get('name')}'. "
            f"Используй строго тот градиент, который указан в самом недавнем "
            f"плане презентации! Всегда используй градиент типа 'to bottom'"
        )
        if (idx + 1) in state["slide_map"]:
            images = state["slide_map"][(idx + 1)]
            for image in images:
                user_message += (
                    f"\nУ тебя доступно изображение '{image.get('name')}' — "
                    f"'{image.get('description')}'. "
                    f"Помни, что это изображение не для фона! "
                    f"Используй его как контент. "
                    f"Помни про то, что нужен class='img' в теге img!"
                )
        if slide.get("attachments", []):
            for graph in slide.get("attachments", []):
                if not isinstance(graph, str):
                    continue
                if graph.startswith("attachment:"):
                    user_message += f"\nИспользуй график: '{graph}'"
                elif graph.startswith("/runs/") or graph.startswith("/files/"):
                    user_message += f"\nИспользуй график: 'attachment:{graph}'"
        slide_tasks.append(
            _generate_slide(state["messages"] + [("user", user_message)], llm)
        )
    slide_resps = await asyncio.gather(*slide_tasks)
    result = presentation_html.replace("<SECTIONS></SECTIONS>", "\n".join(slide_resps))
    result = result.replace("<|API_URL|>", build_file_content_by_path_api())
    for key, value in state["images_uploaded"].items():
        image_url = build_file_content_by_path_url(value["sandbox_path"])
        result_2 = result.replace(
            f"attachment:{key}",
            image_url,
        )
        if result == result_2:
            result = result.replace(f"{key}", image_url)
        else:
            result = result_2
    upload_resp = await upload_files_for_config_user(
        config,
        files=[
            {
                "file_name": f"{config['configurable']['thread_id']}/presentation.html",
                "file_type": "html",
                "content": result.encode("utf-8"),
            }
        ],
    )
    return {"presentation_html": upload_resp[0].model_dump(mode="json")}
