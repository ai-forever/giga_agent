import base64
import uuid
from typing import List, Annotated

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
)
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import InjectedState
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from pydantic import Field

from giga_agent.settings import settings

from langgraph_sdk import get_client

from giga_agent.utils.llm import is_llm_image_inline, load_llm
from giga_agent.generators.image import load_image_gen
from giga_agent.prompts.image import IMAGE_PROMPT


@tool
async def ask_followup_question(
    question: str = Field(description="Дополнительные вопросы пользователю"),
):
    """Используй это, если тебе не хватает какой-либо информации для выполнения задачи пользователя."""
    pass


@tool
async def search(queries: List[str] = Field(description="Поисковые запросы")):
    """Запрос в поисковую систему. Используй для получения новых фактов, о которых ты не знаешь.
    Этот инструмент выдает только короткие факты и ссылки откуда взята эта информация.
    Не забывай что можешь запросить информацию у пользователя с помощью `ask_followup_question`.
    Обязательно разбивай сложные запросы на более легкие.
    При формировании ответа обязательно прикладывай полные ссылки на источники, которые ты получил из инструмента `search`
    """
    search = TavilySearch(tavily_api_key=settings.external.tavily_api_key)

    return await search.abatch(
        [
            {
                "query": query.strip(),
            }
            for query in queries
        ]
    )


@tool
async def suggest_plan(query: str, state: Annotated[dict, InjectedState]):
    """Придумывает план для выполнения задачи пользователя. Используй при первом запросе пользователя, когда у тебя нет плана или его нужно пересоздать

    Args:
        query: Задача пользователя
    """
    llm = load_llm().with_config(tags=["nostream"])

    return (
        await llm.ainvoke(
            [
                (
                    "system",
                    f"""Ты — GigaAssistant, высококвалифицированный инженер-программист с обширными знаниями в программировании на Python, фреймворков.

====

РАЗМЫШЛЕНИЯ (thinking)
Ты должен всегда размышлять над задачей пользователя и ответами инструментов. Также ты должен стараться смотреть на задачу пользователя с разных точек зрения.
Обязательно детальной прописывай в каждом сообщение свои размышления. Также проверяй результаты выполнения инструментов и рефлексируй их результаты.
Для этого используй XML тэг <thinking>. В этом теге ты должен записывать свои размышления и планирование как ты будешь решать задачу пользователя.

Перед тем как предпринимать какие‑либо действия или отвечать пользователю после получения результатов работы инструментов, используй тэг <thinking> как черновик, чтобы:
- перечислить конкретные правила, которые относятся к текущему запросу;
- проверить, собрана ли вся необходимая информация;
- убедиться, что запланированное действие соответствует всем политикам;
- перебрать результаты работы инструментов и убедиться в их корректности.

====

КОД (python)
Помни, что при работе с кодом, ты должен стараться работать по шагам. Допустим сначала узнать какие есть колонки в таблице перед работой с ней. 
Также помни, что все переменные между вызовами сохраняются, так как код выполняется в Jupyter среде.
Не формулируй выводы в коде! Если ты уже закончил работу с данными, тогда либо пиши это сообщением, либо используй другие инструменты

===

СИНТЕЗ РЕЧИ (speak)
Если ты хочешь использовать синтез речи, формулируй его простым языком. Используй обращение во 2 лице (на ты). 
Обязательно используй простой пацанский жаргон!!! Или заказчик не поймет

===

ПОИСК (search)
Всегда разделяй сложные запросы на легкие и используй поиск итеративно.
Допустим если тебя просят найти перечисления объектов, то сделай по отдельному запросу на каждый объект.
Но если же тебя просят найти объекты вместе, тогда разделения на несколько запросов не должно происходить.
Если тебя просят найти информацию за период дат, помни, что ты также можешь разбить сложный запрос на несколько простых

====

АНАЛИЗ ИЗОБРАЖЕНИЙ (ask_about_image)
В результате выполнения кода, тебе могут возвращаться изображения. Если тебе нужно узнать информацию по ним используй инструмент ask_about_image с детальным вопросом по изображению, который нужно задать, чтобы выполнить задачу пользователя.
Используй при анализе только те id или ссылки, которые у тебя есть. Ни в коем случае не придумывай их!!!

====

ПАМЯТЬ
Если пользователь сказал какие-либо факты о себе или ты узнал что-то новое, запиши это в своей памяти. Также используй её чтобы подтягивать эти данные

====

Думай как scrum мастер.
У тебя стоит задача придумать самый оптимальный план для выполнения задачи исходя из тех инструментов, которые у тебя есть.
У тебя из инструментов есть: КОД, СИНТЕЗ РЕЧИ, ПОИСК, АНАЛИЗ ИЗОБРАЖЕНИЙ, ПАМЯТЬ
Обязательно при продумывании плана опирайся на правила каждого из инструментов.
Ты должен вернуть только нумерированный план, который оптимально решит задачу пользователя.
Задача пользователя: "{query}"
Придумай только план!
Нумерированный План: """,
                )
            ]
        )
    ).content


