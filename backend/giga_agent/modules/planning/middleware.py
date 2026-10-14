"""Middleware планинга: сидирует AgentState["mode"] в начале хода.

before_agent выполняется один раз на пользовательский ход (START → before_agent),
цикл tools → before_model его не задевает. Поэтому здесь мы выставляем mode по
тумблеру `plan_mode` из config на КАЖДЫЙ новый ход, а mid-turn флип в "normal"
(его делает present_plan после подтверждения) переживает resume и не сбрасывается
до следующего хода.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState


class PlanningMiddleware(AgentMiddleware):
    async def before_agent(
        self, state: AgentState, runtime: Any, config: RunnableConfig
    ) -> dict[str, Any] | None:
        _ = state, runtime
        configurable = (config or {}).get("configurable") or {}
        if configurable.get("plan_mode"):
            return {
                "mode": "plan",
                "plan_content": "",
                "todos": [],
                "todo_id_seq": 0,
                "plan_approved": False,
                "todos_editable": False,
            }
        return {"mode": "normal", "plan_approved": False, "todos_editable": False}
