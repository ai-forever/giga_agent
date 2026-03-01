from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException, status
from pydantic import ValidationError

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.models.connector import Connector


async def validate_connector_settings_or_422(
    connector_type: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    if not ConnectorRegistry.is_registered(connector_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown connector type: '{connector_type}'. "
                f"Available: {ConnectorRegistry.available_types()}"
            ),
        )

    try:
        return await ConnectorRegistry.validate_settings(connector_type, settings)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


async def fetch_models_or_http_error(
    *,
    runtime_cls: type,
    connector_type: str,
    connector_settings: dict[str, Any],
    fetch_error_type: type[Exception],
    failure_message_builder: Callable[[Exception], str],
    connector_runtime_error_message: str | None = None,
    get_runtime: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
) -> list[Any]:
    runtime_getter = get_runtime or ConnectorRegistry.get_runtime
    connector_runtime: Any

    if connector_runtime_error_message is not None:
        try:
            connector_runtime = await runtime_getter(
                connector_type,
                connector_settings,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=connector_runtime_error_message,
            ) from e
    else:
        connector_runtime = await runtime_getter(
            connector_type,
            connector_settings,
        )

    try:
        return await runtime_cls.fetch_available_models(
            connector=connector_runtime,
        )
    except fetch_error_type as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=failure_message_builder(e),
        )


async def fetch_models_from_connector_or_http_error(
    *,
    runtime_cls: type,
    connector: Connector,
    fetch_error_type: type[Exception],
    failure_message_builder: Callable[[Exception], str],
    connector_runtime_error_message: str | None = None,
    get_runtime: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
) -> list[Any]:
    return await fetch_models_or_http_error(
        runtime_cls=runtime_cls,
        connector_type=connector.type,
        connector_settings=connector.settings or {},
        fetch_error_type=fetch_error_type,
        failure_message_builder=failure_message_builder,
        connector_runtime_error_message=connector_runtime_error_message,
        get_runtime=get_runtime,
    )
