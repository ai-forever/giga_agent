"""Хранилище OAuth-токенов Яндекса в секретах пользователя + прозрачный refresh.

Точка инкапсуляции: тулы Диска/Трекера зовут `get_valid_access_token(...)` и не
знают про срок жизни и обновление. Если access протух (или скоро протухнет) и
есть refresh — токен обновляется и переписывается в БД здесь же.

Обратная совместимость: если в секрете лежит только access без refresh/expiry
(ранее введённый вручную токен) — он возвращается как есть, без обновления.
"""

from __future__ import annotations

import time
import uuid

from langchain.tools import ToolRuntime
from sqlalchemy import select

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import User, UserRepository, UserShort
from giga_agent.modules.yandex_oauth import service

# Обновляем токен заранее, чтобы не отдать «вот-вот протухший».
_EXPIRY_SKEW_SECONDS = 120


def _secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def is_connected(user: UserShort | None, module_id: str) -> bool:
    """True, если у пользователя есть access-токен модуля (ручной или OAuth)."""
    if user is None:
        return False
    cfg = service.get_module(module_id)
    return _secret(user, cfg.access_secret) is not None


async def _load_user(user_id: uuid.UUID) -> UserShort:
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(user_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {user_id} не найден")
    return user


async def _persist(user_id: uuid.UUID, patch: dict[str, str | None]) -> None:
    """Мёрджит patch в user.secrets (None — удаляет ключ) и инвалидирует кэш."""
    factory = await get_session_factory()
    async with factory() as session:
        model = await session.scalar(select(User).where(User.id == user_id))
        if model is None:
            raise ValueError(f"Пользователь {user_id} не найден")
        secrets = dict(model.secrets or {})
        for key, value in patch.items():
            if value is None:
                secrets.pop(key, None)
            else:
                secrets[key] = value
        model.secrets = secrets
        await session.commit()
    await UserRepository.invalidate_cache(user_id)


def _expires_at(user: UserShort, cfg: service.ModuleOAuth) -> int | None:
    raw = _secret(user, cfg.expires_secret)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


async def store_tokens(
    user_id: uuid.UUID, module_id: str, token_response: dict
) -> None:
    """Сохраняет результат exchange/refresh в секреты пользователя."""
    cfg = service.get_module(module_id)
    access = token_response.get("access_token")
    if not access:
        raise ValueError("Ответ Яндекса не содержит access_token")
    patch: dict[str, str | None] = {cfg.access_secret: str(access)}

    refresh = token_response.get("refresh_token")
    if refresh:
        patch[cfg.refresh_secret] = str(refresh)

    expires_in = token_response.get("expires_in")
    if expires_in:
        try:
            patch[cfg.expires_secret] = str(int(time.time()) + int(expires_in))
        except (TypeError, ValueError):
            pass
    await _persist(user_id, patch)


async def disconnect(user_id: uuid.UUID, module_id: str) -> None:
    """Стирает все OAuth-секреты модуля."""
    cfg = service.get_module(module_id)
    await _persist(
        user_id,
        {cfg.access_secret: None, cfg.refresh_secret: None, cfg.expires_secret: None},
    )


async def _valid_token_for_user(user: UserShort, module_id: str) -> str:
    cfg = service.get_module(module_id)
    access = _secret(user, cfg.access_secret)
    refresh = _secret(user, cfg.refresh_secret)
    expires_at = _expires_at(user, cfg)

    fresh_enough = expires_at is None or expires_at - _EXPIRY_SKEW_SECONDS > time.time()
    if access and fresh_enough:
        return access

    # Протух (или скоро) и есть refresh — обновляем и переписываем в БД.
    if refresh:
        token_response = await service.refresh_access_token(refresh, module_id)
        await store_tokens(user.id, module_id, token_response)
        new_access = token_response.get("access_token")
        if new_access:
            return str(new_access)

    # Нет expiry/refresh, но есть access — это ручной токен, отдаём как есть.
    if access:
        return access

    raise ValueError(
        f"Модуль {module_id} не подключён к Яндексу. "
        "Нажмите «Подключить Яндекс» в настройках."
    )


async def get_valid_access_token(runtime: ToolRuntime, module_id: str) -> str:
    """Действующий access-токен текущего пользователя (с авто-refresh)."""
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    user = await _load_user(owner_id)
    return await _valid_token_for_user(user, module_id)


async def get_valid_access_token_for_user(
    user: UserShort | None, module_id: str
) -> str:
    """Версия для REST-эндпоинтов (GenUI), где пользователь уже загружен."""
    if user is None:
        raise ValueError("Требуется аутентификация.")
    return await _valid_token_for_user(user, module_id)
