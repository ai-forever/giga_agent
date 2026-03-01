import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.logging import get_logger
from giga_agent.models.sandbox import Sandbox, SandboxRepository, SandboxStatus
from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.manager.errors import (
    SandboxBusyError,
    SandboxNotFoundError,
    SandboxStateError,
    StorageOperationError,
)
from giga_agent.sandbox.manager.resolve_service import SandboxResolveService
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)


class SandboxLifecycleService:
    _FORCED_STOP_FALLBACK_STATUSES = {
        SandboxStatus.STARTING,
        SandboxStatus.STOPPING,
        SandboxStatus.ERROR,
    }

    def __init__(
        self,
        db: AsyncSession,
        *,
        resolve_service: SandboxResolveService | None = None,
        runtime_factory: SandboxRuntimeFactory | None = None,
    ):
        self.db = db
        self._sandbox_repo = SandboxRepository(db)
        self._resolve = resolve_service or SandboxResolveService(db)
        self._runtime_factory = runtime_factory or SandboxRuntimeFactory()
        self._lock_timeout = self._get_lock_timeout()

    @staticmethod
    def _get_lock_timeout() -> float:
        raw = os.getenv("SANDBOX_LIFECYCLE_LOCK_TIMEOUT_SEC", "15")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 15.0
        return max(value, 1.0)

    async def _with_lifecycle_lock(
        self,
        sandbox_id: uuid.UUID,
        action: Callable[[], Awaitable[BaseSandbox | Sandbox]],
    ) -> BaseSandbox | Sandbox:
        key = f"sandbox:lifecycle:{sandbox_id}"
        try:
            async with asyncio.timeout(self._lock_timeout):
                async with cache.lock(
                    key,
                    expire=self._lock_timeout + 5,
                    wait=True,
                    check_interval=0.05,
                ):
                    return await action()
        except TimeoutError as e:
            raise SandboxBusyError(
                f"Sandbox {sandbox_id} is busy with another lifecycle operation"
            ) from e

    async def _with_provider_capacity_lock(
        self,
        provider_id: uuid.UUID,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        key = f"sandbox:provider:capacity:{provider_id}"
        try:
            async with asyncio.timeout(self._lock_timeout):
                async with cache.lock(
                    key,
                    expire=self._lock_timeout + 5,
                    wait=True,
                    check_interval=0.05,
                ):
                    await action()
        except TimeoutError as e:
            raise SandboxBusyError(
                f"Provider {provider_id} is busy with another capacity operation"
            ) from e

    async def _reserve_capacity_and_mark_starting(
        self,
        *,
        sandbox: Sandbox,
        runtime: BaseSandbox,
    ) -> None:
        if not runtime.has_limit():
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STARTING)
            return

        if runtime.max_active_sandboxes is None or runtime.max_active_sandboxes <= 0:
            raise StorageOperationError(
                "Runtime limit is enabled but max_active_sandboxes is not configured"
            )

        async def _reserve() -> None:
            active_count = await self._sandbox_repo.count_by_provider_and_statuses(
                sandbox.provider_id,
                statuses=[SandboxStatus.RUNNING, SandboxStatus.STARTING],
            )
            if active_count >= runtime.max_active_sandboxes:
                raise SandboxBusyError(
                    "Sandbox capacity exceeded: "
                    f"{active_count}/{runtime.max_active_sandboxes} already active"
                )
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STARTING)

        await self._with_provider_capacity_lock(sandbox.provider_id, action=_reserve)

    async def _start_unlocked(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status == SandboxStatus.RUNNING:
            logger.info("Sandbox %s is already running", sandbox_id)
            return self._runtime_factory.build(sandbox.provider, sandbox)

        provider = sandbox.provider

        try:
            runtime = self._runtime_factory.build(provider, sandbox)
            await self._reserve_capacity_and_mark_starting(
                sandbox=sandbox,
                runtime=runtime,
            )
            await runtime.up()

            connection = runtime.get_connection_settings()
            sandbox.settings = {**(sandbox.settings or {}), **connection}

            external_id = connection.get("external_id")
            if external_id:
                sandbox.external_id = str(external_id)

            await self._sandbox_repo.set_status(sandbox, SandboxStatus.RUNNING)
            logger.info("Sandbox %s started successfully", sandbox_id)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        except SandboxBusyError:
            raise
        except Exception as e:
            logger.error("Failed to start sandbox %s: %s", sandbox_id, e)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise StorageOperationError(f"Failed to start sandbox {sandbox_id}: {e}") from e

        return runtime

    async def start(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        result = await self._with_lifecycle_lock(
            sandbox_id,
            action=lambda: self._start_unlocked(sandbox_id),
        )
        assert isinstance(result, BaseSandbox)
        return result

    async def _stop_unlocked(self, sandbox_id: uuid.UUID) -> Sandbox:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status in (SandboxStatus.STOPPED, SandboxStatus.PENDING):
            logger.info("Sandbox %s is already stopped", sandbox_id)
            return sandbox

        provider = sandbox.provider
        initial_status = SandboxStatus(sandbox.status)
        await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPING)

        try:
            runtime = self._runtime_factory.build(provider, sandbox)
            await runtime.stop()

            self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)

            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
            logger.info("Sandbox %s stopped successfully", sandbox_id)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )

        except Exception as e:
            if initial_status in self._FORCED_STOP_FALLBACK_STATUSES:
                logger.warning(
                    "sandbox_stop_forced_fallback sandbox_id=%s initial_status=%s reason=%s",
                    sandbox_id,
                    initial_status,
                    e,
                )
                runtime = self._runtime_factory.build(provider, sandbox)
                self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
                await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
                await SandboxRepository.cache_invalidate_pair(
                    owner_id=sandbox.owner_id,
                    provider_id=sandbox.provider_id,
                )
                return sandbox

            logger.error("Failed to stop sandbox %s: %s", sandbox_id, e)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise StorageOperationError(f"Failed to stop sandbox {sandbox_id}: {e}") from e

        return sandbox

    async def stop(self, sandbox_id: uuid.UUID) -> Sandbox:
        result = await self._with_lifecycle_lock(
            sandbox_id,
            action=lambda: self._stop_unlocked(sandbox_id),
        )
        assert isinstance(result, Sandbox)
        return result

    @staticmethod
    def _clear_runtime_connection_state(*, sandbox: Sandbox, runtime: BaseSandbox) -> None:
        connection_keys = set(runtime.get_connection_settings().keys())
        sandbox.settings = {
            k: v for k, v in (sandbox.settings or {}).items() if k not in connection_keys
        }
        sandbox.external_id = None

    async def ensure_running_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
    ) -> BaseSandbox:
        resolved = await self._resolve.get_or_create_for_user(
            user_id=user_id,
            provider_id=provider_id,
            settings=settings,
            use_cache=True,
        )
        sandbox = resolved.sandbox
        sandbox_id = sandbox.id

        async def _ensure() -> BaseSandbox:
            sandbox_fresh = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
            if sandbox_fresh is None:
                raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

            if sandbox_fresh.status == SandboxStatus.RUNNING:
                runtime = self._runtime_factory.build(sandbox_fresh.provider, sandbox_fresh)
                if await runtime.is_up():
                    await self._sandbox_repo.touch(sandbox_fresh.id)
                    return runtime

                logger.warning(
                    "Sandbox %s is marked as RUNNING but is not responding, restarting...",
                    sandbox_fresh.id,
                )
                await self._sandbox_repo.set_status(sandbox_fresh, SandboxStatus.STOPPED)
                await SandboxRepository.cache_invalidate_pair(
                    owner_id=user_id,
                    provider_id=sandbox_fresh.provider_id,
                )

            return await self._start_unlocked(sandbox_fresh.id)

        result = await self._with_lifecycle_lock(sandbox_id, action=_ensure)
        assert isinstance(result, BaseSandbox)
        return result

    async def touch(self, sandbox_id: uuid.UUID) -> None:
        await self._sandbox_repo.touch(sandbox_id)

    async def get_runtime_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ) -> BaseSandbox:
        return await self.ensure_running_for_user(user_id, provider_id)

    async def get_runtime(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status != SandboxStatus.RUNNING:
            raise SandboxStateError(
                f"Sandbox {sandbox_id} is not running (status: {sandbox.status})"
            )

        await self._sandbox_repo.touch(sandbox_id)
        return self._runtime_factory.build(sandbox.provider, sandbox)

    async def stop_idle_sandboxes(self) -> list[uuid.UUID]:
        idle_sandboxes = await self._sandbox_repo.get_idle_sandboxes()
        stopped: list[uuid.UUID] = []

        for sandbox in idle_sandboxes:
            try:
                logger.info(
                    "Stopping idle sandbox %s (last activity: %s)",
                    sandbox.id,
                    sandbox.last_activity_at,
                )
                await self.stop(sandbox.id)
                stopped.append(sandbox.id)
            except Exception as e:
                logger.error(
                    "Failed to stop idle sandbox %s: %s",
                    sandbox.id,
                    e,
                    exc_info=True,
                )

        if stopped:
            logger.info("Stopped %s idle sandbox(es)", len(stopped))

        return stopped

    async def _reconcile_stale_starting_unlocked(self, sandbox_id: uuid.UUID) -> uuid.UUID | None:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            logger.info("sandbox_reconcile_skipped sandbox_id=%s reason=not_found", sandbox_id)
            return None
        if sandbox.status != SandboxStatus.STARTING:
            logger.info(
                "sandbox_reconcile_skipped sandbox_id=%s reason=status_changed status=%s",
                sandbox_id,
                sandbox.status,
            )
            return None

        runtime = self._runtime_factory.build(sandbox.provider, sandbox)
        is_up = False
        try:
            is_up = await runtime.is_up()
        except Exception as e:
            logger.warning(
                "sandbox_reconcile_probe_failed sandbox_id=%s reason=%s",
                sandbox_id,
                e,
            )

        if is_up:
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.RUNNING)
            logger.info("sandbox_reconcile_promoted_running sandbox_id=%s", sandbox_id)
        else:
            self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
            logger.info("sandbox_reconcile_healed_stopped sandbox_id=%s", sandbox_id)

        await SandboxRepository.cache_invalidate_pair(
            owner_id=sandbox.owner_id,
            provider_id=sandbox.provider_id,
        )
        return sandbox.id

    async def reconcile_stale_starting(self, ttl_sec: int) -> list[uuid.UUID]:
        stale_before = datetime.utcnow() - timedelta(seconds=max(ttl_sec, 1))
        stale_sandboxes = await self._sandbox_repo.get_stale_starting_sandboxes(
            stale_before=stale_before
        )
        reconciled: list[uuid.UUID] = []

        for sandbox in stale_sandboxes:
            try:
                result = await self._with_lifecycle_lock(
                    sandbox.id,
                    action=lambda sandbox_id=sandbox.id: self._reconcile_stale_starting_unlocked(
                        sandbox_id
                    ),
                )
                if isinstance(result, uuid.UUID):
                    reconciled.append(result)
            except Exception:
                logger.exception(
                    "sandbox_reconcile_failed sandbox_id=%s",
                    sandbox.id,
                )

        return reconciled
