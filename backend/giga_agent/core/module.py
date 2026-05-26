from __future__ import annotations

import os
import inspect
from typing import TYPE_CHECKING, Any, Optional, List, TypedDict, Literal
from typing_extensions import override

from langchain_core.runnables import RunnableConfig
from pydantic import ConfigDict, PrivateAttr
from langchain_core.load.serializable import Serializable
from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import APIRouter
    from giga_agent.core.agent.middleware import AgentMiddleware
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort


class SecretMetadata(TypedDict):
    name: str
    description: str | None
    type: Literal["pass", "text", "llm_id"]


class BaseModule(Serializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str  # Unique identifier for the module
    # Метаданные для UI. Пустой label = модуль сервисный, не показывается в списке.
    label: str = ""
    description: str = ""
    icon: str = ""  # Имя компонента lucide-react, например "FileText".
    _module_path: str = PrivateAttr()

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return True

    def __init__(self, **data):
        super().__init__(**data)

        # Автоматически определяем путь к файлу модуля
        # Используем self.__class__, чтобы получить путь к файлу конкретного подкласса
        self._module_path = os.path.dirname(inspect.getfile(self.__class__))

    @property
    def module_path(self) -> str:
        return self._module_path

    @property
    def migration_path(self) -> str | None:
        """Абсолютный путь к папке миграций модуля, если она существует"""
        path = os.path.join(self.module_path, "migrations")
        if os.path.exists(path) and os.path.isdir(path):
            return path
        return None

    def get_api_router(self, **kwargs: Any) -> Optional["APIRouter"]:
        """
        Возвращает FastAPI router для подключения к основному приложению.
        """
        return None

    def get_models(self, **kwargs: Any) -> list[type]:
        """
        Возвращает список SQLAlchemy-моделей модуля.
        Модули должны переопределять этот метод, чтобы CLI мог подгружать модели
        перед autogenerate миграций.
        """
        return []

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        """
        Возвращает список инструментов (tools), предоставляемых модулем.
        Переопределите в подклассе, чтобы добавить tools в агент.
        """
        return []

    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        """Финальная обёртка над `_get_tools`.

        Для каждого тула пользовательских модулей (с непустым `label`)
        проставляет `extras["module_id"] = self.id`, чтобы `graph_factory`
        мог фильтровать тулы по `disabled_modules` из `config.configurable`.
        Сервисные модули (`label == ""`) не помечаются — их тулы не подлежат
        пользовательскому отключению.
        """
        tools = await self._get_tools(user, agent, config=config, **kwargs)
        if not self.label:
            return tools
        for tool in tools:
            if tool.extras is None:
                tool.extras = {}
            tool.extras.setdefault("module_id", self.id)
        return tools

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
        state: Optional["AgentState"] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        """
        Возвращает строку с инструкциями (system prompt), которые модуль
        добавляет к системному промпту агента. Возвращает None если инструкций нет.
        """
        _ = config
        return None

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: "AgentState",
        agent: "BaseAgent",
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        """
        Возвращает расширение пользовательской задачи, которое будет добавлено
        в подготовленный user prompt перед запуском модели.
        """
        _ = config
        return None

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        """
        Возвращает метаданные секретов, которые нужны модулю.
        """
        return []

    def get_middleware(self, **kwargs: Any) -> Optional["AgentMiddleware"]:
        """
        Возвращает AgentMiddleware, предоставляемый модулем.
        Переопределите в подклассе, чтобы добавить middleware в агент.
        """
        return None

    def get_subgraphs(self, **kwargs: Any) -> dict[str, str]:
        """
        Возвращает дополнительные subgraph entrypoints для langgraph dev server.
        Формат значения: "python.import.path:variable_name".
        """
        return {}

    async def is_enabled(
        self,
        user: "UserShort | None",
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> bool:
        """True если у пользователя есть пререквизиты для использования модуля.

        Используется API `/agent/modules` для отдачи фронту списка доступных
        модулей. По умолчанию True (модуль доступен всем). Подклассы могут
        переопределить, например, для проверки наличия секрета или connector-а.
        """
        _ = user, config, kwargs
        return True

    async def on_startup(self, session: "AsyncSession", **kwargs: Any):
        """
        Hook executed on application startup.
        """
        pass


def collect_module_secrets(modules: list[BaseModule]) -> list[SecretMetadata]:
    secrets: list[SecretMetadata] = []
    seen_names: set[str] = set()

    for module in modules:
        for secret in module.get_secrets():
            name = secret["name"]
            if name in seen_names:
                continue

            secrets.append(
                {
                    "name": name,
                    "description": secret.get("description"),
                    "type": secret.get("type") or "pass",
                }
            )
            seen_names.add(name)

    return secrets
