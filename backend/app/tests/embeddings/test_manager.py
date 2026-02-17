import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.embeddings.manager import EmbeddingManager


class EmbeddingManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_embedding(self):
        embedding_id = uuid.uuid4()

        with patch(
            "giga_agent.embeddings.manager.EmbeddingRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                await EmbeddingManager.resolve_by_id(embedding_id)

    async def test_resolve_raises_for_inactive_embedding(self):
        embedding_id = uuid.uuid4()
        embedding = types.SimpleNamespace(
            id=embedding_id,
            is_active=False,
            connector_id=uuid.uuid4(),
            type="openai",
            model_id="text-embedding-3-small",
            settings={},
        )

        with patch(
            "giga_agent.embeddings.manager.EmbeddingRepository.get_cached_or_db",
            AsyncMock(return_value=embedding),
        ):
            with self.assertRaisesRegex(ValueError, "inactive"):
                await EmbeddingManager.resolve_by_id(embedding_id)

    async def test_resolve_builds_embeddings(self):
        embedding_id = uuid.uuid4()
        connector_id = uuid.uuid4()
        embedding = types.SimpleNamespace(
            id=embedding_id,
            is_active=True,
            connector_id=connector_id,
            type="openai",
            model_id="text-embedding-3-small",
            settings={"dimensions": 512},
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="openai",
            settings={"api_key": "sk-test"},
        )

        built_embeddings = object()

        class _RuntimeStub:
            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return connector_type == "openai"

            @classmethod
            def build_embeddings_from_kwargs(
                cls,
                *,
                model_id: str,
                connection_kwargs: dict,
                embedding_settings: dict | None = None,
            ):
                if model_id != "text-embedding-3-small":
                    raise AssertionError("unexpected model_id")
                if connection_kwargs != {"api_key": "sk-test"}:
                    raise AssertionError("unexpected kwargs")
                if embedding_settings != {"dimensions": 512}:
                    raise AssertionError("unexpected settings")
                return built_embeddings

        with patch(
            "giga_agent.embeddings.manager.EmbeddingRepository.get_cached_or_db",
            AsyncMock(return_value=embedding),
        ), patch(
            "giga_agent.embeddings.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.embeddings.manager.EmbeddingRegistry.get",
            return_value=_RuntimeStub,
        ), patch(
            "giga_agent.embeddings.manager.ConnectorRegistry.get_connection_kwargs",
            return_value={"api_key": "sk-test"},
        ):
            resolved = await EmbeddingManager.resolve_by_id(embedding_id)

        self.assertIs(resolved, built_embeddings)

    async def test_resolve_raises_when_connector_is_incompatible(self):
        embedding_id = uuid.uuid4()
        connector_id = uuid.uuid4()
        embedding = types.SimpleNamespace(
            id=embedding_id,
            is_active=True,
            connector_id=connector_id,
            type="openai",
            model_id="text-embedding-3-small",
            settings={},
        )
        connector = types.SimpleNamespace(
            id=connector_id,
            is_active=True,
            type="gigachat",
            settings={},
        )

        class _RuntimeStub:
            @classmethod
            def is_connector_supported(cls, connector_type: str) -> bool:
                return False

        with patch(
            "giga_agent.embeddings.manager.EmbeddingRepository.get_cached_or_db",
            AsyncMock(return_value=embedding),
        ), patch(
            "giga_agent.embeddings.manager.ConnectorRepository.get_cached_or_db",
            AsyncMock(return_value=connector),
        ), patch(
            "giga_agent.embeddings.manager.EmbeddingRegistry.get",
            return_value=_RuntimeStub,
        ):
            with self.assertRaisesRegex(ValueError, "not compatible"):
                await EmbeddingManager.resolve_by_id(embedding_id)
