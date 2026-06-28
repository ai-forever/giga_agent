from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.module import BaseModule
from giga_agent.core.integrations.base import IntegrationProvider
from giga_agent.core.integrations.registry import (
    YANDEX_PROVIDER_KEY,
    get_static_provider,
)

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.models.users import UserShort


class YandexDiskModule(BaseModule):
    id: str = "yandex_disk"
    label: str = "Яндекс.Диск"
    description: str = "Работа с файлами на Яндекс.Диске"
    icon: str = "HardDrive"
    lazy_tools: bool = True

    def get_providers(self, **kwargs: Any) -> list[IntegrationProvider]:
        _ = kwargs
        provider = get_static_provider(YANDEX_PROVIDER_KEY)
        # None when YANDEX_OAUTH_CLIENT_ID/SECRET are not configured.
        return [provider] if provider is not None else []

    async def is_enabled(
        self, user: "UserShort | None", *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        if not self.get_providers():
            return False
        return await self.providers_connected(user)

    async def _get_tools(
        self,
        user: "UserShort | None",
        agent: "BaseAgent",
        *,
        config=None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not await self.is_enabled(user):
            return []
        from giga_agent.modules.yandex_disk.tools import (
            yandex_disk_download_url,
            yandex_disk_info,
            yandex_disk_list,
        )

        return [yandex_disk_info, yandex_disk_list, yandex_disk_download_url]
