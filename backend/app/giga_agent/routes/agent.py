"""API router for agent runtime metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from giga_agent.core.deps import get_agent
from giga_agent.core.module import SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.auth.api import get_current_active_user

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent

router = APIRouter(prefix="/agent", tags=["agent"])


class SecretMetadataResponse(BaseModel):
    name: str
    description: str | None = None


@router.get("/secrets", response_model=list[SecretMetadataResponse])
async def get_agent_secrets(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    agent: Annotated["BaseAgent", Depends(get_agent)],
) -> list[SecretMetadata]:
    _ = current_user

    secrets: list[SecretMetadata] = []
    seen_names: set[str] = set()

    for module in agent.modules:
        for secret in module.get_secrets():
            name = secret["name"]
            if name in seen_names:
                continue
            seen_names.add(name)
            secrets.append(secret)

    return secrets
