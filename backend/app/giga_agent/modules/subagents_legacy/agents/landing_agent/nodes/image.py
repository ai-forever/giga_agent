import asyncio
import base64
import json
import uuid

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.modules.subagents_legacy.agents.landing_agent.config import (
    LandingState,
    llm,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.prompts.ru import (
    IMAGE_PROMPT,
)
from giga_agent.generators.image import load_image_gen
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile


async def image_node(state: LandingState, config: RunnableConfig):
    image_messages = state.get("image_messages", [])
    new_message = HumanMessage(content=state["task"])
    additional_info = (
        state["agent_messages"][-1].tool_calls[0].get("args", {}).get("additional_info")
    )
    if additional_info:
        new_message.content += f"\nДополнительная информация: {additional_info}"
    plan = state.get("plan", "")
    if not state["image_plan_loaded"] and plan:
        new_message.content += "\nПлан веб-страницы\n" + plan

    prompt = ChatPromptTemplate.from_messages(
        [("system", IMAGE_PROMPT), MessagesPlaceholder("messages")],
    ).partial(language="ru")

    chain = (
        prompt
        | llm
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()},
        )
    ).with_retry()
    full_images = []
    new_message.content += (
        "\nПомни, что тебе нужно вернуть JSON с изображениями! "
        "Обязательно следуй формату ответа согласно инструкции!\n"
    )
    full_messages = [new_message]
    n_count = 2
    if image_messages:
        n_count = 1
    else:
        full_messages[-1].content += "\nСделай минимум 8 изображений!\n"
    for i in range(n_count):
        resp = await chain.ainvoke({"messages": image_messages + full_messages})
        if config["configurable"].get("print_messages", False):
            resp["message"].pretty_print()
        images = resp["json"].get("images", [])
        full_messages += [
            resp["message"],
            HumanMessage(
                content=(
                    "Придумай новый список изображений! Названия не должны повторяться"
                ),
            ),
        ]
        full_images += images
        if len(full_images) >= 7:
            break
    full_images = full_images[:]
    filtered_images = []
    existing_names = [i["name"] for i in state.get("images", [])]
    for image in full_images[:7]:
        if not image.get("width") or not image.get("height"):
            continue
        image["width"] = max(image["width"], 200)
        image["height"] = max(image["height"], 200)
        image_name = image.get("name", "")
        image_name_parts = image_name.split(".")
        if len(image_name_parts) > 1:
            image["name"] = ".".join(image_name_parts[:-1]) + ".jpg"
        else:
            image["name"] = image_name_parts[0] + ".jpg"
        if image["name"] in existing_names:
            continue
        existing_names.append(image["name"])
        # image["name"] = str(uuid.uuid4()) + ".jpg"
        filtered_images.append(image)
    generator = load_image_gen()
    await generator.init()
    tasks = [
        generator.generate_image(i["description"], i["width"], i["height"])
        for i in filtered_images
    ]
    images_data = await asyncio.gather(*tasks, return_exceptions=True)
    images_data_filtered = [
        (i, d) for i, d in zip(filtered_images, images_data) if isinstance(d, str)
    ]

    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path=i["name"],
            file_type="image",
            content=base64.b64decode(image),
        )
        for i, image in images_data_filtered
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files,
        config["configurable"]["thread_id"],
    )

    images_uploaded = state.get("images_uploaded", {})
    new_images = []
    for i, b in zip(images_data_filtered, upload_resp):
        if isinstance(b, Exception):
            continue
        images_uploaded[i[0]["name"]] = b
        new_images.append(i[0])
    action = state["agent_messages"][-1].tool_calls[0]
    return {
        "image_messages": full_messages[:-1],
        "images": new_images,
        "agent_messages": ToolMessage(
            tool_call_id=action.get("id", str(uuid.uuid4())),
            content=json.dumps(
                {
                    "images": filtered_images,
                    "message": "Оцени текущий шаг! И реши какой будет следующим!!",
                },
                ensure_ascii=False,
            ),
        ),
        "images_uploaded": images_uploaded,
        "image_plan_loaded": True,
    }


if __name__ == "__main__":
    prompt = ChatPromptTemplate.from_messages(
        [("system", IMAGE_PROMPT), MessagesPlaceholder("messages")],
    )

    chain = (
        prompt
        | llm.bind(top_p=0.9)
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()},
        )
    ).with_retry()

    chain.invoke(
        {
            "messages": [
                (
                    "user",
                    (
                        "Придумай промпт для мема в конце презентации про "
                        "недвижимость в москве. без котов + минимум текста"
                    ),
                ),
            ],
        },
    )["message"].pretty_print()
