import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.connector import ConnectorRepository
from giga_agent.models.group import GroupRepository
from giga_agent.models.image_generator import ImageGeneratorRepository
from giga_agent.models.llm import LLMRepository
from giga_agent.models.sandbox import SandboxProviderRepository
from giga_agent.models.search_engine import SearchEngineRepository
from giga_agent.models.users import User, UserRepository


class NullableUpdateContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(
                email=email,
                hashed_password="hash",
                first_name="First",
                last_name="Last",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_connector_repository_update_can_clear_name(self):
        user = await self._create_user("connector-null@example.com")

        async with self.session_factory() as session:
            repo = ConnectorRepository(session)
            connector = await repo.create(
                owner_id=user.id,
                connector_type="openai",
                name="main",
                settings={"api_key": "sk-test"},
            )

            updated = await repo.update(connector, name=None)

        self.assertIsNone(updated.name)

    async def test_llm_repository_update_can_clear_name(self):
        user = await self._create_user("llm-null@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
            )
            repo = LLMRepository(session)
            llm = await repo.create(
                owner_id=user.id,
                llm_type="openai",
                connector_id=connector.id,
                model_id="gpt-4o-mini",
                name="main",
                settings={},
            )

            updated = await repo.update(llm, name=None)

        self.assertIsNone(updated.name)

    async def test_search_engine_repository_update_can_clear_nullable_fields(self):
        user = await self._create_user("search-null@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
            )
            repo = SearchEngineRepository(session)
            engine = await repo.create(
                owner_id=user.id,
                engine_type="tavily",
                name="search",
                settings={"api_key": "tvly-key"},
                connector_id=connector.id,
            )

            updated = await repo.update(engine, name=None, connector_id=None)

        self.assertIsNone(updated.name)
        self.assertIsNone(updated.connector_id)

    async def test_image_generator_repository_update_can_clear_nullable_fields(self):
        user = await self._create_user("image-null@example.com")

        async with self.session_factory() as session:
            connector = await ConnectorRepository(session).create(
                owner_id=user.id,
                connector_type="openai",
                settings={"api_key": "sk-test"},
            )
            repo = ImageGeneratorRepository(session)
            generator = await repo.create(
                owner_id=user.id,
                generator_type="openai",
                name="image",
                settings={"model": "gpt-image-1"},
                connector_id=connector.id,
            )

            updated = await repo.update(generator, name=None, connector_id=None)

        self.assertIsNone(updated.name)
        self.assertIsNone(updated.connector_id)

    async def test_group_repository_update_can_clear_nullable_fields(self):
        owner = await self._create_user("group-null@example.com")

        async with self.session_factory() as session:
            repo = GroupRepository(session)
            group = await repo.create(
                owner_id=owner.id,
                name="admins",
                description="desc",
                data={"scope": "all"},
                permissions={"role": "admin"},
            )

            updated = await repo.update(
                group,
                description=None,
                data=None,
                permissions=None,
            )

        self.assertIsNone(updated.description)
        self.assertIsNone(updated.data)
        self.assertIsNone(updated.permissions)

    async def test_sandbox_provider_repository_update_can_clear_name(self):
        owner = await self._create_user("sandbox-null@example.com")

        async with self.session_factory() as session:
            repo = SandboxProviderRepository(session)
            provider = await repo.create(
                owner_id=owner.id,
                provider_type="e2b",
                name="main",
                settings={},
            )

            updated = await repo.update(provider, name=None)

        self.assertIsNone(updated.name)

    async def test_user_repository_update_can_clear_names(self):
        user = await self._create_user("user-null@example.com")

        async with self.session_factory() as session:
            repo = UserRepository(session)
            user_model = await repo._get_model_by_id(user.id)
            assert user_model is not None

            updated = await repo.update(user_model, first_name=None, last_name=None)

        self.assertIsNone(updated.first_name)
        self.assertIsNone(updated.last_name)
