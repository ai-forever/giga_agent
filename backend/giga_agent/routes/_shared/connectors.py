from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from giga_agent.models.connector import ConnectorRepository


async def validate_connector_link(
    *,
    user_id: uuid.UUID,
    connector_id: uuid.UUID | None,
    supported_connector_types: list[str],
    connector_repo: ConnectorRepository,
    resource_label: str,
    require_owner: bool = True,
    require_when_supported: bool = False,
) -> uuid.UUID | None:
    normalized_supported = [
        connector_type.lower() for connector_type in supported_connector_types
    ]

    if not normalized_supported:
        if connector_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"This {resource_label} type does not support connector_id.",
            )
        return None

    if connector_id is None:
        if require_when_supported:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"connector_id is required for this {resource_label} type. "
                    f"Supported connector types: {normalized_supported}"
                ),
            )
        return None

    connector_row = await connector_repo.get_by_id_with_access_for_user(
        connector_id,
        user_id=user_id,
    )
    if connector_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    connector, can_read, _ = connector_row

    if require_owner and connector.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if not require_owner and not can_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if not connector.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector must be active",
        )

    connector_type = (connector.type or "").lower()
    if connector_type not in normalized_supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Connector type '{connector_type}' is not supported by this "
                f"{resource_label}. Supported: {normalized_supported}"
            ),
        )
    return connector_id
