import asyncio
import os
import re

from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.agents.presentation_agent.config import PresentationState, llm
from giga_agent.agents.presentation_agent.prompts.ru import SLIDE_PROMPT
from giga_agent.output_parsers.html_parser import HTMLParser
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile

slide_sem = asyncio.Semaphore(4)

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

with open(os.path.join(__location__, "presentation.html")) as f:
    presentation_html = f.read()


async def generate_slide(messages):
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
        slide_tasks.append(generate_slide(state["messages"] + [("user", user_message)]))
    slide_resps = await asyncio.gather(*slide_tasks)
    result = presentation_html.replace("<SECTIONS></SECTIONS>", "\n".join(slide_resps))
    for key, value in state["images_uploaded"].items():
        result_2 = result.replace(f"attachment:{key}", f"/files{value['path']}")
        if result == result_2:
            result = result.replace(f"{key}", f"/files{value['path']}")
        else:
            result = result_2
    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path="presentation.html",
            file_type="html",
            content=result,
        ),
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files,
        config["configurable"]["thread_id"],
    )
    return {"presentation_html": upload_resp[0]}
