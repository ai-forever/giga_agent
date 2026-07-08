from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort


class YandexDiskModule(BaseModule):
    id: str = "yandex_disk"
    label: str = "Яндекс.Диск"
    description: str = "Работа с файлами и папками на Яндекс.Диске"
    icon: str = "HardDrive"
    categories: list[str] = ["ru", "docs"]
    lazy_tools: bool = True

    def get_providers(self, **kwargs: Any):
        _ = kwargs
        from giga_agent.modules.integrations.yandex_disk.provider import (
            build_yandex_disk_provider,
            yandex_disk_configured,
        )

        if not yandex_disk_configured():
            return []
        return [build_yandex_disk_provider()]

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if not self.get_providers():
            return False
        return await self.providers_connected(user)

    def get_api_router(self, **kwargs: Any) -> Optional[APIRouter]:
        # REST file_browser-виджета: навигация по папкам + публикация (см. api.py).
        _ = kwargs
        from giga_agent.modules.integrations.yandex_disk.api import (
            router as disk_api_router,
        )

        return disk_api_router

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not self.get_providers():
            return []
        if not await self.providers_connected(user):
            return []
        from giga_agent.modules.integrations.yandex_disk.tools import (
            disk_create_folder,
            disk_delete,
            disk_list_files,
            disk_publish,
            disk_read_text,
            disk_unpublish,
            disk_upload_text,
        )

        # Порядок = приоритет для tool-router (на GigaChat в ход влезает ~3
        # disk-тула): самые частые операции — впереди.
        return [
            disk_list_files,
            disk_create_folder,
            disk_upload_text,
            disk_read_text,
            disk_publish,
            disk_unpublish,
            disk_delete,
        ]
