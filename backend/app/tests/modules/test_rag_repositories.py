import unittest
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.connector import Connector
from giga_agent.models.embedding import Embedding
from giga_agent.models.users import User
from giga_agent.modules.rag.database.repositories import (
    RagCollectionsRepository,
    RagDocumentsRepository,
)

# Ensure module tables are registered in Base.metadata
import giga_agent.modules.rag.models  # noqa: F401


class RagRepositoriesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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

