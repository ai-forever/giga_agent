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
    """Подробный plan-mode и рабочий todo-лист normal-mode.

    Сервисный модуль (label="") — его тулы всегда доступны и не отключаются
    пользователем через disabled_modules.

    Статус: реализовано end-to-end (бэкенд + фронт + тесты).
      - write_todo / update_plan / present_plan: tools.py.
      - plan_content / todos / mode поля: AgentState (core/agent/types.py).
      - сидирование mode из config.configurable.plan_mode: PlanningMiddleware.
      - гейтинг тулов по state["mode"]: единая policy из
        core/agent/tool_policy.py проверяется при bind и перед исполнением.
      - фронт: тумблер «Режим планирования» (InputArea), чеклист (ToolCallsList),
        карточка approve/reject (PlanApprovalCard на interrupt plan_approval).
      - тесты: tests/modules/planning/test_planning.py.
    См. docs/PLANNING_MODE.md. plan mode включается тумблером на фронте
    (config.configurable.plan_mode). В normal-mode доступен write_todo, а
    update_plan/present_plan доступны только в plan-mode.
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
        from giga_agent.modules.planning.tools import (
            present_plan,
            update_plan,
            write_todo,
        )

        return [write_todo, update_plan, present_plan]

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
        if state is not None and state.get("mode") == "plan":
            # В plan mode инструкция добавляется BaseAgent.get_prompt в самый
            # низ основного system prompt, чтобы её не затерли другие модули.
            return None

        from giga_agent.modules.planning.prompts import NORMAL_INSTRUCTIONS

        return NORMAL_INSTRUCTIONS
