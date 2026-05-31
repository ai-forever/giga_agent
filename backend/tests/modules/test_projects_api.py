import types
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base, get_session
from giga_agent.models.rag import RagCollection, RagCollectionsRepository
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.projects.api import router


class ProjectsAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.app = FastAPI()
        self.app.include_router(router, prefix="/projects")

        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            async with self.session_factory() as session:
                yield session

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _switch_user(self) -> None:
        new_user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)

        async def _override_current_user():
            return new_user

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.user = new_user

    def test_list_empty(self):
        resp = self.client.get("/projects/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_create_and_get(self):
        resp = self.client.post(
            "/projects/",
            json={
                "name": "alpha",
                "description": "first project",
                "instructions": "be concise",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "alpha")
        self.assertEqual(data["description"], "first project")
        self.assertEqual(data["instructions"], "be concise")
        self.assertEqual(data["owner_id"], str(self.user.id))
        project_id = data["id"]

        resp = self.client.get(f"/projects/{project_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], project_id)

    def test_create_duplicate_name_returns_409(self):
        self.client.post("/projects/", json={"name": "dup"})
        resp = self.client.post("/projects/", json={"name": "dup"})
        self.assertEqual(resp.status_code, 409)

    def test_update_changes_fields(self):
        created = self.client.post(
            "/projects/", json={"name": "p1", "instructions": "old"}
        ).json()
        resp = self.client.patch(
            f"/projects/{created['id']}",
            json={"instructions": "new", "description": "desc"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["instructions"], "new")
        self.assertEqual(data["description"], "desc")
        self.assertEqual(data["name"], "p1")

    def test_delete_removes_project(self):
        created = self.client.post("/projects/", json={"name": "del"}).json()
        resp = self.client.delete(f"/projects/{created['id']}")
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/projects/{created['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_owner_isolation(self):
        owner_a = self.client.post("/projects/", json={"name": "a-proj"}).json()
        self._switch_user()
        resp = self.client.get("/projects/")
        self.assertEqual(resp.json(), [])
        resp = self.client.get(f"/projects/{owner_a['id']}")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.patch(
            f"/projects/{owner_a['id']}", json={"name": "hijacked"}
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete(f"/projects/{owner_a['id']}")
        self.assertEqual(resp.status_code, 404)

    def test_get_unknown_returns_404(self):
        resp = self.client.get(f"/projects/{uuid.uuid4()}")
        self.assertEqual(resp.status_code, 404)


class ProjectsAPIWithCollectionTests(unittest.IsolatedAsyncioTestCase):
    """Verifies project create/delete also handles a backing RAG collection."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.app = FastAPI()
        self.app.include_router(router, prefix="/projects")

        self.embedding_id = uuid.uuid4()
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(), is_active=True, embedding_id=self.embedding_id
        )

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            async with self.session_factory() as session:
                yield session

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

        async def fake_create(*, user, db, name, metadata=None):
            repo = RagCollectionsRepository(db)
            return await repo.create(
                owner_id=user.id,
                name=name,
                embedding_id=user.embedding_id,
                metadata=metadata,
            )

        self._patcher = patch(
            "giga_agent.modules.rag.api.collections.create_collection_for_user",
            new=fake_create,
        )
        self._patcher.start()

    async def asyncTearDown(self) -> None:
        self._patcher.stop()
        await self.engine.dispose()

    async def _count_collections(self) -> int:
        from sqlalchemy import select

        async with self.session_factory() as session:
            result = await session.execute(select(RagCollection))
            return len(list(result.scalars().all()))

    async def test_create_project_creates_backing_collection(self):
        resp = self.client.post("/projects/", json={"name": "with-kb"})
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIsNotNone(data["collection_id"])

        async with self.session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(select(RagCollection))
            collections = list(result.scalars().all())
            self.assertEqual(len(collections), 1)
            self.assertEqual(
                collections[0].metadata_.get("project_id"), data["id"]
            )
            self.assertEqual(str(collections[0].id), data["collection_id"])

    async def test_delete_project_cascades_collection(self):
        created = self.client.post(
            "/projects/", json={"name": "del-with-kb"}
        ).json()
        self.assertEqual(await self._count_collections(), 1)

        resp = self.client.delete(f"/projects/{created['id']}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(await self._count_collections(), 0)

    async def test_user_without_embedding_creates_project_without_collection(self):
        self.user.embedding_id = None
        resp = self.client.post("/projects/", json={"name": "no-kb"})
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["collection_id"])
        self.assertEqual(await self._count_collections(), 0)

    async def test_get_lazily_creates_collection_for_legacy_project(self):
        # Project created when embedding was missing → no backing collection.
        self.user.embedding_id = None
        created = self.client.post("/projects/", json={"name": "legacy"}).json()
        self.assertIsNone(created["collection_id"])
        self.assertEqual(await self._count_collections(), 0)

        # User configures embedding later; opening the project should now
        # bring a collection into existence.
        self.user.embedding_id = self.embedding_id
        resp = self.client.get(f"/projects/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNotNone(data["collection_id"])
        self.assertEqual(await self._count_collections(), 1)

        # Idempotent — second GET doesn't create a duplicate.
        self.client.get(f"/projects/{created['id']}")
        self.assertEqual(await self._count_collections(), 1)
