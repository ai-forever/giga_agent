import types
import unittest
import uuid
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.db import Base
from giga_agent.models.file import FileRepository
from giga_agent.models.sandbox import SandboxProvider
from giga_agent.models.users import User
from giga_agent.sandbox.base import ContentResult
from giga_agent.sandbox.manager import SandboxManager


class SandboxManagerFileOpsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
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
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def _create_provider(self, owner_id: uuid.UUID, provider_type: str = "e2b") -> SandboxProvider:
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
                } if provider_type == "e2b" else {},
                idle_timeout=300,
                is_active=True,
            )
            session.add(provider)
            await session.commit()
            await session.refresh(provider)
            return provider

    async def test_upload_file_for_user_creates_db_record(self):
        user = await self._create_user("m1@example.com")
        provider = await self._create_provider(user.id)
        runtime = types.SimpleNamespace(
            upload_file=AsyncMock(return_value="/home/user/bucket/giga_agent/test/report.txt"),
            requires_running_for_upload=lambda: False,
        )

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._build_runtime = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager.ensure_running_for_user = AsyncMock()

            file = await manager.upload_file_for_user(
                owner_id=user.id,
                file_name="report.txt",
                content=b"data",
                file_type="text",
            )

            self.assertEqual(file.owner_id, user.id)
            self.assertEqual(file.provider_id, provider.id)
            self.assertEqual(file.sandbox_path, "/home/user/bucket/giga_agent/test/report.txt")
            self.assertEqual(file.original_name, "report.txt")
            self.assertEqual(file.file_type, "text")
            self.assertEqual(file.size, 4)
            runtime.upload_file.assert_awaited_once_with(
                owner_id=user.id,
                file_name="report.txt",
                content=b"data",
            )
            manager.ensure_running_for_user.assert_not_awaited()

    async def test_read_file_for_user_dispatches_to_runtime(self):
        user = await self._create_user("m2@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/home/user/bucket/giga_agent/u/r.txt",
                original_name="r.txt",
                file_type="text",
                size=3,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            content = ContentResult(data=b"abc")
            runtime = types.SimpleNamespace(read_file=AsyncMock(return_value=content))
            runtime.requires_running_for_read = lambda path: False
            manager._build_runtime = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager.ensure_running_for_user = AsyncMock()

            fetched, result = await manager.read_file_for_user(
                owner_id=user.id,
                file_id=file.id,
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"abc")
            runtime.read_file.assert_awaited_once_with(file.sandbox_path)
            manager.ensure_running_for_user.assert_not_awaited()

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
            hot_runtime = types.SimpleNamespace(read_file=AsyncMock(return_value=content))

            manager = SandboxManager(session)
            manager._build_runtime = lambda provider, sandbox: cold_runtime  # type: ignore[method-assign]
            manager.ensure_running_for_user = AsyncMock(return_value=hot_runtime)

            fetched, result = await manager.read_file_for_user(
                owner_id=user.id,
                file_id=file.id,
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"abc")
            manager.ensure_running_for_user.assert_awaited_once_with(
                owner_id=user.id,
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
                sandbox_path="/home/user/bucket/giga_agent/u/r.txt",
                original_name="r.txt",
                file_type="text",
                size=3,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            with self.assertRaises(PermissionError):
                await manager.read_file_for_user(owner_id=foreign.id, file_id=file.id)

    async def test_read_file_by_path_for_user_dispatches(self):
        user = await self._create_user("m5@example.com")
        provider = await self._create_provider(user.id)

        async with self.session_factory() as session:
            repo = FileRepository(session)
            file = await repo.create(
                owner_id=user.id,
                provider_id=provider.id,
                sandbox_path="/home/user/bucket/giga_agent/u/by-path.txt",
                original_name="by-path.txt",
                file_type="text",
                size=8,
            )
            self.assertIsNotNone(file)

            manager = SandboxManager(session)
            content = ContentResult(data=b"by-path")
            manager.read_file_for_user = AsyncMock(return_value=(file, content))

            fetched, result = await manager.read_file_by_path_for_user(
                owner_id=user.id,
                sandbox_path="/home/user/bucket/giga_agent/u/by-path.txt",
            )

            self.assertEqual(fetched.id, file.id)
            self.assertIsInstance(result, ContentResult)
            self.assertEqual(result.data, b"by-path")
            manager.read_file_for_user.assert_awaited_once_with(
                owner_id=user.id,
                file_id=file.id,
            )

    async def test_upload_files_for_user_creates_db_records_in_input_order(self):
        user = await self._create_user("m6@example.com")
        provider = await self._create_provider(user.id)
        runtime = types.SimpleNamespace(
            upload_file=AsyncMock(
                side_effect=[
                    "/home/user/bucket/giga_agent/test/first.png",
                    "/home/user/bucket/giga_agent/test/second.mp3",
                    "/home/user/bucket/giga_agent/test/third.mp4",
                    "/home/user/bucket/giga_agent/test/fourth.plotly.json",
                ]
            ),
            requires_running_for_upload=lambda: False,
        )

        async with self.session_factory() as session:
            manager = SandboxManager(session)
            manager._build_runtime = lambda provider, sandbox: runtime  # type: ignore[method-assign]
            manager.ensure_running_for_user = AsyncMock()

            files = await manager.upload_files_for_user(
                owner_id=user.id,
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

            self.assertEqual(len(files), 4)
            self.assertEqual([f.file_type for f in files], ["image", "audio", "video", "plotly_graph"])
            self.assertEqual(
                [f.sandbox_path for f in files],
                [
                    "/home/user/bucket/giga_agent/test/first.png",
                    "/home/user/bucket/giga_agent/test/second.mp3",
                    "/home/user/bucket/giga_agent/test/third.mp4",
                    "/home/user/bucket/giga_agent/test/fourth.plotly.json",
                ],
            )
            self.assertEqual(
                [f.original_name for f in files],
                ["first.png", "second.mp3", "third.mp4", "fourth.plotly.json"],
            )
            self.assertEqual([f.size for f in files], [3, 3, 3, 2])
            self.assertEqual(runtime.upload_file.await_count, 4)
            manager.ensure_running_for_user.assert_not_awaited()
            for call in runtime.upload_file.await_args_list:
                self.assertEqual(call.kwargs["owner_id"], user.id)
