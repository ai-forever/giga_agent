import asyncio

import httpx
from langchain_core.tools import tool
from pydantic import Field

from giga_agent.settings import settings


@tool
async def vk_get_posts(
    domain: str = Field(description="Короткий адрес пользователя или сообщества."),
    offset: int = Field(
        description="Смещение, необходимое для выборки определённого подмножества записей.",
    ),
    count: int = Field(
        description="Количество записей, которое необходимо получить. Максимальное значение: 100.",
    ),
):
    """Получает посты со стены в ВК. Учитывай, что ты можешь получить лишь 100 постов за раз.
    Если нужно получить больше вызови функцию несколько раз или вызови её в цикле через python
    Помни, что тебе сразу выдается список объектов VK Posts! Без items
    Args:
        domain: Короткий адрес пользователя или сообщества.
        offset: Смещение, необходимое для выборки определённого подмножества записей.
        count: Количество записей, которое необходимо получить. Максимальное значение: 100.
    """
    url = "https://api.vk.com/method/wall.get"
    data = {
        "domain": domain,
        "offset": offset,
        "count": count,
        "access_token": settings.external.vk_token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            return response_json
        posts = response.json()["response"]["items"]
        for post in posts:
            post.pop("attachments", None)
        await asyncio.sleep(0.3)
        return posts


@tool
async def vk_get_comments(
    owner_id: str = Field(
        description="Идентификатор владельца страницы (пользователь или сообщество). Обратите внимание, идентификатор сообщества в параметре owner_id необходимо указывать со знаком «-»",
    ),
    post_id: int = Field(description="Идентификатор записи на стене."),
    offset: int = Field(
        description="Сдвиг, необходимый для получения конкретной выборки результатов.",
    ),
    count: int = Field(
        description="Число комментариев, которые необходимо получить. По умолчанию: 10, максимальное значение: 100.",
    ),
):
    """Получает комментарии к посту в ВК. Помни что тебе возвращается сразу список объектов VK Comments!"""
    url = "https://api.vk.com/method/wall.getComments"
    data = {
        "owner_id": owner_id,
        "post_id": post_id,
        "offset": offset,
        "count": count,
        "access_token": settings.external.vk_token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            return response_json
        posts = response.json()["response"]["items"]
        for post in posts:
            post.pop("attachments", None)
        await asyncio.sleep(0.3)
        return posts


class VKException(Exception):
    pass


async def get_page_id(domain: str):
    url = "https://api.vk.com/method/utils.resolveScreenName"
    data = {
        "screen_name": domain,
        "access_token": settings.external.vk_token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            raise VKException(response_json)
        if not response_json["response"]:
            raise VKException("Group not found")
        page_info = response.json()["response"]
        if page_info["type"] == "user":
            return page_info["object_id"]
        if page_info["type"] == "community_application":
            return page_info["group_id"]
        return -page_info["object_id"]


@tool(parse_docstring=True)
async def vk_get_last_comments(domain: str, count: int | None = None):
    """Получает комментарии с последних постов в ВК

    Args:
        domain: Короткий адрес пользователя или сообщества.
        count: Число комментариев, которые необходимо получить.

    """
    if count is None:
        count = 300
    """Получает комментарии со стены в ВК"""
    if (
        domain.startswith("id")
        or domain.startswith("wall")
        or domain.startswith("group")
    ):
        owner_id = int(domain.replace("id", ""))
        if not domain.startswith("id"):
            owner_id = -owner_id
    else:
        owner_id = await get_page_id(domain)
    script = f"""
var posts = API.wall.get({{"count": 20, "domain": "{domain}"}});
var postIds = posts.items@.id;
var postComments = [];
var i = 0;
while (i < postIds.length) {{
    var comments = API.wall.getComments({{"owner_id": {owner_id}, "post_id": postIds[i], "count": 100}});
    postComments.push(comments.items);
    i = i + 1;
}}
return {{"comments": postComments, "ids": postIds}};
"""
    url = "https://api.vk.com/method/execute"
    data = {
        "code": script,
        "access_token": settings.external.vk_token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            raise VKException(response_json)
        all_comments = response_json["response"]["comments"]
        post_ids = response_json["response"]["ids"]

        iters_with_ids = [
            (iter(comments), post_id)
            for comments, post_id in zip(all_comments, post_ids)
        ]

        result = []
        total_comments = sum(len(lst) for lst in all_comments)
        max_n = min(count, total_comments)

        while len(result) < max_n:
            for it, post_id in iters_with_ids:
                try:
                    comment = next(it)
                    comment["post_id"] = post_id
                    comment.pop("attachments", None)
                    result.append(comment)
                    if len(result) == count:
                        break
                except StopIteration:
                    continue
        return result
