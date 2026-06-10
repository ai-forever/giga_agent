from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort

# Имя секрета пользователя, в котором хранится OAuth access-токен Яндекс.Диска.
# На первом этапе токен заводится вручную через настройки пользователя.
# Позже сюда же будет писать значение OAuth callback (см. module.get_api_router).
YANDEX_DISK_ACCESS_TOKEN = "YANDEX_DISK_ACCESS_TOKEN"


def _get_user_secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def has_disk_token(user: UserShort | None) -> bool:
    if user is None:
        return False
    return _get_user_secret(user, YANDEX_DISK_ACCESS_TOKEN) is not None


async def _get_current_user(runtime: ToolRuntime) -> UserShort:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {owner_id} не найден")
    return user


async def get_valid_token(runtime: ToolRuntime) -> str:
    """Возвращает действующий access-токен Яндекс.Диска текущего пользователя.

    Делегирует в общий OAuth-стор: если токен получен через «Подключить Яндекс»
    и протух — он прозрачно обновляется по refresh-токену. Ранее введённый
    вручную токен (без refresh) отдаётся как есть.
    """
    from giga_agent.modules.yandex_oauth import tokens

    return await tokens.get_valid_access_token(runtime, "yandex_disk")
