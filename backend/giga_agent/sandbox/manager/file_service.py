import asyncio
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.models import UserRepository
from giga_agent.models.file import File, FileRepository, FileType
from giga_agent.models.sandbox import SandboxRepository, SandboxProviderRepository
from giga_agent.sandbox.base import FileReadResult
from giga_agent.sandbox.manager.errors import (
    FileAccessError,
    FileNotFoundForUserError,
    ProviderNotFoundError,
    StorageOperationError,
)
from giga_agent.sandbox.manager.lifecycle_service import SandboxLifecycleService
from giga_agent.sandbox.manager.resolve_service import SandboxResolveService
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.sandbox.manager.types import (
    UploadBatchError,
    UploadBatchResult,
    UploadFileSpec,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class TransientFile:
    id: uuid.UUID
    owner_id: uuid.UUID
    provider_id: uuid.UUID
    sandbox_path: str
    original_name: str
    file_type: FileType
    size: int
    created_at: datetime
    updated_at: datetime


def _is_cli_runtime() -> bool:
    return get_settings().giga_agent_runtime == "cli"


def _build_transient_file(
    *,
    owner_id: uuid.UUID,
    provider_id: uuid.UUID,
    sandbox_path: str,
    original_name: str,
    file_type: FileType,
    size: int,
) -> TransientFile:
    now = datetime.now(timezone.utc)
    return TransientFile(
        id=uuid.uuid4(),
        owner_id=owner_id,
        provider_id=provider_id,
        sandbox_path=sandbox_path,
        original_name=original_name,
        file_type=file_type,
        size=size,
        created_at=now,
        updated_at=now,
    )


class SandboxFileService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        resolve_service: SandboxResolveService | None = None,
        lifecycle_service: SandboxLifecycleService | None = None,
        runtime_factory: SandboxRuntimeFactory | None = None,
    ):
        self.db = db
        self._file_repo = FileRepository(db)
        self._provider_repo = SandboxProviderRepository(db)
        self._resolve = resolve_service or SandboxResolveService(db)
        self._runtime_factory = runtime_factory or SandboxRuntimeFactory()
        self._lifecycle = lifecycle_service or SandboxLifecycleService(
            db,
            resolve_service=self._resolve,
            runtime_factory=self._runtime_factory,
        )

    async def _resolve_runtime_for_file(
        self,
        *,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None,
        sandbox_path: str,
        for_op: str,
    ):
        if _is_cli_runtime():
            resolved = await self._resolve.get_or_create_for_user(
                user_id=user_id,
                provider_id=None,
                use_cache=True,
            )
            return (
                self._runtime_factory.build(resolved.provider, resolved.sandbox),
                resolved.provider,
            )

        if provider_id is None:
            raise ProviderNotFoundError(
                f"User {user_id} sandbox provider is not configured"
            )

        provider = await self._provider_repo.get_by_id(provider_id)
        if provider is None:
            cached = await SandboxRepository.cache_get_pair(
                owner_id=user_id,
                provider_id=provider_id,
            )
            if cached is None:
                raise ProviderNotFoundError(f"Provider {provider_id} not found")
            provider_obj = cached.provider
            sandbox_obj = cached.sandbox
        else:
            resolved = await self._resolve.get_or_create_for_user(
                user_id=user_id,
                provider_id=provider.id,
                use_cache=True,
            )
            provider_obj = resolved.provider
            sandbox_obj = resolved.sandbox

        runtime = self._runtime_factory.build(provider_obj, sandbox_obj)

        needs_running = False
        if for_op == "read":
            needs_running = runtime.requires_running_for_read(sandbox_path)
        elif for_op == "delete":
            needs_running = runtime.requires_running_for_delete(sandbox_path)
        elif for_op == "write":
            needs_running = runtime.requires_running_for_write(sandbox_path)
        elif for_op == "file_exists":
            needs_running = runtime.requires_running_for_file_exists(sandbox_path)

        if needs_running:
            runtime = await self._lifecycle.ensure_running_for_user(
                user_id=user_id,
                provider_id=provider_obj.id,
            )

        return runtime, provider_obj

    async def _read_file_from_runtime(
        self,
        runtime,
        *,
        sandbox_path: str,
        file_id: uuid.UUID,
    ) -> FileReadResult:
        try:
            return await runtime.read_file(sandbox_path)
        except FileNotFoundError as e:
            raise FileNotFoundForUserError(str(e)) from e
        except PermissionError as e:
            raise FileAccessError(str(e)) from e
        except Exception as e:
            raise StorageOperationError(
                f"Failed to read file '{sandbox_path}' (id={file_id}): {e}"
            ) from e

    async def _persist_uploaded_file(
        self,
        *,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        sandbox_path: str,
        file_name: str,
        file_type: FileType,
        size: int,
    ) -> File:
        """Записать метаданные загруженного файла (общий хвост для bytes- и
        stream-путей загрузки)."""
        original_name = PurePosixPath(file_name).name
        if _is_cli_runtime():
            return _build_transient_file(
                owner_id=user_id,
                provider_id=provider_id,
                sandbox_path=sandbox_path,
                original_name=original_name,
                file_type=file_type,
                size=size,
            )

        file = await self._file_repo.create(
            owner_id=user_id,
            provider_id=provider_id,
            sandbox_path=sandbox_path,
            original_name=original_name,
            file_type=file_type,
            size=size,
        )
        if file is None:
            file = await self._file_repo.get_by_owner_provider_path(
                owner_id=user_id,
                provider_id=provider_id,
                sandbox_path=sandbox_path,
            )
            if file is None:
                raise StorageOperationError("Failed to persist uploaded file metadata")
        return file

    async def upload_file_for_user(
        self,
        user_id: uuid.UUID,
        file_name: str,
        content: bytes,
        file_type: FileType = "other",
    ) -> File:
        resolved = await self._resolve.get_or_create_for_user(
            user_id=user_id,
            provider_id=None,
            use_cache=True,
        )
        provider = resolved.provider
        sandbox = resolved.sandbox
        runtime = self._runtime_factory.build(provider, sandbox)
        if runtime.requires_running_for_upload():
            runtime = await self._lifecycle.ensure_running_for_user(
                user_id=user_id,
                provider_id=provider.id,
            )

        sandbox_path = await runtime.upload_file(
            owner_id=user_id,
            file_name=file_name,
            content=content,
        )

        return await self._persist_uploaded_file(
            user_id=user_id,
            provider_id=provider.id,
            sandbox_path=sandbox_path,
            file_name=file_name,
            file_type=file_type,
            size=len(content),
        )

    async def upload_stream_for_user(
        self,
        user_id: uuid.UUID,
        file_name: str,
        fileobj,
        size: int,
        file_type: FileType = "other",
    ) -> File:
        """Загрузить файл из seekable файлового объекта (спул UploadFile), не
        собирая тело целиком в RAM API-процесса. Размер берём из ``size``
        (метаданные запроса), а не из len(content)."""
        resolved = await self._resolve.get_or_create_for_user(
            user_id=user_id,
            provider_id=None,
            use_cache=True,
        )
        provider = resolved.provider
        sandbox = resolved.sandbox
        runtime = self._runtime_factory.build(provider, sandbox)
        if runtime.requires_running_for_upload():
            runtime = await self._lifecycle.ensure_running_for_user(
                user_id=user_id,
                provider_id=provider.id,
            )

        sandbox_path = await runtime.upload_file_stream(
            owner_id=user_id,
            file_name=file_name,
            fileobj=fileobj,
            size=size,
        )

        return await self._persist_uploaded_file(
            user_id=user_id,
            provider_id=provider.id,
            sandbox_path=sandbox_path,
            file_name=file_name,
            file_type=file_type,
            size=size,
        )

    async def upload_files_for_user(
        self,
        user_id: uuid.UUID,
        files: list[UploadFileSpec],
    ) -> UploadBatchResult:
        if not files:
            return UploadBatchResult(files=[], errors=[])

        resolved = await self._resolve.get_or_create_for_user(
            user_id=user_id,
            provider_id=None,
            use_cache=True,
        )
        provider = resolved.provider
        sandbox = resolved.sandbox
        runtime = self._runtime_factory.build(provider, sandbox)
        if runtime.requires_running_for_upload():
            runtime = await self._lifecycle.ensure_running_for_user(
                user_id=user_id,
                provider_id=provider.id,
            )

        upload_tasks = [
            runtime.upload_file(
                owner_id=user_id,
                file_name=item["file_name"],
                content=item["content"],
            )
            for item in files
        ]
        uploaded_paths = await asyncio.gather(*upload_tasks, return_exceptions=True)

        created_files: list[File] = []
        upload_errors: list[UploadBatchError] = []
        for idx, path_or_error in enumerate(uploaded_paths):
            item = files[idx]
            file_name = item["file_name"]
            if isinstance(path_or_error, Exception):
                logger.warning(
                    "Failed to upload file '%s' for user %s: %s",
                    file_name,
                    user_id,
                    path_or_error,
                )
                upload_errors.append(
                    UploadBatchError(
                        index=idx,
                        file_name=file_name,
                        code="upload_failed",
                        message=str(path_or_error),
                        retryable=True,
                    )
                )
                continue

            sandbox_path = path_or_error
            original_name = PurePosixPath(file_name).name
            if _is_cli_runtime():
                created_files.append(
                    _build_transient_file(
                        owner_id=user_id,
                        provider_id=provider.id,
                        sandbox_path=sandbox_path,
                        original_name=original_name,
                        file_type=item["file_type"],
                        size=len(item["content"]),
                    )
                )
                continue

            file = await self._file_repo.create(
                owner_id=user_id,
                provider_id=provider.id,
                sandbox_path=sandbox_path,
                original_name=original_name,
                file_type=item["file_type"],
                size=len(item["content"]),
            )
            if file is None:
                file = await self._file_repo.get_by_owner_provider_path(
                    owner_id=user_id,
                    provider_id=provider.id,
                    sandbox_path=sandbox_path,
                )
                if file is None:
                    logger.warning(
                        "Failed to persist uploaded file metadata for '%s' (path=%s)",
                        file_name,
                        sandbox_path,
                    )
                    upload_errors.append(
                        UploadBatchError(
                            index=idx,
                            file_name=file_name,
                            code="metadata_persist_failed",
                            message=(
                                "Failed to persist uploaded file metadata "
                                f"for path {sandbox_path}"
                            ),
                            retryable=False,
                        )
                    )
                    continue

            created_files.append(file)

        return UploadBatchResult(files=created_files, errors=upload_errors)

    async def read_file_for_user(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> tuple[File, FileReadResult]:
        file = await self._file_repo.get_by_id(file_id)
        if file is None:
            raise FileNotFoundForUserError(f"File {file_id} not found")
        if file.owner_id != user_id:
            raise FileAccessError(f"File {file_id} does not belong to user {user_id}")

        runtime, provider = await self._resolve_runtime_for_file(
            user_id=user_id,
            provider_id=file.provider_id,
            sandbox_path=file.sandbox_path,
            for_op="read",
        )

        result = await self._read_file_from_runtime(
            runtime,
            sandbox_path=file.sandbox_path,
            file_id=file.id,
        )

        return file, result

    async def read_file_by_path_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> tuple[File, FileReadResult]:
        file = await self._file_repo.get_by_owner_path(
            owner_id=user_id,
            sandbox_path=sandbox_path,
        )
        if file is None:
            provider_id = None
            if not _is_cli_runtime():
                user = await UserRepository.get_cached_or_db(
                    user_id=user_id, session=self.db
                )
                provider_id = user.sandbox_provider_id
            runtime, provider = await self._resolve_runtime_for_file(
                user_id=user_id,
                provider_id=provider_id,
                sandbox_path=sandbox_path,
                for_op="read",
            )
            file_id = uuid.uuid4()
            result = await self._read_file_from_runtime(
                runtime,
                sandbox_path=sandbox_path,
                file_id=file_id,
            )

            return (
                _build_transient_file(
                    owner_id=user_id,
                    provider_id=provider.id,
                    sandbox_path=sandbox_path,
                    original_name=PurePosixPath(sandbox_path).name,
                    file_type="other",
                    size=0,
                ),
                result,
            )

        return await self.read_file_for_user(
            user_id=user_id,
            file_id=file.id,
        )

    async def delete_file_for_user(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> None:
        file = await self._file_repo.get_by_id(file_id)
        if file is None:
            raise FileNotFoundForUserError(f"File {file_id} not found")
        if file.owner_id != user_id:
            raise FileAccessError(f"File {file_id} does not belong to user {user_id}")

        try:
            runtime, _ = await self._resolve_runtime_for_file(
                user_id=user_id,
                provider_id=file.provider_id,
                sandbox_path=file.sandbox_path,
                for_op="delete",
            )
            await runtime.delete_file(file.sandbox_path)
        except FileNotFoundError:
            pass
        except ProviderNotFoundError:
            logger.warning(
                "Provider for file %s is not found during delete, metadata will be removed",
                file_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to delete file from storage (best-effort): %s",
                e,
                exc_info=True,
            )

        await self._file_repo.delete(file)

    async def delete_file_by_path_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> None:
        file = await self._file_repo.get_by_owner_path(
            owner_id=user_id,
            sandbox_path=sandbox_path,
        )
        if file is None:
            return
        await self.delete_file_for_user(user_id=user_id, file_id=file.id)

    async def _resolve_runtime_for_user(
        self,
        *,
        user_id: uuid.UUID,
        sandbox_path: str,
        for_op: str,
    ):
        if _is_cli_runtime():
            return await self._resolve_runtime_for_file(
                user_id=user_id,
                provider_id=None,
                sandbox_path=sandbox_path,
                for_op=for_op,
            )

        user = await UserRepository.get_cached_or_db(user_id=user_id, session=self.db)
        return await self._resolve_runtime_for_file(
            user_id=user_id,
            provider_id=user.sandbox_provider_id,
            sandbox_path=sandbox_path,
            for_op=for_op,
        )

    async def write_file_content_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
        content: bytes,
    ) -> None:
        runtime, _ = await self._resolve_runtime_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
            for_op="write",
        )
        try:
            await runtime.write_file_content(sandbox_path, content)
        except Exception as e:
            raise StorageOperationError(
                f"Failed to write file '{sandbox_path}': {e}"
            ) from e

    async def file_exists_for_user(
        self,
        user_id: uuid.UUID,
        sandbox_path: str,
    ) -> bool:
        runtime, _ = await self._resolve_runtime_for_user(
            user_id=user_id,
            sandbox_path=sandbox_path,
            for_op="file_exists",
        )
        try:
            return await runtime.file_exists(sandbox_path)
        except Exception as e:
            traceback.print_exc()
            raise StorageOperationError(
                f"Failed to check file existence '{sandbox_path}': {e}"
            ) from e

    async def get_current_workdir_for_user(
        self,
        user_id: uuid.UUID,
    ) -> str | None:
        """Cheap lookup of the runtime cwd for user-facing hints."""
        try:
            runtime, _ = await self._resolve_runtime_for_user(
                user_id=user_id,
                sandbox_path="",
                for_op="file_exists",
            )
        except Exception:
            return None
        try:
            return runtime.current_workdir()
        except Exception:
            return None
