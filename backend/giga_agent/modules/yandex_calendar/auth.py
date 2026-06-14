from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort

# Яндекс.Календарь = CalDAV (caldav.yandex.ru), JSON-REST нет. Надёжная авторизация
# — пароль приложения «Календарь (CalDAV)» (Яндекс ID → Пароли приложений) +
# Basic-auth. OAuth-кнопка сюда не растягивается (нет чистого calendar-scope),
# поэтому email и пароль приложения — ручные секреты модуля.
CALDAV_URL = "https://caldav.yandex.ru"
YANDEX_CALENDAR_EMAIL = "YANDEX_CALENDAR_EMAIL"
YANDEX_CALENDAR_APP_PASSWORD = "YANDEX_CALENDAR_APP_PASSWORD"


def _secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def has_calendar_creds(user: UserShort | None) -> bool:
    if user is None:
        return False
    return (
        _secret(user, YANDEX_CALENDAR_EMAIL) is not None
        and _secret(user, YANDEX_CALENDAR_APP_PASSWORD) is not None
    )


def get_calendar_creds_for_user(user: UserShort | None) -> tuple[str, str]:
    email = _secret(user, YANDEX_CALENDAR_EMAIL) if user else None
    password = _secret(user, YANDEX_CALENDAR_APP_PASSWORD) if user else None
    if not email or not password:
        raise ValueError(
            "Не настроен доступ к Яндекс.Календарю. Укажите секреты "
            f"{YANDEX_CALENDAR_EMAIL} и {YANDEX_CALENDAR_APP_PASSWORD} "
            "(пароль приложения «Календарь (CalDAV)») в настройках."
        )
    return email, password


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


async def get_calendar_creds(runtime: ToolRuntime) -> tuple[str, str]:
    """(email, app_password) текущего пользователя для CalDAV Basic-auth."""
    user = await _get_current_user(runtime)
    return get_calendar_creds_for_user(user)
