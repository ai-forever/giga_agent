from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort

if TYPE_CHECKING:
    from giga_agent.core.agent.types import AgentState

# Результаты ряда тулов рисуются как интерактивные GenUI-виджеты (доски задач
# трекеров, файловый браузер Диска). Они УЖЕ видны пользователю — текстовый
# пересказ их содержимого избыточен и засоряет ответ.
GENUI_INSTRUCTIONS = (
    "Часть инструментов возвращает результат, который пользователю показывается "
    "как интерактивный виджет-карточка, а не как текст: доски и карточки задач "
    "трекеров (tracker_*, *_board, mock_*) и файловый браузер Яндекс.Диска "
    "(disk_list_files). Их содержимое пользователь уже видит на экране. Поэтому "
    "НЕ пересказывай результат такого инструмента текстом: не перечисляй задачи "
    "или файлы списком, не повторяй статусы, размеры и даты. Ограничься одной "
    "короткой подводящей фразой (или вообще без текста) и сразу переходи к "
    "следующему действию или вопросу пользователя."
)


class ToolRouterModule(BaseModule):
    # label пустой → сервисный модуль: его тул (request_tools) всегда доступен
    # и не подлежит отключению через disabled_modules.
    id: str = "tool_router"

    def get_middleware(self, **kwargs: Any) -> Optional[AgentMiddleware]:
        _ = kwargs
        from giga_agent.modules.tool_router.middleware import ToolRouterMiddleware

        return ToolRouterMiddleware()

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = user, agent, state, config, kwargs
        return GENUI_INSTRUCTIONS

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent, config, kwargs
        from giga_agent.modules.tool_router.tools import request_tools

        return [request_tools]
