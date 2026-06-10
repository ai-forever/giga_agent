from __future__ import annotations

from typing import Any, List

import httpx
from fastapi import HTTPException
from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.tracker_base import BaseTrackerModule
from giga_agent.modules.yandex_tracker.auth import (
    YANDEX_TRACKER_OAUTH_TOKEN,
    YANDEX_TRACKER_ORG_ID,
    get_tracker_auth_for_user,
    has_tracker_creds,
)
from giga_agent.modules.yandex_tracker.tools import (
    TRACKER_API,
    _disp,
    _headers,
    _to_issue,
)


class YandexTrackerModule(BaseTrackerModule):
    id: str = "yandex_tracker"
    label: str = "Яндекс.Трекер"
    description: str = "Поиск и ведение задач в Яндекс.Трекере"
    icon: str = "ListTodo"

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        _ = config, kwargs
        return has_tracker_creds(user)

    # --- REST виджета (BaseTrackerModule.get_api_router зовёт эти методы) ---

    def _auth(self, user: UserShort) -> dict[str, str]:
        try:
            token, org_id = get_tracker_auth_for_user(user)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _headers(token, org_id)

    @staticmethod
    def _raise_for_tracker(exc: httpx.HTTPStatusError) -> None:
        try:
            detail: Any = exc.response.json()
        except Exception:  # noqa: BLE001 — тело может быть не-JSON
            detail = exc.response.text or "Ошибка Яндекс.Трекера"
        raise HTTPException(
            status_code=exc.response.status_code, detail=detail
        ) from exc

    async def widget_list_transitions(
        self, user: UserShort, issue_key: str
    ) -> list[dict[str, Any]]:
        headers = self._auth(user)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRACKER_API}/issues/{issue_key}/transitions", headers=headers
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._raise_for_tracker(exc)
            transitions = resp.json()
        return [
            {"id": t.get("id"), "display": t.get("display"), "to": _disp(t.get("to"))}
            for t in transitions
        ]

    async def _fetch_issue(
        self, client: httpx.AsyncClient, headers: dict[str, str], issue_key: str
    ) -> dict[str, Any]:
        resp = await client.get(f"{TRACKER_API}/issues/{issue_key}", headers=headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._raise_for_tracker(exc)
        return _to_issue(resp.json(), with_description=True)

    async def widget_execute_transition(
        self, user: UserShort, issue_key: str, transition_id: str
    ) -> dict[str, Any] | None:
        headers = self._auth(user)
        async with httpx.AsyncClient() as client:
            ex = await client.post(
                f"{TRACKER_API}/issues/{issue_key}/transitions/{transition_id}/_execute",
                headers=headers,
                json={},
            )
            try:
                ex.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._raise_for_tracker(exc)
            # Перечитываем: ответ _execute не всегда содержит новый статус.
            return await self._fetch_issue(client, headers, issue_key)

    async def widget_get_issue(
        self, user: UserShort, issue_key: str
    ) -> dict[str, Any] | None:
        headers = self._auth(user)
        async with httpx.AsyncClient() as client:
            return await self._fetch_issue(client, headers, issue_key)

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": YANDEX_TRACKER_OAUTH_TOKEN,
                "description": (
                    "OAuth-токен Яндекс.Трекера. Получите токен в Яндекс OAuth "
                    "и вставьте сюда."
                ),
                "type": "pass",
            },
            {
                "name": YANDEX_TRACKER_ORG_ID,
                "description": (
                    "ID организации Трекера (X-Cloud-Org-ID для Yandex Cloud "
                    "или X-Org-ID для Яндекс 360)."
                ),
                "type": "text",
            },
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent, config, kwargs
        if not has_tracker_creds(user):
            return []
        from giga_agent.modules.yandex_tracker.tools import (
            tracker_add_comment,
            tracker_create_issue,
            tracker_get_issue,
            tracker_search_issues,
            tracker_transition,
            tracker_update_issue,
        )

        # Порядок = приоритет для tool-router (на GigaChat в ход влезает ~3
        # tracker-тула): самые частые операции — впереди.
        return [
            tracker_search_issues,
            tracker_get_issue,
            tracker_create_issue,
            tracker_add_comment,
            tracker_update_issue,
            tracker_transition,
        ]
