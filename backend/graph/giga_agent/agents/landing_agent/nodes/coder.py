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

from giga_agent.agents.landing_agent.config import LandingState, llm
from giga_agent.agents.landing_agent.prompts.ru import CODER_PROMPT
from giga_agent.agents.landing_agent.tools import done
from giga_agent.output_parsers.html_parser import HTMLParser
from giga_agent.utils.jupyter import REPLUploader, RunUploadFile
from giga_agent.utils.lang import LANG

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", CODER_PROMPT),
        MessagesPlaceholder("messages"),
    ],
).partial(language=LANG)

coder_chain = (
    prompt
    | llm
    | RunnableParallel({"message": RunnablePassthrough(), "html": HTMLParser()})
).with_retry()


async def coder_node(state: LandingState, config: RunnableConfig):
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
    uploader = REPLUploader()
    html_counter = ""
    if state.get("html"):
        prev_path = state["html"].get("path")
        if prev_path:
            filename = os.path.basename(prev_path)
            match = re.match(r"^(?P<name>.+?)(?:_(?P<idx>\d+))?\.html$", filename)
            if match:
                idx = match.group("idx")
                next_idx = int(idx) + 1 if idx else 2
                html_counter = f"_{next_idx}"
    upload_files = [
        RunUploadFile(
            path=f"page{html_counter}.html",
            file_type="html",
            content=html,
        ),
    ]
    upload_resp = await uploader.upload_run_files(
        upload_files,
        config["configurable"]["thread_id"],
    )
    uploaded = upload_resp[0]
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


async def main():
    images = [
        {
            "name": "happy-dog-in-shelter.jpg",
            "description": (
                "Веселый щенок лабрадора сидит у ног пожилой женщины-волонтёра, "
                "оба смотрят прямо в камеру. Просторная комната приюта с "
                "деревянным полом, солнечный свет льётся сквозь большие окна. "
                "Реалистичный снимок, тёплые пастельные цвета."
            ),
            "width": 1920,
            "height": 1080,
        },
        {
            "name": "shelter-facility-overview.jpg",
            "description": (
                "Вид сверху на территорию приюта с зелёными газонами, "
                "вольерами и прогулочными дорожками. Солнечная погода,"
                " голубое небо, яркая зелень деревьев. "
                "Аэрография высокого разрешения, контрастные цвета."
            ),
            "width": 1920,
            "height": 1080,
        },
        {
            "name": "volunteer-with-puppy.jpg",
            "description": (
                "Молодая девушка-доброволец нежно гладит маленького спаниеля, "
                "сидящего рядом. Оба расположены на траве возле вольера, "
                "вокруг другие животные играют и отдыхают. "
                "Естественный дневной свет, мягкие теплые тона."
            ),
            "width": 1280,
            "height": 720,
        },
        {
            "name": "adoption-success-story.jpg",
            "description": (
                "Счастливая семья стоит вместе со своей "
                "новой собакой породы хаски, все улыбаются и держат поводок. "
                "Семейный портрет на природе, осенние листья, "
                "мягкий рассеянный свет, теплая золотистая палитра."
            ),
            "width": 1280,
            "height": 720,
        },
        {
            "name": "donation-button-icon.jpg",
            "description": (
                "Иконка кнопки для пожертвований в виде лапы собаки "
                "с сердечком внутри. Минималистичный векторный рисунок, "
                "синий градиент фона, белый контур иконки."
            ),
            "width": 200,
            "height": 200,
        },
        {
            "name": "contact-form-bg.jpg",
            "description": (
                "Фоновый узор контактной формы с изображением "
                "лапок собак и листьев, повторяющийся паттерн. "
                "Пастельная цветовая гамма, нежные розово-зелёные оттенки, "
                "лёгкость восприятия."
            ),
            "width": 1920,
            "height": 1080,
        },
        {
            "name": "news-event-thumbnail.jpg",
            "description": (
                "Фотография группы людей, участвующих в мероприятии по "
                "сбору средств для приюта. Все одеты в футболки с символикой приюта, "
                "радостно общаются между собой. "
                "Дневной свет, живые эмоции, динамичность композиции."
            ),
            "width": 1024,
            "height": 576,
        },
    ]
    mess = [
        (
            "user",
            (
                "Создай презентацию с помощью reveal.js на 4 слайда. "
                "На первом слайде будет представление продукта, "
                "на втором слайде краткая история нашей компании, "
                "на третьем сравнение нас с конкурентами на последнем слайде контакты. "
                "Данные придумай сам. Компания и продукт называются МЕГАКИРПИЧ. "
                "Обязательно учитывай, что изображения которые ты используешь "
                "должны легко читаться на тексте. "
                "Их можно либо размыть либо добавить цветой фильтр на них, "
                "который будет контрастировать с цветом текста"
            ),
        ),
    ]
    image_lines = []
    for i in images:
        image_lines.append(
            f"""Изображение: '{i["name"]}'
    Описание: '{i["description"]}'
    Ширина: {i["width"]}px
    Высота: {i["height"]}px""",
        )
    ch = prompt | llm.bind_tools([done])
    (
        await ch.ainvoke(
            {
                "messages": mess[:],
                "images": "\n----\n".join(image_lines),
            },
        )
    ).pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
