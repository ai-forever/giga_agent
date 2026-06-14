from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.yandex_calendar.auth import (
    YANDEX_CALENDAR_APP_PASSWORD,
    YANDEX_CALENDAR_EMAIL,
    has_calendar_creds,
)


class YandexCalendarModule(BaseModule):
    id: str = "yandex_calendar"
    label: str = "Яндекс.Календарь"
    description: str = "Просмотр и создание событий в Яндекс.Календаре (CalDAV)"
    icon: str = "Calendar"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return has_calendar_creds(user)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": YANDEX_CALENDAR_EMAIL,
                "description": "Email ящика Яндекс (для CalDAV), напр. you@yandex.ru.",
                "type": "text",
            },
            {
                "name": YANDEX_CALENDAR_APP_PASSWORD,
                "description": (
                    "Пароль приложения «Календарь (CalDAV)» "
                    "(Яндекс ID → Пароли приложений). Не основной пароль."
                ),
                "type": "pass",
            },
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not has_calendar_creds(user):
            return []
        from giga_agent.modules.yandex_calendar.tools import (
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
