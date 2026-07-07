from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.integrations.service import get_access_token
from giga_agent.models.users import UserShort
from giga_agent.modules.integrations.yandex_disk.provider import (
    YANDEX_DISK_PROVIDER_KEY,
)
from giga_agent.utils.langgraph_sdk import get_user_id_from_config


def _runtime_user_id(runtime: ToolRuntime) -> uuid.UUID:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


async def get_disk_token(runtime: ToolRuntime) -> str:
    """Действующий access-токен Яндекс.Диска текущего пользователя (авто-refresh)."""
    return await get_access_token(_runtime_user_id(runtime), YANDEX_DISK_PROVIDER_KEY)


async def get_disk_token_for_user(user: UserShort) -> str:
    """Версия для REST-эндпоинтов (виджет file_browser)."""
    return await get_access_token(user.id, YANDEX_DISK_PROVIDER_KEY)
