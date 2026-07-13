"""Троттлинг логина против брутфорса аккаунтов.

Ведём распределённый счётчик неудачных входов на паре ``(email, client_ip)`` в
cashews (Redis в проде, ``mem://`` локально). Два яруса: быстрый гасит всплески,
медленный задаёт суточный потолок. Проверка выполняется ДО bcrypt — чтобы не
тратить CPU на перебор и не давать тайминг-сигнал.

Важные свойства (обсуждены и зафиксированы в плане):
- Ключ по ``(email, ip)`` → злоумышленник не может залочить вход жертве (нет lockout-DoS).
- Запись неудач только для существующих аккаунтов (см. вызов в ``api.login_for_access_token``)
  → мусорные/варьируемые email не сажают ключи в Redis (нет cache-fill).
- Fail-open: при недоступности Redis логин не блокируется (иначе падение Redis = DoS входа).
- Всё поведение под флагом ``giga_agent_login_throttle_enabled``.
"""

from __future__ import annotations

import logging

from cashews import cache
from fastapi import HTTPException, Request, status

from giga_agent.conf import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "authfail"


def get_client_ip(request: Request) -> str:
    """Реальный IP клиента.

    Если задан ``giga_agent_client_ip_header`` (в проде ``X-Client-IP``, который оператор
    пробрасывает с edge) — берём его. Иначе — TCP-пир (``request.client.host``), который
    подделать нельзя. Доверять заголовку безопасно только когда внутренние порты недоступны
    из интернета — это ответственность оператора при выставлении ENV.
    """
    header = get_settings().giga_agent_client_ip_header
    if header:
        value = request.headers.get(header)
        if value:
            # Заголовок однозначный (не список) — берём как есть.
            return value.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _keys(email: str, ip: str) -> tuple[str, str]:
    email = email.strip().lower()
    base = f"{_KEY_PREFIX}:{email}:{ip}"
    return f"{base}:f", f"{base}:s"


async def check_login_throttle(email: str, ip: str) -> None:
    """Отклонить попытку входа 429, если исчерпан любой из ярусов. Вызывать ДО bcrypt."""
    settings = get_settings()
    if not settings.giga_agent_login_throttle_enabled:
        return

    key_f, key_s = _keys(email, ip)
    try:
        fast = await cache.get(key_f) or 0
        slow = await cache.get(key_s) or 0
    except Exception:  # fail-open: Redis недоступен — не блокируем вход
        logger.warning("login throttle check skipped: cache unavailable", exc_info=True)
        return

    if fast >= settings.giga_agent_login_throttle_fast_max:
        _raise_too_many(settings.giga_agent_login_throttle_fast_window_sec)
    if slow >= settings.giga_agent_login_throttle_slow_max:
        _raise_too_many(settings.giga_agent_login_throttle_slow_window_sec)


async def record_login_failure(email: str, ip: str) -> None:
    """Инкремент обоих ярусов после неудачной проверки пароля.

    Вызывать ТОЛЬКО для существующих аккаунтов — иначе перебор случайных email
    засадит Redis мусорными ключами (cache-fill).
    """
    settings = get_settings()
    if not settings.giga_agent_login_throttle_enabled:
        return

    key_f, key_s = _keys(email, ip)
    try:
        await cache.incr(key_f, expire=settings.giga_agent_login_throttle_fast_window_sec)
        await cache.incr(key_s, expire=settings.giga_agent_login_throttle_slow_window_sec)
    except Exception:  # fail-open
        logger.warning("login throttle record skipped: cache unavailable", exc_info=True)


async def reset_login(email: str, ip: str) -> None:
    """Сбросить оба счётчика после успешного входа."""
    settings = get_settings()
    if not settings.giga_agent_login_throttle_enabled:
        return

    key_f, key_s = _keys(email, ip)
    try:
        await cache.delete(key_f)
        await cache.delete(key_s)
    except Exception:  # fail-open
        logger.warning("login throttle reset skipped: cache unavailable", exc_info=True)


def _raise_too_many(retry_after_sec: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts. Try again later.",
        headers={"Retry-After": str(retry_after_sec)},
    )
