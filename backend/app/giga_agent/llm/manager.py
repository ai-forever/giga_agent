"""Manager for resolving runtime LLM chat models."""

from __future__ import annotations

import uuid

from langchain_core.language_models import BaseChatModel

from giga_agent.connectors.registry import ConnectorRegistry
from giga_agent.llm.registry import LLMRegistry
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.llm import LLMRepository

# Ensure runtimes are registered.
import giga_agent.connectors  # noqa: F401
import giga_agent.llm  # noqa: F401


class LLMManager:
    @staticmethod
    async def resolve_by_id(llm_id: uuid.UUID) -> BaseChatModel:
        llm = await LLMRepository.get_cached_or_db(llm_id, use_cache=True)
        if llm is None:
            raise ValueError(f"LLM with id {llm_id} not found")
        if not llm.is_active:
            raise ValueError(f"LLM with id {llm_id} is inactive")

        connector = await ConnectorRepository.get_cached_or_db(
            llm.connector_id,
            use_cache=True,
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

        kwargs = ConnectorRegistry.get_connection_kwargs(
            connector.type,
            connector.settings or {},
        )
        if kwargs is None:
            raise ValueError(f"Invalid connection settings for connector {connector.id}")

        return runtime_cls.build_chat_model_from_kwargs(
            model_id=llm.model_id,
            connection_kwargs=kwargs,
            llm_settings=llm.settings or {},
        )
