from __future__ import annotations

import uuid
from collections import defaultdict

from giga_agent.core.logging import get_logger
from giga_agent.models.file import FileStorageRef
from giga_agent.models.sandbox import SandboxProviderSnapshot, SandboxSnapshot
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)


async def cleanup_storage_files_best_effort(
    refs: list[FileStorageRef],
    *,
    provider_snapshot: SandboxProviderSnapshot | None = None,
    sandbox_snapshots_by_owner: dict[str, SandboxSnapshot] | None = None,
) -> None:
    """
    Best-effort cleanup for physical files in sandbox storage.

    Requires explicit sandbox/provider snapshots, no DB fallback.
    """
    if not refs:
        return

    if provider_snapshot is None:
        logger.warning("Skip storage cleanup: provider snapshot is not provided")
        return

    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = defaultdict(list)
    for ref in refs:
        grouped[(ref.owner_id, ref.provider_id)].append(ref.sandbox_path)

    for (owner_id, provider_id), paths in grouped.items():
        try:
            if provider_snapshot.id != provider_id:
                logger.warning(
                    "Skip storage cleanup for provider %s: provider snapshot mismatch",
                    provider_id,
                )
                continue

            sandbox = None
            if sandbox_snapshots_by_owner:
                sandbox = sandbox_snapshots_by_owner.get(str(owner_id))
            if sandbox is None:
                logger.warning(
                    "Skip storage cleanup for owner=%s provider=%s: sandbox snapshot is missing",
                    owner_id,
                    provider_id,
                )
                continue

            runtime = SandboxRuntimeFactory.build(provider_snapshot, sandbox)
            for path in paths:
                try:
                    await runtime.delete_file(path)
                except FileNotFoundError:
                    continue
                except Exception as e:
                    logger.warning(
                        "Storage cleanup failed for owner=%s provider=%s path=%s: %s",
                        owner_id,
                        provider_id,
                        path,
                        e,
                    )
        except Exception as e:
            logger.warning(
                "Storage cleanup batch failed for owner=%s provider=%s: %s",
                owner_id,
                provider_id,
                e,
            )
