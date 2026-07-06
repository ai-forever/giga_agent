from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort


class YandexMailModule(BaseModule):
    id: str = "yandex_mail"
    label: str = "Яндекс.Почта"
    description: str = "Чтение и отправка писем в Яндекс.Почте"
    icon: str = "Mail"
    categories: list[str] = ["ru", "web"]
    lazy_tools: bool = True

    def get_providers(self, **kwargs: Any):
        _ = kwargs
        from giga_agent.modules.integrations.yandex_mail.provider import (
            build_yandex_mail_provider,
            yandex_mail_configured,
        )

        if not yandex_mail_configured():
            return []
        return [build_yandex_mail_provider()]

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if not self.get_providers():
            return False
        return await self.providers_connected(user)

    def get_api_router(self, **kwargs: Any) -> Optional[APIRouter]:
        # REST mail_inbox-виджета: список писем + чтение тела (см. api.py).
        _ = kwargs
        from giga_agent.modules.integrations.yandex_mail.api import (
            router as mail_api_router,
        )

        return mail_api_router

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not self.get_providers():
            return []
        if not await self.providers_connected(user):
            return []
        from giga_agent.modules.integrations.yandex_mail.tools import (
            mail_read,
            mail_search,
            mail_send,
        )

        # Порядок = приоритет для tool-router (~3 слота на ход).
        return [mail_search, mail_read, mail_send]
