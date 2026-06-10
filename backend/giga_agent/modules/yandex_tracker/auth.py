from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort

# Секреты пользователя для Яндекс.Трекера.
# На первом этапе заводятся вручную в настройках; позже общий OAuth (см. Диск)
# заполнит токен автоматически — org-id всё равно останется ручным.
YANDEX_TRACKER_OAUTH_TOKEN = "YANDEX_TRACKER_OAUTH_TOKEN"
YANDEX_TRACKER_ORG_ID = "YANDEX_TRACKER_ORG_ID"


def _get_user_secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def has_tracker_creds(user: UserShort | None) -> bool:
    if user is None:
        return False
    return (
        _get_user_secret(user, YANDEX_TRACKER_OAUTH_TOKEN) is not None
        and _get_user_secret(user, YANDEX_TRACKER_ORG_ID) is not None
    )


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


def get_tracker_auth_for_user(user: UserShort | None) -> tuple[str, str]:
    """Возвращает (oauth_token, org_id) из уже загруженного UserShort.

    Используется в REST-эндпоинтах GenUI-виджетов, где пользователь приходит
    из FastAPI-зависимости (Depends(get_current_active_user)), а не из
    ToolRuntime. Логика чтения секретов общая с тул-вариантом ниже.
    """
    token = _get_user_secret(user, YANDEX_TRACKER_OAUTH_TOKEN) if user else None
    org_id = _get_user_secret(user, YANDEX_TRACKER_ORG_ID) if user else None
    if token is None or org_id is None:
        raise ValueError(
            "Не настроен доступ к Яндекс.Трекеру. Укажите секреты "
            f"{YANDEX_TRACKER_OAUTH_TOKEN} и {YANDEX_TRACKER_ORG_ID} "
            "в настройках пользователя."
        )
    return token, org_id


async def get_tracker_auth(runtime: ToolRuntime) -> tuple[str, str]:
    """Возвращает (oauth_token, org_id) текущего пользователя для Трекера.

    Токен берётся из общего OAuth-стора с прозрачным refresh; org-id остаётся
    отдельным ручным секретом (из OAuth он не приходит).
    """
    from giga_agent.modules.yandex_oauth import tokens

    user = await _get_current_user(runtime)
    org_id = _get_user_secret(user, YANDEX_TRACKER_ORG_ID)
    if org_id is None:
        raise ValueError(
            "Не указан ID организации Яндекс.Трекера. Заполните секрет "
            f"{YANDEX_TRACKER_ORG_ID} в настройках пользователя."
        )
    token = await tokens.get_valid_access_token(runtime, "yandex_tracker")
    return token, org_id
