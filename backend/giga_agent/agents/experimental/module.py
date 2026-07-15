"""Регистрационный модуль экспериментального графа.

Единственная задача — объявить сабграф `giga_agent_experimental` в
`langgraph.json` (через `get_subgraphs`). Активация режима гейтится на фронте по
`GIGA_AGENT_EXPERIMENTAL_MODE` (см. app-config), поэтому регистрация графа
безусловна — так `langgraph.json` остаётся стабильным. Модуль сервисный:
без тулов, инструкций и пустой label (в списке модулей не показывается).
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from giga_agent.core.module import BaseModule

if TYPE_CHECKING:
    from fastapi import APIRouter


class ExperimentalModule(BaseModule):
    id: str = "experimental"

    def get_subgraphs(self, **kwargs: Any) -> dict[str, str]:
        _ = kwargs
        return {
            "giga_agent_experimental": ("giga_agent.agents.experimental.graph:graph"),
        }

    def get_api_router(self, **kwargs: Any) -> Optional["APIRouter"]:
        # Ручка активности монтируется под /agent/experimental/... (base.py).
        _ = kwargs
        from giga_agent.agents.experimental.api import router

        return router