# @tool(parse_docstring=True)
@tool
async def ask_about_image(
    image_id: str,
    question: str,
    state: Annotated[dict, InjectedState],
):
    """Анализирует изображение. Используй если нужно узнать информацию по изображению
    Используй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!

    Args:
        image_id: ID изображения
        question: Запрос для анализа изображения. Детально пропиши все, что ты хочешь узнать от изображения. Это полноценный промпт к V-LLM, поэтому используй все мощности нейросетей!
    """
    llm = load_llm().with_config(tags=["nostream"])

    if image_id.startswith("graph:"):
        image_id = image_id[len("graph:") :]
    if image_id not in state["file_ids"]:
        return f"Изображение c ID {image_id} не найдено"
    if is_llm_image_inline():
        return (
            (
                await llm.ainvoke(
                    [
                        HumanMessage(
                            content=question,
                            additional_kwargs={"attachments": [image_id]},
                        ),
                    ]
                )
            ).content
            + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
        )
    else:
        client = get_client()
        result = await client.store.get_item(("attachments",), key=image_id)
        data = (
            result["value"]["img_data"]
            if "img_data" in result["value"]
            else result["value"]["data"]
        )
        return (
            (
                await llm.ainvoke(
                    [
                        HumanMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": question,
                                },
                                {
                                    "type": "image",
                                    "source_type": "base64",
                                    "data": data,
                                    "mime_type": "image/png",
                                },
                            ]
                        ),
                    ]
                )
            ).content
            + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
        )


@tool
async def gen_image(theme: str):
    """
    Генерирует изображение

    Args:
        theme: Тема для генерации изображения
    """
    llm = load_llm().with_config(tags=["nostream"])

    img_chain = (
        IMAGE_PROMPT
        | llm
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()}
        )
    ).with_retry()
    generator = load_image_gen()
    await generator.init()
    response = await img_chain.ainvoke(
        {"messages": [("user", f'Тема изображения: "{theme}". Улучши её')]}
    )
    i = response["json"]["image"]
    image_data = await generator.generate_image(
        i["description"], i["width"], i["height"]
    )
    if is_llm_image_inline():
        uploaded_file_id = (
            await llm.aupload_file(("image.png", base64.b64decode(image_data)))
        ).id_
    else:
        uploaded_file_id = str(uuid.uuid4())
    return {
        "image_description": i["description"],
        "message": f'В результате выполнения было сгенерировано изображение {uploaded_file_id}. Покажи его пользователю через "![описание изображения](graph:{uploaded_file_id})"',
        "giga_attachments": [
            {
                "type": "image/png",
                "file_id": uploaded_file_id,
                "data": image_data,
            }
        ],
    }


@tool(parse_docstring=True)
def Think(thought: str) -> str:
    """
    Используется для рассуждений

    Args:
        thought: Короткое рассуждение
    """
    return f"thought='{thought}'"
