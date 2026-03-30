import inspect
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models import UserShort
from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.mem_zero_memory.memory import (
    MemZeroEmbeddingsNotConfigured,
    get_memory_for_user,
)

router = APIRouter(tags=["mem0"])


def _require_embeddings(user: UserShort) -> None:
    if user.embedding_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Embeddings model is not configured for this user. "
                "Set `embedding_id` for the user to enable long-term memory."
            ),
        )


def _memory_sort_key(memory_item: dict[str, Any]) -> tuple[int, str]:
    timestamp = memory_item.get("created_at") or memory_item.get("updated_at")
    if isinstance(timestamp, datetime):
        return 1, timestamp.isoformat()
    if isinstance(timestamp, str):
        return 1, timestamp
    return 0, ""


@router.get("/memories")
async def get_memories(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    _require_embeddings(current_user)
    try:
        memory = await get_memory_for_user(user=current_user, session=db)
    except MemZeroEmbeddingsNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    memories = await memory.get_all(user_id=str(current_user.id))
    results = memories.get("results", [])
    if inspect.iscoroutine(results):
        results = await results
    if not isinstance(results, list):
        results = []
    sorted_results = sorted(
        (item for item in results if isinstance(item, dict)),
        key=_memory_sort_key,
        reverse=True,
    )
    return {"results": sorted_results}


@router.delete("/memories")
async def delete_all_memories(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    _require_embeddings(current_user)
    try:
        memory = await get_memory_for_user(user=current_user, session=db)
    except MemZeroEmbeddingsNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return await memory.delete_all(user_id=str(current_user.id))


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    _require_embeddings(current_user)
    try:
        memory = await get_memory_for_user(user=current_user, session=db)
    except MemZeroEmbeddingsNotConfigured as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    try:
        mem = await memory.get(memory_id=memory_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )

    if str(mem.get("user_id")) != str(current_user.id):
        # Avoid leaking existence of a memory_id.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )

    return await memory.delete(memory_id=memory_id)
