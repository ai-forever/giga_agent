from __future__ import annotations

import asyncio
import uuid

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import Field

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

VK_SECRET_KEY = "VK_TOKEN"


class VKException(Exception):
    pass


def _get_user_secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


async def _get_current_user(runtime: ToolRuntime) -> UserShort:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {owner_id} не найден")
    return user


async def _get_vk_token(runtime: ToolRuntime) -> str:
    user = await _get_current_user(runtime)
    token = _get_user_secret(user, VK_SECRET_KEY)
    if token is None:
        raise ValueError(f"Missing required user secret: {VK_SECRET_KEY}")
    return token


@tool
async def vk_get_posts(
    runtime: ToolRuntime,
    domain: str = Field(description="Короткий адрес пользователя или сообщества."),
    offset: int = Field(
        description="Смещение, необходимое для выборки определённого подмножества записей.",
    ),
    count: int = Field(
        description="Количество записей, которое необходимо получить. Максимальное значение: 100.",
    ),
):
    """Получает посты со стены в ВК."""
    token = await _get_vk_token(runtime)
    url = "https://api.vk.com/method/wall.get"
    data = {
        "domain": domain,
        "offset": offset,
        "count": count,
        "access_token": token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            return response_json
        posts = response_json["response"]["items"]
        for post in posts:
            post.pop("attachments", None)
        await asyncio.sleep(0.3)
        return posts


@tool
async def vk_get_comments(
    runtime: ToolRuntime,
    owner_id: str = Field(
        description="Идентификатор владельца страницы (пользователь или сообщество). Идентификатор сообщества указывается со знаком '-'.",
    ),
    post_id: int = Field(description="Идентификатор записи на стене."),
    offset: int = Field(
        description="Сдвиг, необходимый для получения конкретной выборки результатов.",
    ),
    count: int = Field(
        description="Число комментариев, которые необходимо получить. По умолчанию: 10, максимум: 100.",
    ),
):
    """Получает комментарии к посту в ВК."""
    token = await _get_vk_token(runtime)
    url = "https://api.vk.com/method/wall.getComments"
    data = {
        "owner_id": owner_id,
        "post_id": post_id,
        "offset": offset,
        "count": count,
        "access_token": token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            return response_json
        posts = response_json["response"]["items"]
        for post in posts:
            post.pop("attachments", None)
        await asyncio.sleep(0.3)
        return posts


async def get_page_id(domain: str, runtime: ToolRuntime) -> int:
    token = await _get_vk_token(runtime)
    url = "https://api.vk.com/method/utils.resolveScreenName"
    data = {
        "screen_name": domain,
        "access_token": token,
        "v": "5.199",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={}, data=data)
        response_json = response.json()
        if "response" not in response_json:
            raise VKException(response_json)
        if not response_json["response"]:
            raise VKException("Group not found")
        page_info = response_json["response"]
        if page_info["type"] == "user":
            return page_info["object_id"]
        if page_info["type"] == "community_application":
            return page_info["group_id"]
        return -page_info["object_id"]


@tool(parse_docstring=True)
async def vk_get_last_comments(
    domain: str,
    runtime: ToolRuntime,
    count: int | None = None,
):
    """Получает комментарии с последних постов в ВК

    Args:
        domain: Короткий адрес пользователя или сообщества.
        count: Число комментариев, которые необходимо получить.
    """
    token = await _get_vk_token(runtime)
    limit = 300 if count is None else count
    if (
        domain.startswith("id")
        or domain.startswith("wall")
        or domain.startswith("group")
    ):
        owner_id = int(domain.replace("id", ""))
        if not domain.startswith("id"):
            owner_id = -owner_id
    else:
        owner_id = await get_page_id(domain, runtime)

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
        "access_token": token,
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
        max_n = min(limit, total_comments)
        while len(result) < max_n:
            for it, post_id in iters_with_ids:
                try:
                    comment = next(it)
                    comment["post_id"] = post_id
                    comment.pop("attachments", None)
                    result.append(comment)
                    if len(result) == limit:
                        break
                except StopIteration:
                    continue
        return result
