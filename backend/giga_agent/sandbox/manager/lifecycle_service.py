import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.core.logging import get_logger
from giga_agent.models.sandbox import (
    Sandbox,
    SandboxProviderSnapshot,
    SandboxRepository,
    SandboxSnapshot,
    SandboxStatus,
)
from giga_agent.sandbox.base import BaseSandbox
from giga_agent.sandbox.manager.errors import (
    SandboxBusyError,
    SandboxNotFoundError,
    SandboxStateError,
    StorageOperationError,
)
from giga_agent.sandbox.manager.resolve_service import SandboxResolveService
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory
from giga_agent.sandbox.manager.types import (
    LogOnlyOrphanAction,
    OrphanAction,
    RemoveExternalRuntimeAction,
    SetSandboxStatusAction,
    StopExternalRuntimeAction,
)
from giga_agent.sandbox.registry import SandboxRegistry

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
        raw = os.getenv("SANDBOX_LIFECYCLE_LOCK_TIMEOUT_SEC", "30")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 15.0
        return max(value, 1.0)

    async def _with_lifecycle_lock(
        self,
        sandbox_id: uuid.UUID,
        action: Callable[[], Awaitable[Any]],
    ) -> Any:
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

    async def _best_effort_cleanup_runtime(self, runtime: BaseSandbox) -> None:
        try:
            await runtime.stop()
        except Exception as cleanup_error:
            logger.warning(
                "sandbox_runtime_cleanup_failed runtime=%s reason=%s",
                runtime.__class__.__name__,
                cleanup_error,
            )

    async def _start_unlocked(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")

        if sandbox.status == SandboxStatus.RUNNING:
            logger.info("Sandbox %s is already running", sandbox_id)
            return self._runtime_factory.build(sandbox.provider, sandbox)

        provider = sandbox.provider
        runtime = self._runtime_factory.build(provider, sandbox)

        try:
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
            await self._best_effort_cleanup_runtime(runtime)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise StorageOperationError(
                f"Failed to start sandbox {sandbox_id}: {e}"
            ) from e

        return runtime

    async def start(self, sandbox_id: uuid.UUID) -> BaseSandbox:
        result = await self._with_lifecycle_lock(
            sandbox_id,
            action=lambda: self._start_unlocked(sandbox_id),
        )
        assert isinstance(result, BaseSandbox)
        return result

    @staticmethod
    def _clear_runtime_connection_state(
        *, sandbox: Sandbox, runtime: BaseSandbox
    ) -> None:
        connection_keys = set(runtime.get_connection_settings().keys())
        sandbox.settings = {
            k: v
            for k, v in (sandbox.settings or {}).items()
            if k not in connection_keys
        }
        sandbox.external_id = None

    async def _handle_forced_stop_fallback(
        self,
        *,
        sandbox: Sandbox,
        provider,
        initial_status: SandboxStatus,
        reason: Exception,
    ) -> bool:
        logger.warning(
            "sandbox_stop_forced_fallback sandbox_id=%s initial_status=%s reason=%s",
            sandbox.id,
            initial_status,
            reason,
        )

        runtime = self._runtime_factory.build(provider, sandbox)

        try:
            await runtime.stop()
        except Exception as retry_error:
            logger.warning(
                "sandbox_stop_forced_fallback_retry_failed sandbox_id=%s reason=%s",
                sandbox.id,
                retry_error,
            )

        try:
            still_up = await runtime.is_up()
        except Exception as probe_error:
            logger.error(
                "sandbox_stop_forced_fallback_probe_failed sandbox_id=%s reason=%s",
                sandbox.id,
                probe_error,
            )
            return False

        if still_up:
            logger.error(
                "sandbox_stop_forced_fallback_runtime_still_up sandbox_id=%s",
                sandbox.id,
            )
            return False

        self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
        await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
        await SandboxRepository.cache_invalidate_pair(
            owner_id=sandbox.owner_id,
            provider_id=sandbox.provider_id,
        )
        return True

    async def _stop_runtime_for_sandbox(
        self,
        *,
        sandbox: Sandbox,
        force: bool,
        reason: str,
    ) -> Sandbox:
        if not force and sandbox.status in (SandboxStatus.STOPPED, SandboxStatus.PENDING):
            logger.info("Sandbox %s is already stopped", sandbox.id)
            return sandbox

        provider = sandbox.provider
        initial_status = SandboxStatus(sandbox.status)
        if sandbox.status != SandboxStatus.STOPPING:
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPING)

        try:
            runtime = self._runtime_factory.build(provider, sandbox)
            await runtime.stop()
            self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
            logger.info(
                "Sandbox %s stopped successfully reason=%s",
                sandbox.id,
                reason,
            )
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
        except Exception as e:
            if initial_status in self._FORCED_STOP_FALLBACK_STATUSES or force:
                fallback_stopped = await self._handle_forced_stop_fallback(
                    sandbox=sandbox,
                    provider=provider,
                    initial_status=initial_status,
                    reason=e,
                )
                if fallback_stopped:
                    return sandbox

            logger.error("Failed to stop sandbox %s: %s", sandbox.id, e)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.ERROR)
            await SandboxRepository.cache_invalidate_pair(
                owner_id=sandbox.owner_id,
                provider_id=sandbox.provider_id,
            )
            raise StorageOperationError(
                f"Failed to stop sandbox {sandbox.id}: {e}"
            ) from e

        return sandbox

    async def _stop_unlocked(self, sandbox_id: uuid.UUID) -> Sandbox:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found")
        return await self._stop_runtime_for_sandbox(
            sandbox=sandbox,
            force=False,
            reason="explicit_stop",
        )

    async def stop(self, sandbox_id: uuid.UUID) -> Sandbox:
        result = await self._with_lifecycle_lock(
            sandbox_id,
            action=lambda: self._stop_unlocked(sandbox_id),
        )
        assert isinstance(result, Sandbox)
        return result

    async def _set_sandbox_status_unlocked(
        self,
        *,
        sandbox: Sandbox,
        status: SandboxStatus,
        clear_runtime_connection: bool,
    ) -> SandboxStatus:
        if clear_runtime_connection:
            runtime = self._runtime_factory.build(sandbox.provider, sandbox)
            self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
        await self._sandbox_repo.set_status(sandbox, status)
        await SandboxRepository.cache_invalidate_pair(
            owner_id=sandbox.owner_id,
            provider_id=sandbox.provider_id,
        )
        return status

    async def _apply_orphan_action_unlocked(self, action: OrphanAction) -> str | None:
        if isinstance(action, LogOnlyOrphanAction):
            log_fn = getattr(logger, action.level, logger.info)
            log_fn(
                "sandbox_orphan_log provider_type=%s provider_id=%s sandbox_id=%s external_id=%s reason=%s",
                action.provider_type,
                action.provider_id,
                action.sandbox_id,
                action.external_id,
                action.reason,
            )
            return None

        if isinstance(action, RemoveExternalRuntimeAction):
            runtime_cls = SandboxRegistry.get(action.provider_type)
            await runtime_cls.remove_external_runtime(action.external_id)
            return action.external_id

        sandbox = None
        if action.sandbox_id is not None:
            sandbox = await self._sandbox_repo.get_by_id_with_provider(action.sandbox_id)

        if isinstance(action, StopExternalRuntimeAction):
            if sandbox is None:
                runtime_cls = SandboxRegistry.get(action.provider_type)
                await runtime_cls.remove_external_runtime(action.external_id)
                return action.external_id
            await self._stop_runtime_for_sandbox(
                sandbox=sandbox,
                force=True,
                reason=action.reason,
            )
            return str(sandbox.id)

        if isinstance(action, SetSandboxStatusAction):
            if sandbox is None:
                return None
            await self._set_sandbox_status_unlocked(
                sandbox=sandbox,
                status=action.status,
                clear_runtime_connection=action.clear_runtime_connection,
            )
            return str(sandbox.id)

        return None

    async def apply_orphan_action(self, action: OrphanAction) -> str | None:
        sandbox_id = getattr(action, "sandbox_id", None)
        if sandbox_id is None:
            return await self._apply_orphan_action_unlocked(action)
        result = await self._with_lifecycle_lock(
            sandbox_id,
            action=lambda: self._apply_orphan_action_unlocked(action),
        )
        if result is None or isinstance(result, str):
            return result
        return str(result)

    async def cleanup_orphans_for_provider_type(self, provider_type: str) -> list[str]:
        runtime_cls = SandboxRegistry.get(provider_type)
        sandboxes = await self._sandbox_repo.get_by_provider_type_with_provider(provider_type)
        provider_snapshots: dict[uuid.UUID, SandboxProviderSnapshot] = {}
        sandbox_snapshots: list[SandboxSnapshot] = []

        for sandbox in sandboxes:
            if sandbox.provider is None:
                continue
            pair = SandboxRepository.to_pair_snapshot(sandbox.provider, sandbox)
            provider_snapshots[pair.provider.id] = pair.provider
            sandbox_snapshots.append(pair.sandbox)

        actions = await runtime_cls.cleanup_orphans(
            providers=list(provider_snapshots.values()),
            sandboxes=sandbox_snapshots,
        )
        applied: list[str] = []

        for action in actions:
            try:
                result = await self.apply_orphan_action(action)
                if result is not None:
                    applied.append(result)
            except Exception:
                logger.exception(
                    "sandbox_orphan_action_failed provider_type=%s action=%s",
                    provider_type,
                    action,
                )

        return applied

    async def cleanup_orphans(self, *, concurrency: int = 1) -> dict[str, list[str]]:
        results: dict[str, list[str]] = {}
        semaphore = asyncio.Semaphore(max(concurrency, 1))

        async def _run(provider_type: str) -> tuple[str, list[str] | None]:
            async with semaphore:
                try:
                    applied = await self.cleanup_orphans_for_provider_type(provider_type)
                except Exception:
                    logger.exception(
                        "sandbox_orphan_cleanup_failed provider_type=%s",
                        provider_type,
                    )
                    return provider_type, None
                return provider_type, applied

        batches = await asyncio.gather(
            *(_run(provider_type) for provider_type in SandboxRegistry.available_types())
        )
        for provider_type, applied in batches:
            if applied:
                results[provider_type] = applied
        return results

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
                runtime = self._runtime_factory.build(
                    sandbox_fresh.provider, sandbox_fresh
                )
                if await runtime.is_up():
                    await self._sandbox_repo.touch(sandbox_fresh.id)
                    return runtime

                logger.warning(
                    "Sandbox %s is marked as RUNNING but is not responding, restarting...",
                    sandbox_fresh.id,
                )
                await self._stop_runtime_for_sandbox(
                    sandbox=sandbox_fresh,
                    force=True,
                    reason="running_but_not_responding_restart",
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

    async def _reconcile_stale_starting_unlocked(
        self, sandbox_id: uuid.UUID
    ) -> uuid.UUID | None:
        sandbox = await self._sandbox_repo.get_by_id_with_provider(sandbox_id)
        if sandbox is None:
            logger.info(
                "sandbox_reconcile_skipped sandbox_id=%s reason=not_found", sandbox_id
            )
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
            await self._best_effort_cleanup_runtime(runtime)
            self._clear_runtime_connection_state(sandbox=sandbox, runtime=runtime)
            await self._sandbox_repo.set_status(sandbox, SandboxStatus.STOPPED)
            logger.info("sandbox_reconcile_healed_stopped sandbox_id=%s", sandbox_id)

        await SandboxRepository.cache_invalidate_pair(
            owner_id=sandbox.owner_id,
            provider_id=sandbox.provider_id,
        )
        return sandbox.id

    async def reconcile_stale_starting(self, ttl_sec: int) -> list[uuid.UUID]:
        stale_before = datetime.now(timezone.utc) - timedelta(seconds=max(ttl_sec, 1))
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
