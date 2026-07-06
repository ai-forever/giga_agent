from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.db import get_session_factory
from giga_agent.core.integrations.service import get_access_token
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.modules.integrations.yandex_tracker.provider import (
    YANDEX_TRACKER_PROVIDER_KEY,
)

# Ручной секрет: ID организации Трекера (X-Cloud-Org-ID / X-Org-ID). OAuth его
# не выдаёт, поэтому вводится отдельно.
YANDEX_TRACKER_ORG_ID = "YANDEX_TRACKER_ORG_ID"


def _secret(user: UserShort | None, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def has_tracker_org(user: UserShort | None) -> bool:
    if user is None:
        return False
    return _secret(user, YANDEX_TRACKER_ORG_ID) is not None


def _require_org(user: UserShort | None) -> str:
    org_id = _secret(user, YANDEX_TRACKER_ORG_ID)
    if org_id is None:
        raise ValueError(
            "Не указан ID организации Яндекс.Трекера. Заполните секрет "
            f"{YANDEX_TRACKER_ORG_ID} в настройках модуля."
        )
    return org_id


async def _load_user(user_id: uuid.UUID) -> UserShort:
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(user_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {user_id} не найден")
    return user


async def get_tracker_auth(runtime: ToolRuntime) -> tuple[str, str]:
    """(oauth_token, org_id) текущего пользователя для Трекера."""
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    user = await _load_user(owner_id)
    org_id = _require_org(user)
    token = await get_access_token(owner_id, YANDEX_TRACKER_PROVIDER_KEY)
    return token, org_id


async def get_tracker_auth_for_user(user: UserShort) -> tuple[str, str]:
    """Версия для REST-эндпоинтов (виджет доски): пользователь уже из FastAPI."""
    org_id = _require_org(user)
    token = await get_access_token(user.id, YANDEX_TRACKER_PROVIDER_KEY)
    return token, org_id
