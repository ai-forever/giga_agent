from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from giga_agent.core.module import BaseModule
from giga_agent.modules.yandex_oauth.router import router as oauth_router


class YandexOAuthModule(BaseModule):
    """Сервисный модуль: общий OAuth-флоу Яндекса для Диска и Трекера.

    Пустой label — в списке пользовательских модулей не показывается, тулов не
    даёт. Только монтирует REST-эндпоинты подключения (/agent/yandex_oauth/...).
    """

    id: str = "yandex_oauth"

    def get_api_router(self, **kwargs: Any) -> APIRouter:
        _ = kwargs
        return oauth_router
