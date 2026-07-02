from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.yandex_tracker.auth import (
    YANDEX_TRACKER_OAUTH_TOKEN,
    YANDEX_TRACKER_ORG_ID,
    has_tracker_creds,
)


class YandexTrackerModule(BaseModule):
    id: str = "yandex_tracker"
    label: str = "Яндекс.Трекер"
    description: str = "Поиск и ведение задач в Яндекс.Трекере"
    icon: str = "ListTodo"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return has_tracker_creds(user)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": YANDEX_TRACKER_OAUTH_TOKEN,
                "description": (
                    "OAuth-токен Яндекс.Трекера. Получите токен в Яндекс OAuth "
                    "и вставьте сюда."
                ),
                "type": "pass",
            },
            {
                "name": YANDEX_TRACKER_ORG_ID,
                "description": (
                    "ID организации Трекера (X-Cloud-Org-ID для Yandex Cloud "
                    "или X-Org-ID для Яндекс 360)."
                ),
                "type": "text",
            },
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not has_tracker_creds(user):
            return []
        from giga_agent.modules.yandex_tracker.tools import (
            tracker_add_comment,
            tracker_create_issue,
            tracker_get_issue,
            tracker_search_issues,
            tracker_transition,
            tracker_update_issue,
        )

        # Порядок = приоритет для tool-router (на GigaChat в ход влезает ~3
        # tracker-тула): самые частые операции — впереди.
        return [
            tracker_search_issues,
            tracker_get_issue,
            tracker_create_issue,
            tracker_add_comment,
            tracker_update_issue,
            tracker_transition,
        ]
