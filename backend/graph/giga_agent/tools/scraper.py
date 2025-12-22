import asyncio
from typing import Annotated

from langchain.tools import InjectedState
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_tavily import TavilyExtract

from giga_agent.utils.llm import is_llm_gigachat, load_llm
from giga_agent.utils.messages import filter_tool_calls

llm = load_llm(tag="fast").bind(top_p=0.3).with_config(tags=["nostream"])

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Ты — опытный копирайтер-аналитик.
Тебе предоставлены выгрузки с сайта (тексты, таблицы, изображения).

**Твоя задача:**

1. Проанализировать весь полученный материал.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать итоговый ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * прикрепляет важные изображения (с короткой подписью к каждой) `![alt-текст](ссылка)`.

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * изображения — обязательно в формате `![alt-текст](ссылка)`
""",
        ),
        MessagesPlaceholder("messages"),
    ],
)

scrape_sem = asyncio.Semaphore(4)


async def url_response_to_llm(messages, response):
    extract_ch = PROMPT | llm
    last_mes = filter_tool_calls(messages[-1])

    message = HumanMessage(
        content=f"""**Твоя задача:**

1. Проанализировать материал ниже.
2. Отобрать только то, что напрямую относится к поставленной задаче.
3. Сформировать исходя из материала короткий ответ для пользователя, который:

   * содержит релевантные фрагменты текста;
   * включает нужные таблицы (с сохранением структуры);
   * прикрепляет важные изображения (с короткой подписью к каждой) `![alt-текст](ссылка)`.

**Требования к результату:**

* Ничего лишнего: только данные, важные для решения задачи.
* Ясные, лаконичные формулировки, без воды.
* Если источник неясен — укажи пометку «(источник неизвестен)».
* Соблюдай единый стиль оформления:

  * заголовки — **полужирные**,
  * подзаголовки — *курсив*,
  * таблицы — в Markdown,
  * изображения — обязательно в формате ![alt-текст](ссылка)
  
Материал 
----
{response}
----
Дай краткую информацию исходя из материала следуя своей инструкции по форматированию ответа""",
    )
    async with scrape_sem:
        resp = await extract_ch.ainvoke(
            {"messages": messages[:-1] + [last_mes, message]},
        )
    return {
        "url": response["url"],
        "images": response["images"],
        "result": resp.content,
    }


@tool
async def get_urls(urls: list[str], state: Annotated[dict, InjectedState]):
    """Скачивает список URLs и отдает результат со страницы. Используй это когда тебе нужно узнать информацию по ссылке.
    Также это может возвращать изображения. Ты можешь их вставлять так ![alt](url)

    Args:
        urls: Список urls для скачивания

    """
    extract = TavilyExtract()

    response = await extract.ainvoke(
        {"urls": urls, "include_images": False, "extract_depth": "basic"},
    )
    if is_llm_gigachat():
        await llm._client.aget_token()
    tasks = []
    for result in response["results"]:
        tasks.append(url_response_to_llm(state["messages"], result))

    response = await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "results": response,
        "attention": "\nИспользуй результаты в своем ответе. Не забудь вставить изображения из результатов, которые ты посчитаешь были бы полезны пользователю! Следующим образом `![alt-текст](ссылка)`",
    }
