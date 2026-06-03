from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.yandex_disk.auth import YANDEX_DISK_ACCESS_TOKEN, has_disk_token


class YandexDiskModule(BaseModule):
    id: str = "yandex_disk"
    label: str = "Яндекс.Диск"
    description: str = "Работа с файлами и папками на Яндекс.Диске"
    icon: str = "HardDrive"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return has_disk_token(user)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": YANDEX_DISK_ACCESS_TOKEN,
                "description": (
                    "OAuth-токен Яндекс.Диска (scope cloud_api:disk.*). "
                    "Получите токен в Яндекс OAuth и вставьте сюда."
                ),
                "type": "pass",
            }
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not has_disk_token(user):
            return []
        from giga_agent.modules.yandex_disk.tools import (
            disk_create_folder,
            disk_delete,
            disk_list_files,
            disk_publish,
            disk_read_text,
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
            disk_delete,
        ]
