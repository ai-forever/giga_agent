import unittest
import uuid

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.connector import Connector
from giga_agent.models.embedding import Embedding
from giga_agent.models.file import File
from giga_agent.models.rag import (
    RagCollectionsRepository,
    RagDocument,
    RagDocumentsRepository,
)
from giga_agent.models.sandbox import SandboxProvider
from giga_agent.models.users import User

# Ensure module tables are registered in Base.metadata
import giga_agent.models.rag  # noqa: F401


class RagRepositoriesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        event.listen(
            self.engine.sync_engine,
            "connect",
            lambda dbapi_connection, connection_record: dbapi_connection.execute(
                "PRAGMA foreign_keys=ON"
            ),
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self) -> User:
        async with self.session_factory() as session:
            user = User(
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="hash",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def _create_embedding(self, owner_id: uuid.UUID) -> Embedding:
        async with self.session_factory() as session:
            connector = Connector(owner_id=owner_id, type="openai", settings={}, is_active=True)
            session.add(connector)
            await session.commit()
            await session.refresh(connector)

            embedding = Embedding(
                owner_id=owner_id,
                connector_id=connector.id,
                type="openai",
                model_id="text-embedding-3-small",
                vector_size=1536,
                settings={},
                is_active=True,
            )
            session.add(embedding)
            await session.commit()
            await session.refresh(embedding)
            return embedding

    async def test_collection_and_document_crud(self) -> None:
        user = await self._create_user()
        embedding = await self._create_embedding(user.id)

        async with self.session_factory() as session:
            col_repo = RagCollectionsRepository(session)
            created = await col_repo.create(
                owner_id=user.id,
                name="страховые документы",
                embedding_id=embedding.id,
                metadata={"description": "test"},
            )
            self.assertEqual(created.owner_id, user.id)
            self.assertEqual(created.metadata_.get("description"), "test")

            fetched = await col_repo.get_by_id(owner_id=user.id, collection_id=created.id)
            self.assertIsNotNone(fetched)

            updated = await col_repo.update(
                owner_id=user.id,
                collection_id=created.id,
                name="insurance",
                metadata={"description": "upd"},
            )
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.name, "insurance")

            doc_repo = RagDocumentsRepository(session)
            doc_id = uuid.uuid4()
            created_doc = await doc_repo.create(
                owner_id=user.id,
                collection_id=created.id,
                document_id=doc_id,
                original_name="policy.txt",
                sandbox_path="rag/x/y.txt",
            )
            self.assertEqual(created_doc.id, doc_id)

            docs = await doc_repo.list_by_collection(
                owner_id=user.id,
                collection_id=created.id,
                limit=10,
                offset=0,
            )
            self.assertEqual(len(docs), 1)

            ok = await doc_repo.delete(
                owner_id=user.id,
                collection_id=created.id,
                document_id=doc_id,
            )
            self.assertTrue(ok)

    async def test_document_file_fk_on_delete_sets_null(self) -> None:
        user = await self._create_user()
        embedding = await self._create_embedding(user.id)

        async with self.session_factory() as session:
            provider = SandboxProvider(
                owner_id=user.id,
                type="e2b",
                settings={},
                idle_timeout=300,
                is_active=True,
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)

            file = File(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/bucket/u/doc.txt",
                original_name="doc.txt",
                file_type="text",
                size=10,
            )
            session.add(file)
            await session.commit()
            await session.refresh(file)

            collection = await RagCollectionsRepository(session).create(
                owner_id=user.id,
                name="docs-fk",
                embedding_id=embedding.id,
                metadata={},
            )
            await RagDocumentsRepository(session).create(
                owner_id=user.id,
                collection_id=collection.id,
                document_id=uuid.uuid4(),
                original_name="doc.txt",
                file_id=file.id,
                sandbox_provider_id=provider.id,
                sandbox_path=file.sandbox_path,
            )

            await session.delete(file)
            await session.commit()

            docs = await RagDocumentsRepository(session).list_by_collection(
                owner_id=user.id,
                collection_id=collection.id,
                limit=10,
                offset=0,
            )
            self.assertEqual(len(docs), 1)
            self.assertIsNone(docs[0].file_id)

    async def test_document_provider_fk_on_delete_sets_null(self) -> None:
        user = await self._create_user()
        embedding = await self._create_embedding(user.id)

        async with self.session_factory() as session:
            provider = SandboxProvider(
                owner_id=user.id,
                type="e2b",
                settings={},
                idle_timeout=300,
                is_active=True,
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)

            collection = await RagCollectionsRepository(session).create(
                owner_id=user.id,
                name="docs-provider-fk",
                embedding_id=embedding.id,
                metadata={},
            )
            doc = RagDocument(
                id=uuid.uuid4(),
                owner_id=user.id,
                collection_id=collection.id,
                original_name="doc.txt",
                sandbox_provider_id=provider.id,
                sandbox_path="/bucket/u/doc.txt",
            )
            session.add(doc)
            await session.commit()

            await session.delete(provider)
            await session.commit()
            await session.refresh(doc)
            self.assertIsNone(doc.sandbox_provider_id)
