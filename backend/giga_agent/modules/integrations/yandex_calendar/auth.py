"""OAuth-токен Яндекс.Календаря для текущего пользователя.

Действующий OAuth access-токен с авто-refresh, как у Диска.
"""

from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.integrations.service import get_access_token
from giga_agent.models.users import UserShort
from giga_agent.modules.integrations.yandex_calendar.provider import (
    YANDEX_CALENDAR_PROVIDER_KEY,
)
from giga_agent.utils.langgraph_sdk import get_user_id_from_config


def _runtime_user_id(runtime: ToolRuntime) -> uuid.UUID:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


async def get_calendar_token(runtime: ToolRuntime) -> str:
    """Действующий OAuth access-токен Яндекс.Календаря (авто-refresh)."""
    return await get_access_token(
        _runtime_user_id(runtime), YANDEX_CALENDAR_PROVIDER_KEY
    )


async def get_calendar_token_for_user(user: UserShort) -> str:
    """Версия для REST-эндпоинтов (если понадобится вне тулов)."""
    return await get_access_token(user.id, YANDEX_CALENDAR_PROVIDER_KEY)
