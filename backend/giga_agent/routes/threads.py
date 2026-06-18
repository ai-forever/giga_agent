"""Compact, deduplicated thread history for lightweight branch navigation.

The frontend opens threads with ``fetchStateHistory: false`` to avoid downloading
the langgraph ``/threads/{id}/history`` payload, which repeats every message's
full content inside every checkpoint's ``values`` (O(checkpoints × messages)).

This endpoint fetches that full history server-to-server via the langgraph SDK
client (so the heavy transfer stays on the internal network) and returns a
deduplicated, compact representation: each unique message serialized once, plus
the checkpoint lineage with per-state message-id lists. The browser rebuilds the
branch DAG and rehydrates per-branch messages from that, keeping payload at
roughly (unique messages once) + (lineage).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session
from giga_agent.core.logging import get_logger
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import (
    AUTH_COOKIE_NAME,
    get_current_active_user,
    oauth2_scheme,
)
from giga_agent.services.prompt_suggestions import (
    get_follow_up_suggestions,
    get_starter_suggestions,
)
from giga_agent.utils.langgraph_sdk import get_client as get_langgraph_client
from giga_agent.utils.thread_metadata import update_thread_metadata

logger = get_logger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"])

# Hard ceiling on how many checkpoints /history/compact materializes at once.
# langgraph's get_history embeds the FULL message snapshot in every checkpoint's
# `values` (O(checkpoints × messages)); a pathological thread (e.g. a runaway
# tool loop with thousands of checkpoints, ~1MB each) can OOM the process. The
# incoming `limit` is clamped to this value; clients paginate via `before`.
MAX_COMPACT_HISTORY_LIMIT = 50


class CompactState(BaseModel):
    """One checkpoint, stripped of message bodies (referenced by id instead)."""

    checkpoint: dict[str, Any] | None = None
    parent_checkpoint: dict[str, Any] | None = None
    created_at: str | None = None
    next: list[str] = []
    message_ids: list[str] = []


class CompactHistoryResponse(BaseModel):
    messages: dict[str, Any]
    states: list[CompactState]
    has_forks: bool


class ThreadAutoApproveRequest(BaseModel):
    auto_approve: bool


class ThreadAutoApproveResponse(BaseModel):
    auto_approve: bool


class PromptSuggestionsResponse(BaseModel):
    suggestions: list[str]
    cached: bool = False
    based_on_pairs: int = 0
    source_thread_count: int = 0


def _langgraph_config(token: str) -> dict[str, Any]:
    return {"configurable": {"langgraph_auth_user": {"token": token}}}


def _bearer_token(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> str | None:
    """The caller's raw access token (Authorization header or auth cookie)."""
    raw = token or request.cookies.get(AUTH_COOKIE_NAME)
    if raw and raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw


@router.get("/{thread_id}/history/compact", response_model=CompactHistoryResponse)
async def get_thread_history_compact(
    thread_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
    limit: int = MAX_COMPACT_HISTORY_LIMIT,
    before: str | None = None,
) -> CompactHistoryResponse:
    """Compact, deduplicated history so the FE can rebuild the branch tree cheaply."""
    _ = current_user  # ownership is enforced downstream via the forwarded token

    # Clamp to the ceiling so a client can't request a payload large enough to
    # OOM the process; pagination still works via `before`.
    limit = max(1, min(limit, MAX_COMPACT_HISTORY_LIMIT))

    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
        )

    langgraph_config = {
        "configurable": {
            "langgraph_auth_user": {
                "token": token,
            },
        },
    }
    try:
        states = await get_langgraph_client(langgraph_config).threads.get_history(
            thread_id, limit=limit, before=before
        )
    except Exception as exc:
        logger.warning(
            "compact_history_fetch_failed", thread_id=thread_id, error=str(exc)
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to fetch thread history"
        ) from exc

    messages: dict[str, Any] = {}
    out_states: list[CompactState] = []
    children: dict[str, int] = {}
    for st in states:
        values = st.get("values") or {}
        ids: list[str] = []
        for m in values.get("messages") or []:
            mid = m.get("id") if isinstance(m, dict) else None
            if not mid:
                # id-less messages can't be deduped/branch-mapped; FE appends as-is.
                logger.debug("compact_history_message_without_id", thread_id=thread_id)
                continue
            ids.append(mid)
            messages.setdefault(mid, m)

        parent = st.get("parent_checkpoint")
        parent_id = (parent or {}).get("checkpoint_id") or "$"
        children[parent_id] = children.get(parent_id, 0) + 1

        out_states.append(
            CompactState(
                checkpoint=st.get("checkpoint"),
                parent_checkpoint=parent,
                created_at=st.get("created_at"),
                next=list(st.get("next") or []),
                message_ids=ids,
            )
        )

    has_forks = any(count > 1 for count in children.values())
    return CompactHistoryResponse(
        messages=messages, states=out_states, has_forks=has_forks
    )


