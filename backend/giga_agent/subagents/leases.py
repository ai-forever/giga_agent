from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass

from cashews import cache

from giga_agent.conf import get_settings

ERROR_CODE = "SUBAGENT_CONCURRENCY_LIMIT"
_TTL_GRACE_SECONDS = 300


class SubagentConcurrencyError(RuntimeError):
    code = ERROR_CODE


@dataclass
class SubagentLease:
    id: str
    user_id: str
    child_thread_id: str
    child_run_id: str | None
    state: str
    created_at: float
    heartbeat_at: float
    expires_at: float


def _index_key(user_id: uuid.UUID) -> str:
    return f"subagents:leases:{user_id}"


def _lock_key(user_id: uuid.UUID) -> str:
    return f"subagents:leases:lock:{user_id}"


async def _read(user_id: uuid.UUID) -> list[dict]:
    raw = await cache.get(_index_key(user_id))
    return list(raw) if isinstance(raw, list) else []


async def acquire_lease(
    user_id: uuid.UUID,
    *,
    child_thread_id: str,
    child_run_id: str | None = None,
) -> SubagentLease:
    settings = get_settings()
    now = time.time()
    async with cache.lock(_lock_key(user_id), expire=10, wait=True):
        rows = [row for row in await _read(user_id) if row.get("expires_at", 0) > now]
        active = [row for row in rows if row.get("state") in {"running", "interrupted"}]
        if len(active) >= settings.giga_agent_max_active_subagents_per_user:
            raise SubagentConcurrencyError(
                f"Active subagent limit ({settings.giga_agent_max_active_subagents_per_user}) reached"
            )
        lease = SubagentLease(
            id=str(uuid.uuid4()),
            user_id=str(user_id),
            child_thread_id=child_thread_id,
            child_run_id=child_run_id,
            state="running",
            created_at=now,
            heartbeat_at=now,
            expires_at=now + settings.giga_agent_subagent_approval_ttl_seconds,
        )
        rows.append(asdict(lease))
        await cache.set(
            _index_key(user_id),
            rows,
            expire=settings.giga_agent_subagent_approval_ttl_seconds
            + _TTL_GRACE_SECONDS,
        )
        return lease


async def update_lease(
    user_id: uuid.UUID,
    lease_id: str,
    *,
    state: str | None = None,
    child_run_id: str | None = None,
) -> None:
    async with cache.lock(_lock_key(user_id), expire=10, wait=True):
        rows = await _read(user_id)
        now = time.time()
        for row in rows:
            if row.get("id") != lease_id:
                continue
            row["heartbeat_at"] = now
            if state is not None:
                row["state"] = state
            if child_run_id is not None:
                row["child_run_id"] = child_run_id
            break
        await cache.set(
            _index_key(user_id),
            rows,
            expire=get_settings().giga_agent_subagent_approval_ttl_seconds
            + _TTL_GRACE_SECONDS,
        )


async def release_lease(user_id: uuid.UUID, lease_id: str) -> None:
    async with cache.lock(_lock_key(user_id), expire=10, wait=True):
        rows = [row for row in await _read(user_id) if row.get("id") != lease_id]
        if rows:
            await cache.set(
                _index_key(user_id),
                rows,
                expire=get_settings().giga_agent_subagent_approval_ttl_seconds
                + _TTL_GRACE_SECONDS,
            )
        else:
            await cache.delete(_index_key(user_id))
