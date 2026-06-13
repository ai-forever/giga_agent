from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.yandex_mail.auth import (
    YANDEX_MAIL_ACCESS_TOKEN,
    has_mail_token,
)


class YandexMailModule(BaseModule):
    id: str = "yandex_mail"
    label: str = "Яндекс.Почта"
    description: str = "Чтение и отправка писем в Яндекс.Почте"
    icon: str = "Mail"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return has_mail_token(user)

    def get_api_router(self, **kwargs: Any) -> Optional[APIRouter]:
        # REST mail_inbox-виджета: список писем + чтение тела (см. api.py).
        _ = kwargs
        from giga_agent.modules.yandex_mail.api import router as mail_api_router

        return mail_api_router

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": YANDEX_MAIL_ACCESS_TOKEN,
                "description": (
                    "OAuth-токен Яндекс.Почты (scope mail:imap_full + mail:smtp). "
                    "Обычно заполняется кнопкой «Подключить Яндекс»."
                ),
                "type": "pass",
            }
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not has_mail_token(user):
            return []
        from giga_agent.modules.yandex_mail.tools import (
            mail_read,
            mail_search,
            mail_send,
        )

        # Порядок = приоритет для tool-router (~3 слота на ход).
        return [mail_search, mail_read, mail_send]
