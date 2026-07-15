"""In-process warm-session pool for backend MCP (phase 1: embedded).

Why a pool: an MCP session is a stateful connection that costs a ~0.5s
connect+initialize handshake, AND it cannot be moved between asyncio tasks —
``streamable_http_client`` / ``stdio_client`` / ``ClientSession`` are anyio
task-group context managers whose background read/write tasks live in the task
that opened them. So "keep a session warm" means a dedicated long-lived task
owns the open session and serves operations to it over a queue (the ``_Worker``
actor below). A live warm session is therefore bound to one process/event loop;
Redis can coordinate limits, never hand a session to another pod.

Scope of phase 1 (see design decisions):
- **Embedded only** — lives in the main process; created lazily, stopped on
  shutdown. ``GIGA_AGENT_MCP_POOL_MODE=off`` reverts to a session-per-call.
- **Exclusive checkout** — one in-flight operation per warm session.
- **Pools non-OAuth servers** (none / bearer / stdio). OAuth servers still use a
  one-shot session per acquire (the ``_DirectHandle`` path), keeping their
  existing per-(user, server) refresh lock and request-scoped db. Pooling OAuth
  is a later extension (needs a session factory + token-refresh callback).
- **Limits** — per (user, server), per user, global total; idle TTL; max
  lifetime. At capacity a request gracefully degrades to a cold one-shot session
  (still throttled by the per-server semaphore) rather than blocking.

The acquire/handle interface preserves list+call affinity: a single ``acquire()``
block runs the gate listing and the tool call over the SAME session.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

from cashews import cache

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.modules.mcp.client import (
    _MAX_RESULT_BYTES,
    _OPERATION_TIMEOUT,
    _TOOL_CALL_TIMEOUT,
    _TOOLS_CACHE_TTL,
    _extract_resource_text,
    _open_session,
    _process_call_result,
    _serialize_tool,
)
from giga_agent.modules.mcp.errors import McpUnreachableError
from giga_agent.modules.mcp.resolved import ResolvedServer

logger = get_logger(__name__)

_ = _MAX_RESULT_BYTES  # re-exported for callers/tests via this module

# A session operation: given the live ClientSession, do the work and return the
# raw MCP result. Run by the owning worker (pooled) or inline (direct).
SessionOp = Callable[[Any], Awaitable[Any]]


# ── Handles ─────────────────────────────────────────────────────────────────


class SessionHandle:
    """A leased MCP session. Subclasses provide the raw transport ops.

    The cooked methods (``list_tools`` / ``call_tool`` / ``read_resource``) add
    the cross-cutting concerns — tool-cache, payload size guard, resource text
    extraction — so every call site behaves identically regardless of whether
    the session is pooled or one-shot.
    """

    server: ResolvedServer
    broken: bool = False

    async def _raw_list_tools(self) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _raw_call_tool(
        self, name: str, args: dict[str, Any], timeout: float
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def _raw_read_resource(self, uri: str) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def list_tools(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        key = McpServerRepository.cache_key(self.server.cache_id)
        if not force_refresh:
            cached = await cache.get(key)
            if cached is not None:
                return cached
        result = await self._raw_list_tools()
        tools = [_serialize_tool(t) for t in result.tools]
        await cache.set(key, tools, expire=_TOOLS_CACHE_TTL)
        return tools

    async def call_tool(
        self, name: str, args: dict[str, Any] | None, *, timeout: float | None = None
    ) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None]:
        raw = await self._raw_call_tool(name, args or {}, timeout or _TOOL_CALL_TIMEOUT)
        return _process_call_result(raw, name)

    async def read_resource(self, uri: str) -> tuple[str, str]:
        raw = await self._raw_read_resource(uri)
        return _extract_resource_text(raw, uri)


class _DirectHandle(SessionHandle):
    """One-shot session held open only for the duration of the acquire block."""

    def __init__(self, server: ResolvedServer, session: Any):
        self.server = server
        self._session = session
        self.broken = False

    async def _raw_list_tools(self) -> Any:
        return await asyncio.wait_for(self._session.list_tools(), _OPERATION_TIMEOUT)

    async def _raw_call_tool(
        self, name: str, args: dict[str, Any], timeout: float
    ) -> Any:
        return await asyncio.wait_for(self._session.call_tool(name, args), timeout)

    async def _raw_read_resource(self, uri: str) -> Any:
        return await asyncio.wait_for(
            self._session.read_resource(uri), _OPERATION_TIMEOUT
        )


class _WorkerHandle(SessionHandle):
    """Forwards ops to a leased warm worker over its inbox; times out client-side."""

    def __init__(self, worker: "_Worker"):
        self.worker = worker
        self.server = worker.server
        self.broken = False

    async def _submit(self, op: SessionOp, timeout: float) -> Any:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.worker.inbox.put_nowait((op, fut))
        closed = asyncio.ensure_future(self.worker.closed.wait())
        try:
            done, _pending = await asyncio.wait(
                {fut, closed}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if fut in done:
                try:
                    return fut.result()
                except BaseException:
                    # The op failed → the worker assumes its session is suspect
                    # and dies; don't hand this session back to the pool.
                    self.broken = True
                    raise
            # Worker died before answering, or we timed out: either way the
            # session is no longer trustworthy.
            self.broken = True
            if closed in done and not fut.done():
                # Surface the real open/close cause (typed McpError) when known.
                raise self.worker.open_error or McpUnreachableError(
                    f"server '{self.server.name}' session closed"
                )
            raise asyncio.TimeoutError()
        finally:
            closed.cancel()

    async def _raw_list_tools(self) -> Any:
        return await self._submit(
            lambda s: asyncio.wait_for(s.list_tools(), _OPERATION_TIMEOUT),
            _OPERATION_TIMEOUT + 5,
        )

    async def _raw_call_tool(
        self, name: str, args: dict[str, Any], timeout: float
    ) -> Any:
        # No inner wait_for: the handle enforces the timeout and poisons the
        # worker on expiry (cancelling the in-flight call_tool).
        return await self._submit(lambda s: s.call_tool(name, args), timeout)

    async def _raw_read_resource(self, uri: str) -> Any:
        return await self._submit(
            lambda s: asyncio.wait_for(s.read_resource(uri), _OPERATION_TIMEOUT),
            _OPERATION_TIMEOUT + 5,
        )


# ── Worker (the actor that owns one warm session) ────────────────────────────

_IDLE = "idle"
_BUSY = "busy"
_DEAD = "dead"
_SHUTDOWN = object()


class _Worker:
    def __init__(
        self,
        pool: "LocalSessionPool",
        key: tuple[uuid.UUID, str],
        user_id: uuid.UUID,
        server: ResolvedServer,
    ):
        self.pool = pool
        self.key = key
        self.user_id = user_id
        self.server = server
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = asyncio.Event()
        self.state = _IDLE
        self.task: asyncio.Task | None = None
        self.born = time.monotonic()
        self._gone = False  # uncounted exactly once
        # The exception that closed the session (e.g. McpLocalBlockedError on a
        # failed open); surfaced to in-flight handles so they keep its real type.
        self.open_error: BaseException | None = None

    @property
    def too_old(self) -> bool:
        return (time.monotonic() - self.born) >= self.pool.max_lifetime

    async def run(self) -> None:
        try:
            async with _open_session(
                self.server, user_id=self.user_id, db=None, throttle=False
            ) as session:
                while True:
                    try:
                        item = await asyncio.wait_for(
                            self.inbox.get(), timeout=self.pool.idle_ttl
                        )
                    except asyncio.TimeoutError:
                        if await self.pool._retire_if_idle(self):
                            return  # idle too long → close session and exit
                        continue  # got leased meanwhile → wait for the op
                    if item is _SHUTDOWN:
                        return
                    op, fut = item
                    try:
                        res = await op(session)
                    except BaseException as exc:  # noqa: BLE001
                        if not fut.done():
                            fut.set_exception(exc)
                        return  # session may be corrupted → drop it
                    if not fut.done():
                        fut.set_result(res)
        except BaseException as exc:  # open failed / cancelled / unexpected
            self.open_error = exc
            self._fail_pending(exc)
            raise
        finally:
            self._fail_pending(self.open_error)
            await self.pool._deregister(self)

    def _fail_pending(self, error: BaseException | None = None) -> None:
        """Reject any queued ops so their handles don't wait for a dead worker."""
        err = error or McpUnreachableError(
            f"server '{self.server.name}' session closed"
        )
        while True:
            try:
                item = self.inbox.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is _SHUTDOWN:
                continue
            _op, fut = item
            if not fut.done():
                fut.set_exception(err)


