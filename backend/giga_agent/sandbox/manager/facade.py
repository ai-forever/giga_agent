import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models.file import File, FileType
from giga_agent.models.sandbox import Sandbox
from giga_agent.sandbox.base import BaseSandbox, FileReadResult
from giga_agent.sandbox.manager.file_service import SandboxFileService
from giga_agent.sandbox.manager.lifecycle_service import SandboxLifecycleService
from giga_agent.sandbox.manager.resolve_service import SandboxResolveService
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.sandbox.manager.types import (
    SandboxResolved,
    UploadBatchResult,
    UploadFileSpec,
)


class SandboxManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._runtime_factory = SandboxRuntimeFactory()
        self._resolve = SandboxResolveService(db)
        self._lifecycle = SandboxLifecycleService(
            db,
            resolve_service=self._resolve,
            runtime_factory=self._runtime_factory,
        )
        self._files = SandboxFileService(
            db,
            resolve_service=self._resolve,
            lifecycle_service=self._lifecycle,
            runtime_factory=self._runtime_factory,
        )

    @classmethod
    async def get_cached_or_db(
        cls,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        session: AsyncSession,
    ) -> SandboxResolved:
        return await SandboxResolveService.get_cached_or_db(
            user_id=user_id,
            provider_id=provider_id,
            settings=settings,
            session=session,
        )

    async def get_or_create_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        use_cache: bool = True,
    ) -> SandboxResolved:
        return await self._resolve.get_or_create_for_user(
            user_id=user_id,
            provider_id=provider_id,
            settings=settings,
            use_cache=use_cache,
        )

    async def _resolve_provider(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ):
        return await self._resolve.resolve_provider(
            user_id=user_id,
            provider_id=provider_id,
        )

    async def ensure_running_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
    ) -> BaseSandbox:
        return await self._lifecycle.ensure_running_for_user(
            user_id=user_id,
            provider_id=provider_id,
            settings=settings,
        )

    async def start(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        return await self._lifecycle.start(sandbox_id)

    async def stop(self, sandbox_id: uuid.UUID) -> Sandbox:
        return await self._lifecycle.stop(sandbox_id)

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        await self._lifecycle.touch(sandbox_id)

    async def get_runtime_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ) -> BaseSandbox:
        return await self._lifecycle.get_runtime_for_user(user_id, provider_id)

    async def get_runtime(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        return await self._lifecycle.get_runtime(sandbox_id)

    async def stop_idle_sandboxes(self) -> list[uuid.UUID]:
        return await self._lifecycle.stop_idle_sandboxes()

    async def reconcile_stale_starting_sandboxes(self, ttl_sec: int) -> list[uuid.UUID]:
        return await self._lifecycle.reconcile_stale_starting(ttl_sec)

    async def cleanup_orphans(self, *, concurrency: int = 1) -> dict[str, list[str]]:
        return await self._lifecycle.cleanup_orphans(concurrency=concurrency)

    async def upload_file_for_user(
        self,
        user_id: uuid.UUID,
        file_name: str,
        content: bytes,
        file_type: FileType = "other",
    ) -> File:
        return await self._files.upload_file_for_user(
            user_id=user_id,
            file_name=file_name,
            content=content,
            file_type=file_type,
        )

    async def upload_files_for_user(
        self,
        user_id: uuid.UUID,
        files: list[UploadFileSpec],
    ) -> UploadBatchResult:
        return await self._files.upload_files_for_user(user_id=user_id, files=files)

    async def read_file_for_user(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> tuple[File, FileReadResult]:
        return await self._files.read_file_for_user(user_id=user_id, file_id=file_id)

    async def read_file_by_path_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> tuple[File, FileReadResult]:
        return await self._files.read_file_by_path_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
        )

    async def delete_file_for_user(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> None:
        await self._files.delete_file_for_user(user_id=user_id, file_id=file_id)

    async def delete_file_by_path_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> None:
        await self._files.delete_file_by_path_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
        )

    async def write_file_content_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
        content: bytes,
    ) -> None:
        await self._files.write_file_content_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
            content=content,
        )

    async def file_exists_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> bool:
        return await self._files.file_exists_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
        )
