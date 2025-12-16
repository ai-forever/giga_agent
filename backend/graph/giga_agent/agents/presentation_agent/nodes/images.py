import asyncio
import base64
import re

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.agents.presentation_agent.config import PresentationState, llm
from giga_agent.agents.presentation_agent.prompts.ru import IMAGE_PROMPT
from giga_agent.generators.image import load_image_gen
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile


async def image_node(state: PresentationState, config: RunnableConfig):
    slides_for_images = []
    uuid_pattern = (
        "^[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    for idx, slide in enumerate(state["slides"]):
        if not slide.get("attachments"):
            slides_for_images.append(f"{idx + 1}. {slide.get('name')}")
        else:
            graph_not_valid = True
            for graph in slide["attachments"]:
                if (graph.startswith("attachment:") and graph_not_valid) or re.match(
                    uuid_pattern,
                    graph,
                ):
                    graph_not_valid = False
                    break
            if graph_not_valid:
                slides_for_images.append(f"{idx + 1}. {slide.get('name')}")
    slides_text = "\n".join(slides_for_images)
    img_chain = (
        IMAGE_PROMPT
        | llm
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()},
        )
    ).with_retry()
    image_message = (
        f"Придумай список изображений для следующих слайдов: {slides_text}. "
        f"Ты можешь придумывать не для каждого слайда изображения, "
        f"а только там где считаешь нужным. "
        f"Помни, что графики мы будем брать исходя из переписки с пользователем выше!"
        f" Тебе нужно сгенерировать описание изображения для: "
        f"предметов, интерьеров, ландшафтов, людей и т.д. все, "
        f"что может относится к презентации! Инфографика не нужна! "
        f"Изображения нужны только в тех слайдах где нет инфографики!",
    )
    img_resp = await img_chain.ainvoke(
        {
            "messages": state["messages"][-2:]
            + [
                ("user", image_message),
            ],
        },
    )
    images = img_resp["json"]["images"]
    if config["configurable"].get("print_messages", False):
        img_resp["message"].pretty_print()
    generator = load_image_gen()
    await generator.init()
    tasks = [
        generator.generate_image(i["description"], i["width"], i["height"])
        for i in images
    ]
    images_data = await asyncio.gather(*tasks, return_exceptions=True)
    images_data_filtered = [
        (i, d) for i, d in zip(images, images_data) if isinstance(d, str)
    ]
    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path=i[0]["name"],
            file_type="image",
            content=base64.b64decode(i[1]),
        )
        for i in images_data_filtered
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files,
        config["configurable"]["thread_id"],
    )
    slide_map = {}
    images_uploaded = state.get("images_uploaded", {})
    for i, b in zip(images_data_filtered, upload_resp):
        if isinstance(b, Exception):
            continue
        slide_map.setdefault(i[0]["slide_index"], []).append(i[0])
        images_uploaded[i[0]["name"]] = b
        if config["configurable"].get("save_files", False):
            raise Exception("TODO: переделать")
            # with open(i["name"], "wb") as f:
            #     await asyncio.to_thread(f.write, base64.b64decode(b))
    return {"slide_map": slide_map, "images_uploaded": images_uploaded}
