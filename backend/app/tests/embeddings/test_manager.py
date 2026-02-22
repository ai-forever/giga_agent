import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.embeddings.base import BaseEmbeddingRuntime
from giga_agent.models.connector import ConnectorResponse


class EmbeddingManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_raises_for_missing_embedding(self):
        embedding_id = uuid.uuid4()
        session = object()

        with patch(
            "giga_agent.embeddings.manager.EmbeddingRepository.get_cached_or_db",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                await EmbeddingManager.resolve_by_id(embedding_id, session=session)

    async def test_resolve_raises_for_inactive_embedding(self):
        embedding_id = uuid.uuid4()
        session = object()
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
                await EmbeddingManager.resolve_by_id(embedding_id, session=session)

    async def test_resolve_builds_embeddings(self):
        embedding_id = uuid.uuid4()
        session = object()
        connector_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        embedding = types.SimpleNamespace(
            id=embedding_id,
            is_active=True,
            connector_id=connector_id,
            type="openai",
            model_id="text-embedding-3-small",
            vector_size=512,
            settings={"dimensions": 512},
        )

        connector = ConnectorResponse(
            id=connector_id,
            owner_id=owner_id,
            is_active=True,
            type="openai",
            name=None,
            settings={"api_key": "sk-test"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        built_embeddings = types.SimpleNamespace()

        class _RuntimeStub(BaseEmbeddingRuntime):
            dimensions: int | None = None

            @classmethod
            def supported_connector_types(cls) -> list[str]:
                return ["openai"]

            def _embeddings(self):
                if self.model_id != "text-embedding-3-small":
                    raise AssertionError("unexpected model_id")
                if self.connector.settings != {"api_key": "sk-test"}:
                    raise AssertionError("unexpected kwargs")
                if self._settings_payload() != {"dimensions": 512}:
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
            resolved = await EmbeddingManager.resolve_by_id(
                embedding_id,
                session=session,
            )
            self.assertIsInstance(resolved, _RuntimeStub)
            self.assertEqual(resolved.vector_size, 512)
            self.assertEqual(resolved.connector.id, connector_id)

            client = resolved.embeddings
            self.assertIs(client, built_embeddings)

    async def test_resolve_raises_when_connector_is_incompatible(self):
        embedding_id = uuid.uuid4()
        session = object()
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
                await EmbeddingManager.resolve_by_id(embedding_id, session=session)
