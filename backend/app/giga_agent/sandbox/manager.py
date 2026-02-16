import uuid
import logging
import asyncio
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.db import get_session_factory
from giga_agent.models.sandbox import (
    Sandbox,
    SandboxProvider,
    SandboxStatus,
    SandboxRepository,
    SandboxProviderRepository,
    SandboxPairSnapshot,
    SandboxProviderSnapshot,
    SandboxSnapshot,
)
from giga_agent.models.file import File, FileRepository, FileType
from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.registry import SandboxRegistry

logger = logging.getLogger(__name__)


class UploadFileSpec(TypedDict):
    file_name: str
    content: bytes
    file_type: FileType


@dataclass(frozen=True)
class SandboxResolved:
    provider: SandboxProvider | SandboxProviderSnapshot
    sandbox: Sandbox | SandboxSnapshot


class SandboxManager:
    """
    Сервисный слой, связывающий модели БД с runtime-классами песочниц.

    Отвечает за:
    - Автоматическое создание sandbox'а при первом обращении (get_or_create)
    - Запуск и остановку sandbox'ов
    - Обновление активности (touch)
    - Сбор и остановку idle sandbox'ов (GC)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._sandbox_repo = SandboxRepository(db)
        self._provider_repo = SandboxProviderRepository(db)
        self._file_repo = FileRepository(db)

    @classmethod
    async def get_cached_or_db(
        cls,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        session: AsyncSession | None = None,
        use_cache: bool = True,
    ) -> SandboxResolved:
        if use_cache:
            cached = await SandboxRepository.cache_get_pair(
                owner_id=owner_id,
                provider_id=provider_id,
            )
            if cached is not None:
                if cached.sandbox.owner_id == owner_id:
                    return SandboxResolved(
                        provider=cached.provider,
                        sandbox=cached.sandbox,
                    )
                await SandboxRepository.cache_invalidate_pair(
                    owner_id=owner_id,
                    provider_id=cached.provider.id,
                )

        if session is not None:
            return await cls(session).get_or_create_for_user(
                owner_id=owner_id,
                provider_id=provider_id,
                settings=settings,
                use_cache=False,
            )

        factory = await get_session_factory()
        async with factory() as db:
            return await cls(db).get_or_create_for_user(
                owner_id=owner_id,
                provider_id=provider_id,
                settings=settings,
                use_cache=False,
            )

    # ============ Runtime helpers ============

    @staticmethod
    def _merge_settings(
        provider: SandboxProvider,
        sandbox: Sandbox,
    ) -> dict:
        """
        Собрать effective_settings из провайдера и sandbox'а.

        Порядок мерджа: provider.settings ← sandbox.settings
        (sandbox-level переопределяет provider-level).
        idle_timeout берётся из модели провайдера (DB column, не JSON).
        """
        settings = {**(provider.settings or {}), **(sandbox.settings or {})}
        settings["idle_timeout"] = provider.idle_timeout
        return settings

    def _build_runtime(
        self,
        provider: SandboxProvider,
        sandbox: Sandbox,
    ) -> BaseSandbox:
        """Создать runtime-экземпляр песочницы из данных БД."""
        runtime_cls = SandboxRegistry.get(provider.type)
        return runtime_cls(**self._merge_settings(provider, sandbox))

    def _build_runtime_from_existing(
        self,
        provider: SandboxProvider,
        sandbox: Sandbox,
    ) -> BaseSandbox:
        """
        Восстановить runtime для уже запущенного sandbox'а
        (например, для остановки или проверки статуса).

        Connection settings (external_id, токены и т.д.) уже хранятся
        в sandbox.settings и прокидываются через _merge_settings.
        """
        runtime_cls = SandboxRegistry.get(provider.type)
        return runtime_cls(**self._merge_settings(provider, sandbox))

    # ============ Resolve / Get-or-Create ============

    async def _resolve_provider(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ) -> SandboxProvider:
        """
        Определить провайдера для пользователя.

        Если provider_id указан — загружает и проверяет владельца.
        Если не указан — берёт первый активный провайдер пользователя.

        :raises ValueError: Провайдер не найден или не принадлежит пользователю.
        """
        if provider_id is not None:
            provider = await self._provider_repo.get_by_id(provider_id)
            if provider is None:
                raise ValueError(f"Provider {provider_id} not found")
            if provider.owner_id != owner_id:
                raise ValueError(f"Provider {provider_id} does not belong to user {owner_id}")
            return provider

        providers = await self._provider_repo.get_by_owner(owner_id, only_active=True)
        if not providers:
            raise ValueError(
                f"User {owner_id} has no active sandbox providers. "
                "Create a provider first."
            )
        return providers[0]

    async def get_or_create_for_user(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        use_cache: bool = True,
    ) -> SandboxResolved:
        """
        Получить существующий sandbox пользователя или создать новый.

        Если provider_id не указан, используется первый активный провайдер.
        Если sandbox для пары (owner, provider) уже есть — возвращает его.
        Если нет — создаёт запись в БД со статусом STOPPED.

        :param owner_id: ID пользователя.
        :param provider_id: ID провайдера (опционально).
        :param settings: Настройки инстанса (опционально).
        :returns: Существующий или новый sandbox + provider.
        """
        if use_cache:
            cached = await SandboxRepository.cache_get_pair(
                owner_id=owner_id,
                provider_id=provider_id,
            )
            if cached is not None:
                # Safety: ensure the cached pair belongs to the requested user
                if cached.sandbox.owner_id == owner_id:
                    return SandboxResolved(
                        provider=cached.provider,
                        sandbox=cached.sandbox,
                    )
                await SandboxRepository.cache_invalidate_pair(
                    owner_id=owner_id,
                    provider_id=cached.provider.id,
                )

        provider = await self._resolve_provider(owner_id, provider_id)

        sandbox = await self._sandbox_repo.get_by_owner_and_provider(
            owner_id, provider.id
        )
        if sandbox is not None:
            logger.debug(
                f"Found existing sandbox {sandbox.id} for user {owner_id} "
                f"(provider {provider.id})"
            )
            sandbox.provider = provider
            resolved = SandboxResolved(provider=provider, sandbox=sandbox)
            snapshot = SandboxRepository.to_pair_snapshot(provider, sandbox)
            await SandboxRepository.cache_set_pair(
                owner_id=owner_id,
                provider_id=provider.id,
                snapshot=snapshot,
                is_default=(provider_id is None),
            )
            return resolved

        sandbox = await self._sandbox_repo.create(
            owner_id=owner_id,
            provider_id=provider.id,
            settings=settings,
        )
        logger.info(
            f"Created sandbox {sandbox.id} for user {owner_id} "
            f"(provider {provider.id})"
        )
        sandbox.provider = provider
        resolved = SandboxResolved(provider=provider, sandbox=sandbox)
        snapshot = SandboxRepository.to_pair_snapshot(provider, sandbox)
        await SandboxRepository.cache_set_pair(
            owner_id=owner_id,
            provider_id=provider.id,
            snapshot=snapshot,
            is_default=(provider_id is None),
        )
        return resolved

    async def ensure_running_for_user(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
    ) -> BaseSandbox:
        """
        Гарантировать, что у пользователя есть запущенный sandbox.

        1. Находит или создаёт sandbox в БД.
        2. Если sandbox не RUNNING — запускает его.
        3. Если RUNNING но не отвечает — перезапускает.

        :param owner_id: ID пользователя.
        :param provider_id: ID провайдера (опционально).
        :param settings: Настройки инстанса (опционально, только при создании).
        :returns: Готовый к работе BaseSandbox runtime.
        """
        resolved = await self.get_or_create_for_user(
            owner_id, provider_id, settings, use_cache=True
        )
        sandbox = resolved.sandbox
        provider = resolved.provider

        if sandbox.status == SandboxStatus.RUNNING:
            # Проверяем, действительно ли sandbox работает
            runtime = self._build_runtime_from_existing(provider, sandbox)
            if await runtime.is_up():
                await self._sandbox_repo.touch(sandbox.id)
                return runtime

            # Sandbox помечен как RUNNING, но реально не отвечает — перезапускаем
            logger.warning(
                f"Sandbox {sandbox.id} is marked as RUNNING but is not responding, "
                "restarting..."
            )
            orm = await self._sandbox_repo.get_by_id(sandbox.id)
            if orm is not None:
                await self._sandbox_repo.set_status(orm, SandboxStatus.STOPPED)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=owner_id,
                provider_id=sandbox.provider_id,
            )

        return await self.start(sandbox.id)

    # ============ Lifecycle ============

    async def start(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        """
        Запустить sandbox.

        Загружает sandbox + provider, создаёт runtime, вызывает up(),
        обновляет статус и external_id.

        :returns: Готовый к работе BaseSandbox runtime.
        """
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        if sandbox.status == SandboxStatus.RUNNING:
            logger.info(f"Sandbox {sandbox_id} is already running")
            return self._build_runtime_from_existing(sandbox.provider, sandbox)

        provider = sandbox.provider

        # Обновляем статус на STARTING
        await self._sandbox_repo.set_status(sandbox, SandboxStatus.STARTING)

        try:
            runtime = self._build_runtime(provider, sandbox)
            await runtime.up()

            # Сохраняем connection settings для повторного подключения
            connection = runtime.get_connection_settings()
            sandbox.settings = {**(sandbox.settings or {}), **connection}

            # Дублируем external_id в колонку для удобства запросов
            external_id = connection.get("external_id")
            if external_id:
                sandbox.external_id = str(external_id)

            await self._sandbox_repo.set_status(sandbox, SandboxStatus.RUNNING)
            logger.info(f"Sandbox {sandbox_id} started successfully")
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        except Exception as e:
            logger.error(f"Failed to start sandbox {sandbox_id}: {e}")
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise

        return runtime

    async def stop(self, sandbox_id: uuid.UUID) -> Sandbox:
        """
        Остановить sandbox.

        Загружает sandbox + provider, восстанавливает runtime, вызывает stop().
        """
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        if sandbox.status in (SandboxStatus.STOPPED, SandboxStatus.PENDING):
            logger.info(f"Sandbox {sandbox_id} is already stopped")
            return sandbox

        provider = sandbox.provider

        # Обновляем статус на STOPPING
        await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPING)

        try:
            runtime = self._build_runtime_from_existing(provider, sandbox)
            await runtime.stop()

            # Очищаем connection settings (external_id, токены и т.д.)
            connection_keys = set(runtime.get_connection_settings().keys())
            sandbox.settings = {
                k: v for k, v in (sandbox.settings or {}).items()
                if k not in connection_keys
            }
            sandbox.external_id = None

            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
            logger.info(f"Sandbox {sandbox_id} stopped successfully")
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        except Exception as e:
            logger.error(f"Failed to stop sandbox {sandbox_id}: {e}")
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise

        return sandbox

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        """Обновить время последней активности sandbox'а."""
        await self._sandbox_repo.touch(sandbox_id)

    async def get_runtime_for_user(
        self,
        owner_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ) -> BaseSandbox:
        """
        Получить runtime для пользователя.

        Если sandbox не существует — создаёт и запускает его.
        Если существует, но не запущен — запускает.
        Автоматически обновляет last_activity_at.

        :param owner_id: ID пользователя.
        :param provider_id: ID провайдера (опционально).
        :returns: Готовый к работе BaseSandbox runtime.
        """
        return await self.ensure_running_for_user(owner_id, provider_id)

    async def upload_file_for_user(
        self,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
        file_type: FileType = "other",
    ) -> File:
        """
        Загрузить файл в sandbox-хранилище пользователя и сохранить метаданные в БД.

        Провайдер выбирается как первый активный provider пользователя.
        """
        resolved = await self.get_or_create_for_user(
            owner_id=owner_id,
            provider_id=None,
            use_cache=True,
        )
        provider = resolved.provider
        sandbox = resolved.sandbox
        runtime = self._build_runtime(provider, sandbox)
        if runtime.requires_running_for_upload():
            runtime = await self.ensure_running_for_user(
                owner_id=owner_id,
                provider_id=provider.id,
            )

        sandbox_path = await runtime.upload_file(
            owner_id=owner_id,
            file_name=file_name,
            content=content,
        )

        file = await self._file_repo.create(
            owner_id=owner_id,
            provider_id=provider.id,
            sandbox_path=sandbox_path,
            file_type=file_type,  # validated on FileResponse/Pydantic layer
            size=len(content),
        )
        if file is None:
            file = await self._file_repo.get_by_owner_provider_path(
                owner_id=owner_id,
                provider_id=provider.id,
                sandbox_path=sandbox_path,
            )
            if file is None:
                raise RuntimeError("Failed to persist uploaded file metadata")
        return file

    async def upload_files_for_user(
        self,
        owner_id: uuid.UUID,
        files: list[UploadFileSpec],
    ) -> list[File]:
        """
        Пакетно загрузить файлы в sandbox-хранилище пользователя.

        Upload в runtime выполняется параллельно, запись метаданных в БД —
        последовательно в порядке входных данных.
        """
        if not files:
            return []

        resolved = await self.get_or_create_for_user(
            owner_id=owner_id,
            provider_id=None,
            use_cache=True,
        )
        provider = resolved.provider
        sandbox = resolved.sandbox
        runtime = self._build_runtime(provider, sandbox)
        if runtime.requires_running_for_upload():
            runtime = await self.ensure_running_for_user(
                owner_id=owner_id,
                provider_id=provider.id,
            )

        upload_tasks = [
            runtime.upload_file(
                owner_id=owner_id,
                file_name=item["file_name"],
                content=item["content"],
            )
            for item in files
        ]
        uploaded_paths = await asyncio.gather(*upload_tasks, return_exceptions=True)

        created_files: list[File] = []
        for idx, path_or_error in enumerate(uploaded_paths):
            item = files[idx]
            if isinstance(path_or_error, Exception):
                logger.warning(
                    "Failed to upload file '%s' for user %s: %s",
                    item["file_name"],
                    owner_id,
                    path_or_error,
                )
                continue

            sandbox_path = path_or_error
            file = await self._file_repo.create(
                owner_id=owner_id,
                provider_id=provider.id,
                sandbox_path=sandbox_path,
                file_type=item["file_type"],  # validated on Pydantic layer
                size=len(item["content"]),
            )
            if file is None:
                file = await self._file_repo.get_by_owner_provider_path(
                    owner_id=owner_id,
                    provider_id=provider.id,
                    sandbox_path=sandbox_path,
                )
                if file is None:
                    logger.warning(
                        "Failed to persist uploaded file metadata for '%s' (path=%s)",
                        item["file_name"],
                        sandbox_path,
                    )
                    continue

            created_files.append(file)

        return created_files

    async def read_file_for_user(
        self,
        owner_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> tuple[File, bytes | str]:
        """
        Прочитать файл пользователя по file_id через соответствующий sandbox provider.
        """
        file = await self._file_repo.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File {file_id} not found")
        if file.owner_id != owner_id:
            raise PermissionError(
                f"File {file_id} does not belong to user {owner_id}"
            )

        provider = await self._provider_repo.get_by_id(file.provider_id)
        if provider is None:
            # Try cache path (in case provider row was loaded previously via sandbox pair)
            cached = await SandboxRepository.cache_get_pair(
                owner_id=owner_id,
                provider_id=file.provider_id,
            )
            if cached is None:
                raise ValueError(
                    f"Provider {file.provider_id} not found for file {file_id}"
                )
            provider_obj = cached.provider
            if provider_obj.owner_id != owner_id:
                raise PermissionError(
                    f"Provider {provider_obj.id} does not belong to user {owner_id}"
                )
            sandbox_obj = cached.sandbox
        else:
            if provider.owner_id != owner_id:
                raise PermissionError(
                    f"Provider {provider.id} does not belong to user {owner_id}"
                )
            resolved = await self.get_or_create_for_user(
                owner_id=owner_id,
                provider_id=provider.id,
                use_cache=True,
            )
            provider_obj = resolved.provider
            sandbox_obj = resolved.sandbox

        runtime = self._build_runtime(provider_obj, sandbox_obj)
        if runtime.requires_running_for_read(file.sandbox_path):
            runtime = await self.ensure_running_for_user(
                owner_id=owner_id,
                provider_id=provider_obj.id,
            )
        try:
            content_or_url = await runtime.read_file(file.sandbox_path)
        except FileNotFoundError:
            raise
        except PermissionError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to read file '{file.sandbox_path}' (id={file.id}): {e}"
            ) from e

        return file, content_or_url

    async def read_file_by_path_for_user(
        self,
        owner_id: uuid.UUID,
        sandbox_path: str,
    ) -> tuple[File, bytes | str]:
        """
        Прочитать файл пользователя по sandbox_path.
        """
        file = await self._file_repo.get_by_owner_path(
            owner_id=owner_id,
            sandbox_path=sandbox_path,
        )
        if file is None:
            raise ValueError(
                f"File with path '{sandbox_path}' not found for user {owner_id}"
            )

        return await self.read_file_for_user(
            owner_id=owner_id,
            file_id=file.id,
        )

    async def delete_file_for_user(
        self,
        owner_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> None:
        """Удалить метаданные файла пользователя из БД."""
        file = await self._file_repo.get_by_id(file_id)
        if file is None:
            raise ValueError(f"File {file_id} not found")
        if file.owner_id != owner_id:
            raise PermissionError(
                f"File {file_id} does not belong to user {owner_id}"
            )
        await self._file_repo.delete(file)

    async def get_runtime(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        """
        Получить runtime для запущенного sandbox'а по ID (например, для выполнения кода).

        Автоматически обновляет last_activity_at.
        """
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        if sandbox.status != SandboxStatus.RUNNING:
            raise RuntimeError(
                f"Sandbox {sandbox_id} is not running (status: {sandbox.status})"
            )

        await self._sandbox_repo.touch(sandbox_id)
        return self._build_runtime_from_existing(sandbox.provider, sandbox)

    # ============ GC (Idle Cleanup) ============

    async def stop_idle_sandboxes(self) -> list[uuid.UUID]:
        """
        Найти и остановить все sandbox'ы, превысившие idle timeout.

        Возвращает список ID остановленных sandbox'ов.
        """
        idle_sandboxes = await self._sandbox_repo.get_idle_sandboxes()
        stopped: list[uuid.UUID] = []

        for sandbox in idle_sandboxes:
            try:
                logger.info(
                    f"Stopping idle sandbox {sandbox.id} "
                    f"(last activity: {sandbox.last_activity_at})"
                )
                await self.stop(sandbox.id)
                stopped.append(sandbox.id)
            except Exception as e:
                logger.error(
                    f"Failed to stop idle sandbox {sandbox.id}: {e}",
                    exc_info=True,
                )

        if stopped:
            logger.info(f"Stopped {len(stopped)} idle sandbox(es)")

        return stopped
