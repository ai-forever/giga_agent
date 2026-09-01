"""Manager for resolving runtime LLM chat models."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.llm.base import BaseLLMRuntime
from giga_agent.llm.registry import LLMRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.llm import LLMRepository

# Ensure runtimes are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401


class LLMManager:
    @staticmethod
    async def resolve_by_id(
        llm_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> BaseLLMRuntime:
        llm = await LLMRepository.get_cached_or_db(llm_id, session=session)
        if llm is None:
            raise ValueError(f"LLM with id {llm_id} not found")
        if not llm.is_active:
            raise ValueError(f"LLM with id {llm_id} is inactive")

        connector = await ConnectorRepository.get_cached_or_db(
            llm.connector_id,
            session=session,
        )
        if connector is None:
            raise ValueError(f"Connector for LLM {llm_id} not found")
        if not connector.is_active:
            raise ValueError(f"Connector {connector.id} is inactive.")

        runtime_cls = LLMRegistry.get(llm.type)
        if not runtime_cls.is_connector_supported(connector.type):
            raise ValueError(
                f"LLM type '{llm.type}' is not compatible with connector type '{connector.type}'"
            )

        connector_runtime = await ConnectorRegistry.get_runtime(
            connector.type,
            connector.settings or {},
        )

        validated_settings = await runtime_cls.validate_settings(llm.settings or {})
        return runtime_cls(
            connector=connector_runtime,
            model_id=llm.model_id,
            context_window=llm.context_window,
            **validated_settings,
        )