@router.put("/{thread_id}/auto-approve", response_model=ThreadAutoApproveResponse)
async def set_thread_auto_approve(
    thread_id: str,
    body: ThreadAutoApproveRequest,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
) -> ThreadAutoApproveResponse:
    """Persist the autonomy (``auto_approve``) flag in thread metadata.

    Writes through :func:`update_thread_metadata`, which both updates the
    langgraph thread metadata (via the forwarded token) and refreshes the
    ``thread_metadata`` cache the run middlewares read from — so a toggle is
    honored even mid-run, without piggybacking on the next ``submit``.
    """
    _ = current_user  # ownership is enforced downstream via the forwarded token

    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
        )

    try:
        await update_thread_metadata(
            _langgraph_config(token),
            thread_id,
            {"auto_approve": bool(body.auto_approve)},
        )
    except Exception as exc:
        logger.warning(
            "thread_auto_approve_update_failed", thread_id=thread_id, error=str(exc)
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to update thread metadata"
        ) from exc

    return ThreadAutoApproveResponse(auto_approve=bool(body.auto_approve))


@router.get("/starter-suggestions", response_model=PromptSuggestionsResponse)
async def get_starter_prompt_suggestions(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
    db: Annotated[AsyncSession, Depends(get_session)],
    count: int = 5,
    limit_threads: int = 5,
    refresh: bool = False,
) -> PromptSuggestionsResponse:
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
        )

    try:
        result = await get_starter_suggestions(
            token=token,
            user=current_user,
            db=db,
            count=count,
            limit_threads=limit_threads,
            refresh=refresh,
        )
    except Exception as exc:
        logger.warning("starter_suggestions_failed", error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to generate starter suggestions"
        ) from exc

    return PromptSuggestionsResponse(
        suggestions=result.suggestions,
        cached=result.cached,
        based_on_pairs=result.based_on_pairs,
        source_thread_count=result.source_thread_count,
    )


@router.get(
    "/{thread_id}/follow-up-suggestions", response_model=PromptSuggestionsResponse
)
async def get_follow_up_prompt_suggestions(
    thread_id: str,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    token: Annotated[str | None, Depends(_bearer_token)],
    db: Annotated[AsyncSession, Depends(get_session)],
    pairs: int = 5,
    count: int = 3,
    refresh: bool = False,
) -> PromptSuggestionsResponse:
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
        )

    try:
        result = await get_follow_up_suggestions(
            token=token,
            thread_id=thread_id,
            user=current_user,
            db=db,
            count=count,
            pairs_limit=pairs,
            refresh=refresh,
        )
    except Exception as exc:
        logger.warning(
            "follow_up_suggestions_failed", thread_id=thread_id, error=str(exc)
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to generate follow-up suggestions"
        ) from exc

    return PromptSuggestionsResponse(
        suggestions=result.suggestions,
        cached=result.cached,
        based_on_pairs=result.based_on_pairs,
        source_thread_count=result.source_thread_count,
    )
