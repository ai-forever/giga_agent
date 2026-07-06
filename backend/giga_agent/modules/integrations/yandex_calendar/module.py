from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort


class YandexCalendarModule(BaseModule):
    id: str = "yandex_calendar"
    label: str = "Яндекс.Календарь"
    description: str = "Просмотр и создание событий в Яндекс.Календаре (CalDAV)"
    icon: str = "Calendar"
    categories: list[str] = ["ru", "web"]
    lazy_tools: bool = True

    def get_providers(self, **kwargs: Any):
        _ = kwargs
        from giga_agent.modules.integrations.yandex_calendar.provider import (
            build_yandex_calendar_provider,
            yandex_calendar_configured,
        )

        if not yandex_calendar_configured():
            return []
        return [build_yandex_calendar_provider()]

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if not self.get_providers():
            return False
        return await self.providers_connected(user)

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not self.get_providers():
            return []
        if not await self.providers_connected(user):
            return []
        from giga_agent.modules.integrations.yandex_calendar.tools import (
            calendar_create_event,
            calendar_delete_event,
            calendar_list_events,
            calendar_month,
        )

        # Порядок = приоритет для tool-router (на GigaChat ~3 слота).
        return [
            calendar_list_events,
            calendar_month,
            calendar_create_event,
            calendar_delete_event,
        ]
