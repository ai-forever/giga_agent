"""REST демо-трекера — тот же контракт, что у Яндекс.Трекера
(`/{module_id}/issues/{key}/transitions`). StatusBadge на фронте строит эти
URL из provider и работает с моком без единой правки. Данные — в памяти.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.mock_tracker import data

router = APIRouter(tags=["mock_tracker"])


@router.get("/issues/{issue_key}/transitions")
async def list_transitions(
    issue_key: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    _ = current_user
    return {"transitions": data.transitions_for(issue_key)}


@router.post("/issues/{issue_key}/transitions/{transition_id}")
async def execute_transition(
    issue_key: str,
    transition_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    _ = current_user
    issue = data.apply_transition(issue_key, transition_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Переход не найден")
    return {"status": "transitioned", "issue": issue}
