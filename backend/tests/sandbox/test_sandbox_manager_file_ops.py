import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.file import FileRepository
from giga_agent.models.resource_permission import ResourcePermissionRepository
from giga_agent.models.sandbox import (
    SandboxProvider,
    SandboxProviderSnapshot,
    SandboxSnapshot,
)
from giga_agent.models.users import User
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.manager import (
    FileAccessError,
    ProviderNotFoundError,
    SandboxManager,
)
from giga_agent.sandbox.manager.types import SandboxResolved


class SandboxManagerFileOpsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self, email: str, *, is_superuser: bool = False) -> User:
        async with self.session_factory() as session:
            user = User(
                email=email,
                hashed_password="hash",
                is_active=True,
                is_superuser=is_superuser,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def _create_provider(
        self, owner_id: uuid.UUID, provider_type: str = "e2b"
    ) -> SandboxProvider:
        async with self.session_factory() as session:
            provider = SandboxProvider(
                owner_id=owner_id,
                type=provider_type,
                settings={
                    "api_key": "test-key",
                    "s3_bucket": "test-bucket",
                    "s3_endpoint": "https://s3.example.local",
                    "s3_region": "ru-central-1",
                    "aws_access_key_id": "ak",
                    "aws_secret_access_key": "sk",
                }
                if provider_type == "e2b"
                else {},
                idle_timeout=300,
                is_active=True,
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)

            user = await session.get(User, owner_id)
            if user is not None and user.sandbox_provider_id is None:
                user.sandbox_provider_id = provider.id
                await session.commit()

            return provider

    async def test_upload_file_for_user_creates_db_record(self):
        user = await self._create_user("m1@example.com")
        provider = await self._create_provider(user.id)
        runtime = types.SimpleNamespace(
            upload_file=AsyncMock(return_value="/bucket/report.txt"),
            requires_running_for_upload=lambda: False,
        )

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock()

            file = await manager.upload_file_for_user(
                user_id=user.id,
                file_name="report.txt",
                content=b"data",
                file_type="text",
            )

            self.assertEqual(file.owner_id, user.id)
            self.assertEqual(file.provider_id, provider.id)
            self.assertEqual(file.sandbox_path, "/bucket/report.txt")
            self.assertEqual(file.original_name, "report.txt")
            self.assertEqual(file.file_type, "text")
            self.assertEqual(file.size, 4)
            runtime.upload_file.assert_awaited_once_with(
                owner_id=user.id,
                file_name="report.txt",
                content=b"data",
            )
            manager._lifecycle.ensure_running_for_user.assert_not_awaited()

    async def test_resolve_provider_raises_when_user_sandbox_provider_not_configured(
        self,
    ):
        user = await self._create_user("m1b@example.com")

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            with self.assertRaisesRegex(
                ProviderNotFoundError,
                "sandbox provider is not configured",
            ):
                await manager._resolve_provider(user_id=user.id, provider_id=None)

    async def test_resolve_provider_uses_user_sandbox_provider_id(self):
        user = await self._create_user("m1c@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            user_in_db = await session.get(User, user.id)
            assert user_in_db is not None
            user_in_db.sandbox_provider_id = provider.id
            await session.commit()

            manager = SandboxManager(session)
            resolved = await manager._resolve_provider(
                user_id=user.id, provider_id=None
            )
            self.assertEqual(resolved.id, provider.id)

    async def test_resolve_provider_allows_local_provider_for_non_admin_user(self):
        user = await self._create_user("m1d@example.com")
        provider = await self._create_provider(user.id, provider_type="local_jupyter")

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            resolved = await manager._resolve_provider(
                user_id=user.id, provider_id=None
            )
            self.assertEqual(resolved.id, provider.id)

    async def test_read_file_for_user_dispatches_to_runtime(self):
        user = await self._create_user("m2@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/bucket/u/r.txt",
                original_name="r.txt",
                file_type="text",
                size=3,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            content = ContentResult(data=b"abc")
            runtime = types.SimpleNamespace(read_file=AsyncMock(return_value=content))
            runtime.requires_running_for_read = lambda path: False
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock()

            fetched, result = await manager.read_file_for_user(
                user_id=user.id,
                file_id=file.id,
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"abc")
            runtime.read_file.assert_awaited_once_with(file.sandbox_path)
            manager._lifecycle.ensure_running_for_user.assert_not_awaited()

    async def test_read_file_for_user_uses_running_sandbox_for_internal_path(self):
        user = await self._create_user("m2b@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/tmp/inside-sandbox.txt",
                original_name="inside-sandbox.txt",
                file_type="text",
                size=3,
            )
            self.assertIsNotNone(file)

            cold_runtime = types.SimpleNamespace(
                requires_running_for_read=lambda path: True,
            )
            content = ContentResult(data=b"abc")
            hot_runtime = types.SimpleNamespace(
                read_file=AsyncMock(return_value=content)
            )

            manager = SandboxManager(session)
            manager._runtime_factory.build = lambda provider, sandbox: cold_runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock(
                return_value=hot_runtime
            )

            fetched, result = await manager.read_file_for_user(
                user_id=user.id,
                file_id=file.id,
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"abc")
            manager._lifecycle.ensure_running_for_user.assert_awaited_once_with(
                user_id=user.id,
                provider_id=provider.id,
            )
            hot_runtime.read_file.assert_awaited_once_with(file.sandbox_path)

    async def test_read_file_for_user_raises_permission_error_for_foreign_owner(self):
        owner = await self._create_user("m3@example.com")
        foreign = await self._create_user("m4@example.com")
        provider = await self._create_provider(owner.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=owner.id,
                provider_id=provider.id,
                sandbox_path="/bucket/u/r.txt",
                original_name="r.txt",
                file_type="text",
                size=3,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            with self.assertRaises(FileAccessError):
                await manager.read_file_for_user(user_id=foreign.id, file_id=file.id)

    async def test_read_file_by_path_for_user_dispatches(self):
        user = await self._create_user("m5@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/bucket/u/by-path.txt",
                original_name="by-path.txt",
                file_type="text",
                size=8,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            content = ContentResult(data=b"by-path")
            manager._files.read_file_for_user = AsyncMock(return_value=(file, content))

            fetched, result = await manager.read_file_by_path_for_user(
                user_id=user.id,
                sandbox_path="/bucket/u/by-path.txt",
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"by-path")
            manager._files.read_file_for_user.assert_awaited_once_with(
                user_id=user.id,
                file_id=file.id,
            )

    async def test_read_file_by_path_for_user_reads_cli_sandbox_directly(self):
        user_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        sandbox_path = "/tmp/cli-output.txt"
        content = ContentResult(data=b"cli-data")
        provider = SandboxProviderSnapshot(
            id=provider_id,
            owner_id=user_id,
            type="local_jupyter",
            name="cli_local_jupyter",
        )
        sandbox = SandboxSnapshot(
            id=sandbox_id,
            owner_id=user_id,
            provider_id=provider_id,
            status="pending",
        )
        runtime = types.SimpleNamespace(read_file=AsyncMock(return_value=content))

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._resolve.get_or_create_for_user = AsyncMock(
                return_value=SandboxResolved(provider=provider, sandbox=sandbox)
            )
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]

            with (
                patch(
                    "giga_agent.sandbox.manager.file_service._is_cli_runtime",
                    return_value=True,
                ),
                patch(
                    "giga_agent.sandbox.manager.file_service.UserRepository.get_cached_or_db",
                    side_effect=AssertionError(
                        "DB user lookup should not run in CLI mode"
                    ),
                ),
            ):
                fetched, result = await manager.read_file_by_path_for_user(
                    user_id=user_id,
                    sandbox_path=sandbox_path,
                )

        self.assertEqual(fetched.owner_id, user_id)
        self.assertEqual(fetched.provider_id, provider_id)
        self.assertEqual(fetched.sandbox_path, sandbox_path)
        self.assertEqual(fetched.original_name, "cli-output.txt")
        self.assertEqual(fetched.file_type, "other")
        self.assertEqual(fetched.size, 0)
        self.assertIs(result, content)
        manager._resolve.get_or_create_for_user.assert_awaited_once_with(
            user_id=user_id,
            provider_id=None,
            use_cache=True,
        )
        runtime.read_file.assert_awaited_once_with(sandbox_path)

    async def test_upload_files_for_user_creates_db_records_in_input_order(self):
        user = await self._create_user("m6@example.com")
        await self._create_provider(user.id)
        runtime = types.SimpleNamespace(
            upload_file=AsyncMock(
                side_effect=[
                    "/bucket/first.png",
                    "/bucket/second.mp3",
                    "/bucket/third.mp4",
                    "/bucket/fourth.plotly.json",
                ]
            ),
            requires_running_for_upload=lambda: False,
        )

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock()

            result = await manager.upload_files_for_user(
                user_id=user.id,
                files=[
                    {
                        "file_name": "thread-1/first.png",
                        "content": b"png",
                        "file_type": "image",
                    },
                    {
                        "file_name": "thread-1/second.mp3",
                        "content": b"mp3",
                        "file_type": "audio",
                    },
                    {
                        "file_name": "thread-1/third.mp4",
                        "content": b"mp4",
                        "file_type": "video",
                    },
                    {
                        "file_name": "thread-1/fourth.plotly.json",
                        "content": b"{}",
                        "file_type": "plotly_graph",
                    },
                ],
            )
            files = result.files

            self.assertEqual(len(files), 4)
            self.assertEqual(result.errors, [])
            self.assertEqual(
                [f.file_type for f in files],
                ["image", "audio", "video", "plotly_graph"],
            )
            self.assertEqual(
                [f.sandbox_path for f in files],
                [
                    "/bucket/first.png",
                    "/bucket/second.mp3",
                    "/bucket/third.mp4",
                    "/bucket/fourth.plotly.json",
                ],
            )
            self.assertEqual(
                [f.original_name for f in files],
                ["first.png", "second.mp3", "third.mp4", "fourth.plotly.json"],
            )
            self.assertEqual([f.size for f in files], [3, 3, 3, 2])
            self.assertEqual(runtime.upload_file.await_count, 4)
            manager._lifecycle.ensure_running_for_user.assert_not_awaited()
            for call in runtime.upload_file.await_args_list:
                self.assertEqual(call.kwargs["owner_id"], user.id)

    async def test_delete_file_for_user_deletes_from_storage_best_effort_and_removes_db_record(
        self,
    ):
        user = await self._create_user("m7@example.com")
        viewer = await self._create_user("m7_viewer@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/bucket/u/to-delete.txt",
                original_name="to-delete.txt",
                file_type="text",
                size=1,
            )
            self.assertIsNotNone(file)
            permissions = ResourcePermissionRepository(session)
            await permissions.grant_permission(
                resource_type="file",
                resource_id=file.id,
                owner_type="user",
                owner_id=viewer.id,
                permission="read",
            )

            runtime = types.SimpleNamespace(
                delete_file=AsyncMock(return_value=None),
                requires_running_for_delete=lambda path: False,
            )

            manager = SandboxManager(session)
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock()

            await manager.delete_file_for_user(user_id=user.id, file_id=file.id)

            runtime.delete_file.assert_awaited_once_with(file.sandbox_path)
            manager._lifecycle.ensure_running_for_user.assert_not_awaited()
            self.assertIsNone(await repo.get_by_id(file.id))
            self.assertEqual(
                await permissions.list_permissions_for_resource(
                    resource_type="file",
                    resource_id=file.id,
                ),
                [],
            )

    async def test_delete_file_for_user_uses_running_sandbox_when_required(self):
        user = await self._create_user("m8@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/tmp/internal.txt",
                original_name="internal.txt",
                file_type="text",
                size=1,
            )
            self.assertIsNotNone(file)

            cold_runtime = types.SimpleNamespace(
                requires_running_for_delete=lambda path: True,
            )
            hot_runtime = types.SimpleNamespace(
                delete_file=AsyncMock(return_value=None)
            )

            manager = SandboxManager(session)
            manager._runtime_factory.build = lambda provider, sandbox: cold_runtime  # type: ignore[method-assign]
            manager._lifecycle.ensure_running_for_user = AsyncMock(
                return_value=hot_runtime
            )

            await manager.delete_file_for_user(user_id=user.id, file_id=file.id)

            manager._lifecycle.ensure_running_for_user.assert_awaited_once_with(
                user_id=user.id,
                provider_id=provider.id,
            )
            hot_runtime.delete_file.assert_awaited_once_with(file.sandbox_path)
            self.assertIsNone(await repo.get_by_id(file.id))

    async def test_path_write_and_exists_resolve_cli_sandbox_directly(self):
        user_id = uuid.uuid4()
        provider_id = uuid.uuid4()
        sandbox_id = uuid.uuid4()
        sandbox_path = "/tmp/cli-output.txt"
        provider = SandboxProviderSnapshot(
            id=provider_id,
            owner_id=user_id,
            type="local_jupyter",
            name="cli_local_jupyter",
        )
        sandbox = SandboxSnapshot(
            id=sandbox_id,
            owner_id=user_id,
            provider_id=provider_id,
            status="pending",
        )
        runtime = types.SimpleNamespace(
            write_file_content=AsyncMock(return_value=None),
            file_exists=AsyncMock(return_value=True),
        )

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._resolve.get_or_create_for_user = AsyncMock(
                return_value=SandboxResolved(provider=provider, sandbox=sandbox)
            )
            manager._runtime_factory.build = lambda provider, sandbox: runtime  # type: ignore[method-assign]

            with (
                patch(
                    "giga_agent.sandbox.manager.file_service._is_cli_runtime",
                    return_value=True,
                ),
                patch(
                    "giga_agent.sandbox.manager.file_service.UserRepository.get_cached_or_db",
                    side_effect=AssertionError(
                        "DB user lookup should not run in CLI mode"
                    ),
                ),
            ):
                await manager.write_file_content_for_user(
                    user_id=user_id,
                    sandbox_path=sandbox_path,
                    content=b"cli-data",
                )
                exists = await manager.file_exists_for_user(
                    user_id=user_id,
                    sandbox_path=sandbox_path,
                )

        self.assertTrue(exists)
        self.assertEqual(manager._resolve.get_or_create_for_user.await_count, 2)
        for awaited in manager._resolve.get_or_create_for_user.await_args_list:
            self.assertEqual(
                awaited.kwargs,
                {
                    "user_id": user_id,
                    "provider_id": None,
                    "use_cache": True,
                },
            )
        runtime.write_file_content.assert_awaited_once_with(sandbox_path, b"cli-data")
        runtime.file_exists.assert_awaited_once_with(sandbox_path)
