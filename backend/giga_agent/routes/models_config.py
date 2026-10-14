"""API router for model metadata (context windows, pricing)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from giga_agent.models.users import UserShort
from giga_agent.model_metadata import get_models_config as load_models_config
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(prefix="/models-config", tags=["models-config"])


@router.get("", response_model=dict[str, Any])
async def get_models_config(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    _ = current_user
    return load_models_config()
