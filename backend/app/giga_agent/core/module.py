import os
import inspect
from typing import TYPE_CHECKING, Optional, List
from typing_extensions import override

from pydantic import ConfigDict, PrivateAttr
from langchain_core.load.serializable import Serializable
from langchain_core.tools import BaseTool
from giga_agent.models.users import UserShort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import APIRouter
    from giga_agent.core.agent.middleware import AgentMiddleware
    from giga_agent.core.agent.base import BaseAgent


class BaseModule(Serializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str  # Unique identifier for the module
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

    def get_api_router(self) -> Optional["APIRouter"]:
        """
        Возвращает FastAPI router для подключения к основному приложению.
        """
        return None

    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> List[BaseTool]:
        """
        Возвращает список инструментов (tools), предоставляемых модулем.
        Переопределите в подклассе, чтобы добавить tools в агент.
        """
        return []

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> str | None:
        """
        Возвращает строку с инструкциями (system prompt), которые модуль
        добавляет к системному промпту агента. Возвращает None если инструкций нет.
        """
        return None

    async def get_middleware(self) -> Optional["AgentMiddleware"]:
        """
        Возвращает список AgentMiddleware, предоставляемых модулем.
        Переопределите в подклассе, чтобы добавить middleware в агент.
        """
        return None

    async def on_startup(self, session: "AsyncSession"):
        """
        Hook executed on application startup.
        """
        pass
