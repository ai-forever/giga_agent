"""API router for model metadata (context windows, pricing)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

router = APIRouter(prefix="/models-config", tags=["models-config"])

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "models_config.json"
_cached_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _cached_config
    if _cached_config is None:
        if _CONFIG_PATH.is_file():
            _cached_config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        else:
            _cached_config = {"models": {}}
    return _cached_config


@router.get("", response_model=dict[str, Any])
async def get_models_config(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
) -> dict[str, Any]:
    _ = current_user
    return _load_config()