# ── Pool interface + implementations ─────────────────────────────────────────


class McpSessionPool:
    """Routes MCP ops through a session. ``acquire`` yields a SessionHandle."""

    @asynccontextmanager
    async def acquire(
        self, server: ResolvedServer, *, user_id: uuid.UUID, db: Any = None
    ) -> AsyncIterator[SessionHandle]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield  # noqa: W0101 - makes this an async generator for typing

    async def invalidate(
        self, *, cache_id: str, user_id: uuid.UUID | None = None
    ) -> None:  # pragma: no cover - default no-op
        """Drop any warm sessions for a server (all users, or one user).

        No-op for pools that don't keep warm sessions (``DirectPool`` / off).
        """
        pass

    async def shutdown(self) -> None:  # pragma: no cover - default no-op
        pass


class DirectPool(McpSessionPool):
    """No pooling: open → operate → close per acquire (the pre-pool behavior)."""

    @asynccontextmanager
    async def acquire(
        self, server: ResolvedServer, *, user_id: uuid.UUID, db: Any = None
    ) -> AsyncIterator[SessionHandle]:
        async with _open_session(server, user_id=user_id, db=db) as session:
            yield _DirectHandle(server, session)


class LocalSessionPool(McpSessionPool):
    """Embedded warm-session pool keyed by (user_id, server.cache_id)."""

    def __init__(
        self,
        *,
        max_per_server: int,
        max_per_user: int,
        max_total: int,
        idle_ttl: int,
        max_lifetime: int,
        max_per_server_oauth: int = 1,
    ):
        self.max_per_server = max(1, max_per_server)
        self.max_per_server_oauth = max(1, max_per_server_oauth)
        self.max_per_user = max(1, max_per_user)
        self.max_total = max(1, max_total)
        self.idle_ttl = max(1, idle_ttl)
        self.max_lifetime = max(1, max_lifetime)

        self._idle: dict[tuple, deque] = defaultdict(deque)
        self._all: set[_Worker] = set()
        self._per_key: dict[tuple, int] = defaultdict(int)
        self._per_user: dict[uuid.UUID, int] = defaultdict(int)
        self._total = 0
        self._lock = asyncio.Lock()
        self._closing = False

    def _poolable(self, server: ResolvedServer) -> bool:
        # All auth types are pooled. OAuth is capped at max_per_server_oauth
        # (default 1) so its token refresh stays serialized per (user, server).
        return True

    def _max_per_server(self, server: ResolvedServer) -> int:
        if server.auth_type == "oauth2":
            return self.max_per_server_oauth
        return self.max_per_server

    @asynccontextmanager
    async def acquire(
        self, server: ResolvedServer, *, user_id: uuid.UUID, db: Any = None
    ) -> AsyncIterator[SessionHandle]:
        if self._closing or not self._poolable(server):
            async with _open_session(server, user_id=user_id, db=db) as session:
                yield _DirectHandle(server, session)
            return

        worker = await self._lease(server, user_id)
        if worker is None:
            # At capacity → degrade to a cold one-shot session rather than block.
            logger.debug(
                "MCP pool at capacity for '%s' (user %s); one-shot session",
                server.name,
                user_id,
            )
            async with _open_session(server, user_id=user_id, db=db) as session:
                yield _DirectHandle(server, session)
            return

        handle = _WorkerHandle(worker)
        try:
            yield handle
        finally:
            await self._release(worker, broken=handle.broken)

    async def _lease(
        self, server: ResolvedServer, user_id: uuid.UUID
    ) -> _Worker | None:
        key = (user_id, server.cache_id)
        async with self._lock:
            dq = self._idle.get(key)
            while dq:
                w = dq.popleft()
                if (
                    w._gone
                    or w.state == _DEAD
                    or w.too_old
                    or w.server.config_sig != server.config_sig
                ):
                    # stale/expired/reconfigured → close it and keep looking. A
                    # changed config_sig means the mcp.json entry was edited, so
                    # the warm subprocess runs an outdated command/env → recycle.
                    self._retire_idle_locked(w)
                    continue
                w.state = _BUSY
                return w
            if (
                self._per_key[key] < self._max_per_server(server)
                and self._per_user[user_id] < self.max_per_user
                and self._total < self.max_total
            ):
                w = self._spawn_locked(key, user_id, server)
                w.state = _BUSY
                return w
            return None

    def _spawn_locked(
        self, key: tuple, user_id: uuid.UUID, server: ResolvedServer
    ) -> _Worker:
        w = _Worker(self, key, user_id, server)
        w.task = asyncio.ensure_future(w.run())
        self._all.add(w)
        self._per_key[key] += 1
        self._per_user[user_id] += 1
        self._total += 1
        return w

    async def _release(self, worker: _Worker, *, broken: bool) -> None:
        async with self._lock:
            if broken or worker.too_old or worker.state == _DEAD or self._closing:
                self._kill_locked(worker)
            else:
                worker.state = _IDLE
                self._idle[worker.key].append(worker)

    async def invalidate(
        self, *, cache_id: str, user_id: uuid.UUID | None = None
    ) -> None:
        """Kill warm sessions for ``cache_id`` (all users, or one ``user_id``).

        Called when a server's config/creds change so the next request opens a
        fresh session instead of reusing a warm one bound to stale settings.
        """
        async with self._lock:
            for w in list(self._all):
                if w.key[1] != cache_id:
                    continue
                if user_id is not None and w.key[0] != user_id:
                    continue
                dq = self._idle.get(w.key)
                if dq and w in dq:
                    dq.remove(w)
                self._kill_locked(w)

    async def _retire_if_idle(self, worker: _Worker) -> bool:
        """Called by an idle worker on its TTL timeout. True → it should exit."""
        async with self._lock:
            dq = self._idle.get(worker.key)
            if dq and worker in dq:
                dq.remove(worker)
                self._uncount_locked(worker)  # worker.run will close its session
                return True
            return False  # already leased; keep serving

    async def _deregister(self, worker: _Worker) -> None:
        async with self._lock:
            self._uncount_locked(worker)

    def _kill_locked(self, worker: _Worker) -> None:
        self._uncount_locked(worker)
        if worker.task is not None and not worker.task.done():
            worker.task.cancel()  # cancels any in-flight op + tears down session

    def _retire_idle_locked(self, worker: _Worker) -> None:
        """Drop a stale/expired worker found in the idle list (graceful stop)."""
        self._uncount_locked(worker)
        worker.inbox.put_nowait(_SHUTDOWN)

    def _uncount_locked(self, worker: _Worker) -> None:
        if worker._gone:
            return
        worker._gone = True
        worker.state = _DEAD
        self._all.discard(worker)
        self._per_key[worker.key] = max(0, self._per_key[worker.key] - 1)
        if self._per_key[worker.key] == 0:
            self._per_key.pop(worker.key, None)
        self._per_user[worker.user_id] = max(0, self._per_user[worker.user_id] - 1)
        if self._per_user[worker.user_id] == 0:
            self._per_user.pop(worker.user_id, None)
        self._total = max(0, self._total - 1)
        worker.closed.set()

    async def shutdown(self) -> None:
        async with self._lock:
            self._closing = True
            workers = list(self._all)
        for w in workers:
            if w.task is not None and not w.task.done():
                w.task.cancel()
        tasks = [w.task for w in workers if w.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# ── Module singleton ─────────────────────────────────────────────────────────

_pool: McpSessionPool | None = None


def _build_pool() -> McpSessionPool:
    s = get_settings()
    mode = (s.giga_agent_mcp_pool_mode or "embedded").strip().lower()
    if mode == "off":
        logger.info("MCP session pool disabled (mode=off); using one-shot sessions")
        return DirectPool()
    if mode == "remote":
        logger.warning(
            "MCP pool mode 'remote' is not implemented yet; falling back to embedded"
        )
    return LocalSessionPool(
        max_per_server=s.giga_agent_mcp_pool_max_per_server,
        max_per_server_oauth=s.giga_agent_mcp_pool_max_per_server_oauth,
        max_per_user=s.giga_agent_mcp_pool_max_per_user,
        max_total=s.giga_agent_mcp_pool_max_total,
        idle_ttl=s.giga_agent_mcp_pool_idle_ttl_sec,
        max_lifetime=s.giga_agent_mcp_pool_max_lifetime_sec,
    )


def get_pool() -> McpSessionPool:
    """Process-wide MCP session pool, created lazily on first use."""
    global _pool
    if _pool is None:
        _pool = _build_pool()
    return _pool


async def invalidate_pool_for_server(
    server_id: Any, *, user_id: uuid.UUID | None = None
) -> None:
    """Drop warm pool sessions for a DB server (its ``cache_id`` is ``str(id)``).

    Wired into ``invalidate_tools_cache`` so editing/deleting a server or
    completing an OAuth (re)auth also recycles any warm session bound to the old
    config/creds — not just the tool-discovery cache.
    """
    await get_pool().invalidate(cache_id=str(server_id), user_id=user_id)


async def shutdown_pool() -> None:
    """Close warm sessions on app shutdown / dev-server reload."""
    global _pool
    if _pool is not None:
        await _pool.shutdown()
        _pool = None


def reset_pool() -> None:
    """Drop the singleton without shutting it down (tests only)."""
    global _pool
    _pool = None
