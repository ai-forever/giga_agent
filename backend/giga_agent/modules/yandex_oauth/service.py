"""Чистый OAuth-слой Яндекса: конфиг приложения, scope-реестр модулей,
построение authorize-URL, обмен кода и refresh токена.

Здесь нет ни БД, ни FastAPI — только HTTP к oauth.yandex.ru и работа с конфигом.
Per-module различия (scope, имена секретов) описаны в MODULES; один
зарегистрированный OAuth-аппликейшн обслуживает все модули, scope запрашивается
под конкретный модуль в момент авторизации.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from giga_agent.conf import GIGA_AGENT_PREFIX_API, get_settings

OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"
# Специальный redirect_uri для copy-paste флоу (verification_code): Яндекс
# показывает код на своей странице, пользователь переносит его руками.
VERIFICATION_CODE_REDIRECT = "https://oauth.yandex.ru/verification_code"


@dataclass(frozen=True)
class ModuleOAuth:
    """Описание OAuth-привязки одного модуля."""

    module_id: str
    scopes: tuple[str, ...]
    access_secret: str
    refresh_secret: str
    expires_secret: str


# Реестр модулей. Имена access-секретов намеренно совпадают с теми, что уже
# заводились вручную (YANDEX_DISK_ACCESS_TOKEN / YANDEX_TRACKER_OAUTH_TOKEN),
# чтобы ранее введённые токены продолжали работать как fallback без refresh.
MODULES: dict[str, ModuleOAuth] = {
    "yandex_disk": ModuleOAuth(
        module_id="yandex_disk",
        scopes=(
            "cloud_api:disk.read",
            "cloud_api:disk.write",
            "cloud_api:disk.info",
        ),
        access_secret="YANDEX_DISK_ACCESS_TOKEN",
        refresh_secret="YANDEX_DISK_REFRESH_TOKEN",
        expires_secret="YANDEX_DISK_TOKEN_EXPIRES_AT",
    ),
    "yandex_tracker": ModuleOAuth(
        module_id="yandex_tracker",
        scopes=("tracker:read", "tracker:write"),
        access_secret="YANDEX_TRACKER_OAUTH_TOKEN",
        refresh_secret="YANDEX_TRACKER_REFRESH_TOKEN",
        expires_secret="YANDEX_TRACKER_TOKEN_EXPIRES_AT",
    ),
    "yandex_mail": ModuleOAuth(
        module_id="yandex_mail",
        # imap_full — чтение, smtp — отправка, login:email — адрес ящика для
        # строки XOAUTH2 (через login.yandex.ru/info).
        scopes=("mail:imap_full", "mail:smtp", "login:email"),
        access_secret="YANDEX_MAIL_ACCESS_TOKEN",
        refresh_secret="YANDEX_MAIL_REFRESH_TOKEN",
        expires_secret="YANDEX_MAIL_TOKEN_EXPIRES_AT",
    ),
}


def get_module(module_id: str) -> ModuleOAuth:
    cfg = MODULES.get(module_id)
    if cfg is None:
        raise ValueError(f"Неизвестный yandex-модуль: {module_id}")
    return cfg


# Модули, у которых может быть СВОЁ Яндекс-приложение (Яндекс требует отдельное
# под mail-scope). Env: YANDEX_OAUTH_CLIENT_ID_<MODULE_UPPER> / ..._SECRET.
# Если не задано — фолбэк на общие YANDEX_OAUTH_CLIENT_ID/SECRET.
def client_credentials(module_id: str | None = None) -> tuple[str | None, str | None]:
    s = get_settings()
    if module_id == "yandex_mail" and s.giga_agent_yandex_mail_client_id:
        return (
            s.giga_agent_yandex_mail_client_id,
            s.giga_agent_yandex_mail_client_secret,
        )
    return (
        s.giga_agent_yandex_oauth_client_id,
        s.giga_agent_yandex_oauth_client_secret,
    )


def is_configured(module_id: str | None = None) -> bool:
    """True, если для модуля заданы client_id и client_secret (свои или общие)."""
    cid, secret = client_credentials(module_id)
    return bool(cid and secret)


def redirect_uri() -> str | None:
    """Server-callback redirect_uri: явный из настроек или собранный из base_url.

    Возвращает None, если базовый URL не сконфигурирован — тогда доступен только
    copy-paste флоу (verification_code).
    """
    s = get_settings()
    if s.giga_agent_yandex_oauth_redirect_uri:
        return s.giga_agent_yandex_oauth_redirect_uri.rstrip("/")
    base = s.giga_agent_base_url
    if not base:
        return None
    prefix = GIGA_AGENT_PREFIX_API.rstrip("/")
    return f"{base.rstrip('/')}{prefix}/yandex_oauth/callback"


def build_authorize_url(module_id: str, state: str, *, use_callback: bool) -> str:
    """Собирает URL страницы согласия Яндекса под scope модуля.

    use_callback=True — server-callback (нужен сконфигурированный redirect_uri);
    use_callback=False — verification_code (код показывается пользователю).
    """
    cfg = get_module(module_id)
    cid, _ = client_credentials(module_id)
    if not cid:
        raise ValueError("Не задан YANDEX_OAUTH_CLIENT_ID на сервере.")

    redirect = redirect_uri() if use_callback else VERIFICATION_CODE_REDIRECT
    if use_callback and not redirect:
        raise ValueError(
            "Не сконфигурирован redirect_uri (задайте GIGA_AGENT_BASE_URL "
            "или YANDEX_OAUTH_REDIRECT_URI)."
        )

    params = {
        "response_type": "code",
        "client_id": cid,
        "scope": " ".join(cfg.scopes),
        "state": state,
        "redirect_uri": redirect,
        # force_confirm гарантирует выдачу refresh-токена даже при повторном
        # подключении того же аккаунта.
        "force_confirm": "yes",
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def _post_token(
    data: dict[str, str], module_id: str | None = None
) -> dict[str, Any]:
    cid, secret = client_credentials(module_id)
    if not (cid and secret):
        raise ValueError("Не заданы client_id/client_secret приложения Яндекс.")
    payload = {**data, "client_id": cid, "client_secret": secret}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(OAUTH_TOKEN_URL, data=payload)
    if resp.status_code >= 400:
        detail: Any
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise YandexOAuthError(resp.status_code, detail)
    return resp.json()


class YandexOAuthError(Exception):
    """Ошибка обмена/обновления токена Яндекса (с телом ответа OAuth)."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Yandex OAuth error {status_code}: {detail}")


async def exchange_code(
    code: str, *, use_callback: bool, module_id: str | None = None
) -> dict[str, Any]:
    """Меняет authorization code на токены. redirect_uri должен совпадать с
    тем, что использовался в authorize; creds — из приложения модуля."""
    redirect = redirect_uri() if use_callback else VERIFICATION_CODE_REDIRECT
    data = {"grant_type": "authorization_code", "code": code}
    if redirect:
        data["redirect_uri"] = redirect
    return await _post_token(data, module_id)


async def refresh_access_token(
    refresh_token: str, module_id: str | None = None
) -> dict[str, Any]:
    """Обновляет access-токен по refresh-токену (creds — из приложения модуля)."""
    return await _post_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        module_id,
    )
