from __future__ import annotations

from typing import Any, List, Optional, TYPE_CHECKING

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort

if TYPE_CHECKING:
    from giga_agent.core.agent.middleware import AgentMiddleware


class PlanningModule(BaseModule):
    """Режим планирования: динамический todo-лист + plan-mode с подтверждением.

    Сервисный модуль (label="") — его тулы всегда доступны и не отключаются
    пользователем через disabled_modules.

    Статус:
      - update_plan / present_plan: реализованы (tools.py), пушат план в UI.
      - plan / mode поля: добавлены в AgentState (core/agent/types.py).
      - сидирование mode из config.configurable.plan_mode: PlanningMiddleware.
      - гейтинг тулов по state["mode"]: graph_factory.amodel_node
        (PLAN_MODE_BLOCKED_MODULES).
      - ОСТАЁТСЯ: фронт (чеклист, карточка approve/edit/reject, тумблер plan mode)
        и тесты. См. docs/PLANNING_MODE.md.
    plan mode включается через config.configurable.plan_mode (тумблер на фронте).
    Пока фронт не шлёт этот флаг — plan mode неактивен, и present_plan модели не
    предлагается; update_plan работает в обычном режиме.
    """

    id: str = "planning"
    label: str = ""  # сервисный модуль: тулы всегда доступны
    description: str = "Планирование: декомпозиция запроса в список задач."
    icon: str = "ListChecks"

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> List[BaseTool]:
        _ = user, agent, config, kwargs
        from giga_agent.modules.planning.tools import present_plan, update_plan

        return [update_plan, present_plan]

    def get_middleware(self, **kwargs: Any) -> Optional["AgentMiddleware"]:
        _ = kwargs
        from giga_agent.modules.planning.middleware import PlanningMiddleware

        return PlanningMiddleware()

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional[AgentState] = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = user, agent, config, kwargs
        from giga_agent.modules.planning.prompts import (
            NORMAL_INSTRUCTIONS,
            PLAN_MODE_INSTRUCTIONS,
        )

        if state is not None and state.get("mode") == "plan":
            return PLAN_MODE_INSTRUCTIONS
        return NORMAL_INSTRUCTIONS
