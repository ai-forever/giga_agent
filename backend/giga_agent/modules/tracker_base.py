"""Общий слой провайдеров-трекеров: нормализованный контракт Issue + базовый
модуль со стандартным REST переходов.

Любой трекер (Яндекс, Jira, Linear, мок) приводит данные к одному виду —
`{widget:"issue_board", provider, issues:[Issue]}` — и фронт-кит рендерит их без
правок. REST переходов одинаков для всех (`/{module_id}/issues/{key}/...`),
поэтому вынесен сюда фабрикой; провайдер реализует три корутины.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

WIDGET_KIND = "issue_board"


def make_issue(
    *,
    key: str,
    title: str | None,
    provider: str,
    status: str | None = None,
    description: str | None = None,
    tag: str | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Собирает нормализованный Issue под фронт-контракт (None-поля выкидываем)."""
    issue: dict[str, Any] = {
        "id": key,
        "key": key,
        "title": title or "",
        "provider": provider,
    }
    if status is not None:
        issue["status"] = status
    if description:
        issue["description"] = description
    if tag is not None:
        issue["tag"] = tag
    issue["fields"] = fields or []
    return issue


def board_payload(provider: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Нормализованный payload доски — то, что рендерит кит по маркеру widget."""
    return {"widget": WIDGET_KIND, "provider": provider, "issues": issues}


def single_payload(provider: str, issue: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "widget": WIDGET_KIND,
        "provider": provider,
        "issues": [issue] if issue else [],
    }


def field(value: Any, *, icon: str | None = None, label: str | None = None):
    """Удобный конструктор поля карточки; None-значение → None (отфильтровать)."""
    if value is None or value == "":
        return None
    f: dict[str, Any] = {"value": str(value)}
    if icon:
        f["icon"] = icon
    if label:
        f["label"] = label
    return f


class BaseTrackerModule(BaseModule):
    """База для модулей-трекеров: даёт стандартный REST переходов виджета.

    Провайдер реализует три корутины (list/execute/get) поверх своего API/данных.
    REST монтируется на `/{module_id}` и совпадает у всех провайдеров — StatusBadge
    на фронте строит эти URL из issue.provider.
    """

    async def widget_list_transitions(
        self, user: UserShort, issue_key: str
    ) -> list[dict[str, Any]]:
        """`[{id, display, to}]` — доступные переходы статуса задачи."""
        raise NotImplementedError

    async def widget_execute_transition(
        self, user: UserShort, issue_key: str, transition_id: str
    ) -> dict[str, Any] | None:
        """Исполняет переход, возвращает свежий нормализованный Issue (или None)."""
        raise NotImplementedError

    async def widget_get_issue(
        self, user: UserShort, issue_key: str
    ) -> dict[str, Any] | None:
        """Свежий нормализованный Issue для ручного refresh карточки."""
        raise NotImplementedError

    def get_api_router(self, **kwargs: Any) -> APIRouter:
        _ = kwargs
        router = APIRouter(tags=[self.id])
        module = self

        @router.get("/issues/{issue_key}/transitions")
        async def list_transitions(
            issue_key: str,
            current_user: Annotated[UserShort, Depends(get_current_active_user)],
        ) -> dict[str, Any]:
            return {
                "transitions": await module.widget_list_transitions(
                    current_user, issue_key
                )
            }

        @router.post("/issues/{issue_key}/transitions/{transition_id}")
        async def execute_transition(
            issue_key: str,
            transition_id: str,
            current_user: Annotated[UserShort, Depends(get_current_active_user)],
        ) -> dict[str, Any]:
            issue = await module.widget_execute_transition(
                current_user, issue_key, transition_id
            )
            if issue is None:
                raise HTTPException(status_code=404, detail="Переход не найден")
            return {"status": "transitioned", "issue": issue}

        @router.get("/issues/{issue_key}")
        async def get_issue(
            issue_key: str,
            current_user: Annotated[UserShort, Depends(get_current_active_user)],
        ) -> dict[str, Any]:
            return {"issue": await module.widget_get_issue(current_user, issue_key)}

        return router
