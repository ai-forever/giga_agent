"""Backend MCP client over streamable HTTP.

Short-lived sessions (open → initialize → operate → close) per invocation; no
global pool. Tool discovery is cached in cashews keyed by ``server_id`` and
shared across threads/users to avoid hammering remote servers (decision #5).
"""

from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from contextlib import asynccontextmanager, nullcontext
from typing import TYPE_CHECKING, Any, AsyncIterator

from cashews import cache
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.modules.mcp.auth import build_connection_auth
from giga_agent.modules.mcp.errors import (
    McpError,
    McpLocalBlockedError,
    McpTimeoutError,
    McpUnreachableError,
)
from giga_agent.modules.mcp.resolved import ResolvedServer

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Hard per-operation timeout for connect/initialize/discovery (mirrors the
# frontend 15s in mcp-modal.tsx).
_OPERATION_TIMEOUT = 15.0
# Tool execution gets a longer budget: tools legitimately do slow work (uploads,
# web search, remote rendering). E.g. Excalidraw's export_to_excalidraw uploads
# to excalidraw.com — usually ~2s but it can spike past 15s, and a too-tight
# limit surfaces as a confusing "unreachable" error.
_TOOL_CALL_TIMEOUT = 60.0
_TOOLS_CACHE_TTL = "10m"
# Cap concurrent sessions per server to avoid hammering a remote (the project
# recently added similar per-user session limits elsewhere).
_SESSIONS_PER_SERVER = 4
# Reject absurdly large tool outputs before processing/upload.
_MAX_RESULT_BYTES = 25 * 1024 * 1024

_semaphores: dict[str, asyncio.Semaphore] = {}


def _semaphore_for(server_id: str) -> asyncio.Semaphore:
    sem = _semaphores.get(server_id)
    if sem is None:
        sem = asyncio.Semaphore(_SESSIONS_PER_SERVER)
        _semaphores[server_id] = sem
    return sem


def _ensure_local_allowed(server: ResolvedServer) -> None:
    # stdio servers are inherently local and only ever resolved in local runtime.
    if (
        server.transport == "http"
        and server.is_local
        and not get_settings().giga_agent_runtime_local
    ):
        raise McpLocalBlockedError(
            f"server '{server.name}' points to a local/private host; "
            "local execution is disabled in this runtime"
        )


@asynccontextmanager
async def _open_session(
    server: ResolvedServer,
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None",
    throttle: bool = True,
) -> AsyncIterator[ClientSession]:
    """Open and initialize an MCP session, or raise a typed error.

    ``throttle`` gates the per-server concurrency semaphore. The session pool
    passes ``throttle=False`` because it enforces its own (per-user / per-server
    / total) limits and would otherwise hold the semaphore for the whole warm
    lifetime of the session.
    """
    _ensure_local_allowed(server)

    # NOTE: OAuth token refresh is NOT serialized by a lock here. A per-session
    # lock wrapping the whole ``yield`` is incompatible with the warm-session
    # pool (a session lives up to ~30 min, far past any sane lock TTL) and the
    # mcp SDK's OAuthClientProvider refreshes lazily at request time anyway, not
    # at open. Instead we rely on: max_per_server_oauth=1 (one warm session per
    # (user, server) in-pod → refresh is serialized for free) plus self-heal —
    # a refresh that loses a cross-pod rotation race fails, poisons the worker,
    # and the next open re-reads the fresh token from the DB.
    throttle_cm = _semaphore_for(server.cache_id) if throttle else nullcontext()
    async with throttle_cm:
        try:
            if server.transport == "stdio":
                params = StdioServerParameters(
                    command=server.command or "",
                    args=server.args,
                    env=server.env,
                    cwd=server.cwd,
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(
                            session.initialize(), timeout=_OPERATION_TIMEOUT
                        )
                        yield session
            else:
                if server.db_server is not None:
                    headers, http_auth = await build_connection_auth(
                        server.db_server, user_id=user_id, db=db
                    )
                else:
                    headers, http_auth = server.headers or {}, None
                async with streamablehttp_client(
                    server.url,
                    headers=headers or None,
                    auth=http_auth,
                    timeout=_OPERATION_TIMEOUT,
                ) as (read, write, _get_session_id):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(
                            session.initialize(), timeout=_OPERATION_TIMEOUT
                        )
                        yield session
        except asyncio.TimeoutError as exc:
            raise McpTimeoutError(
                f"server '{server.name}' did not respond in time"
            ) from exc
        except McpError:
            # Typed errors (auth required, local blocked) must surface as-is.
            raise
        except Exception as exc:  # connection refused / DNS / TLS / spawn / protocol
            traceback.print_exc()
            raise McpUnreachableError(
                f"server '{server.name}' is unreachable: {exc}"
            ) from exc


def _extract_resource_text(result: Any, uri: str) -> tuple[str, str]:
    """Pull the first text payload out of a ``read_resource`` result."""
    for content in result.contents or []:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            return text, str(getattr(content, "mimeType", "") or "")
    raise McpError(f"resource '{uri}' has no text content")


async def read_server_resource(
    server: ResolvedServer,
    uri: str,
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None" = None,
) -> tuple[str, str]:
    """Read a text resource (e.g. an MCP App's ``ui://…`` widget HTML).

    Returns ``(text, mime_type)``. Raises :class:`McpError` when the resource
    has no text payload (binary-only resources are not supported here).
    """
    from giga_agent.modules.mcp.pool import get_pool

    async with get_pool().acquire(server, user_id=user_id, db=db) as handle:
        return await handle.read_resource(uri)


def _serialize_tool(tool: Any) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": tool.inputSchema or {},
    }
    # Preserve the tool's ``_meta`` and ``annotations`` — MCP Apps (UI) servers
    # advertise the widget linkage (``meta.ui.resourceUri``) and tool visibility
    # (``meta.ui.visibility``) there. Dropping them blinds the UI layer.
    meta = getattr(tool, "meta", None)
    if meta:
        serialized["meta"] = meta
    annotations = getattr(tool, "annotations", None)
    if annotations is not None:
        serialized["annotations"] = (
            annotations.model_dump()
            if hasattr(annotations, "model_dump")
            else annotations
        )
    return serialized


async def list_server_tools(
    server: ResolvedServer,
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None" = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return the server's tool catalog, served from a shared cashews cache."""
    from giga_agent.modules.mcp.pool import get_pool

    # Fast path: a cache hit needs no session at all, so don't lease one.
    if not force_refresh:
        cached = await cache.get(McpServerRepository.cache_key(server.cache_id))
        if cached is not None:
            return cached

    async with get_pool().acquire(server, user_id=user_id, db=db) as handle:
        return await handle.list_tools(force_refresh=force_refresh)


def _process_call_result(
    result: Any, tool_name: str
) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None]:
    """Normalize a raw ``call_tool`` result into ``(parts, is_error, structured)``.

    ``parts`` are plain dicts compatible with
    :func:`giga_agent.middlewares.tool_result.process_mcp_content`. Oversized
    payloads are discarded with an error part before any normalization/upload.
    """
    # ``exclude_none`` drops unset optionals (``annotations``, ``_meta``, …)
    # instead of emitting them as JSON ``null``. MCP App widgets validate each
    # content block against the zod ``ContentBlockSchema``, where those fields are
    # ``.optional()`` and a literal ``null`` fails the union match.
    parts = [part.model_dump(exclude_none=True) for part in (result.content or [])]
    structured = getattr(result, "structuredContent", None)

    try:
        size = len(json.dumps(parts, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        size = 0
    if size > _MAX_RESULT_BYTES:
        return (
            [
                {
                    "type": "text",
                    "text": (
                        f"[MCP tool '{tool_name}' returned ~{size // (1024 * 1024)}MB, "
                        f"exceeding the {_MAX_RESULT_BYTES // (1024 * 1024)}MB limit; "
                        "result discarded]"
                    ),
                }
            ],
            True,
            None,
        )
    return parts, bool(result.isError), structured


async def call_server_tool(
    server: ResolvedServer,
    tool_name: str,
    args: dict[str, Any],
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None" = None,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any] | None]:
    """Call a tool and return ``(content_parts, is_error, structured_content)``.

    ``structured_content`` is the tool's ``structuredContent`` (machine-readable
    result, e.g. an MCP App's checkpoint id) — ``None`` when the tool returns none.
    """
    from giga_agent.modules.mcp.pool import get_pool

    # When the tool call times out, the (direct-path) teardown may wrap the
    # cancellation as a misleading "unreachable"; track the real cause so we
    # surface a genuine timeout.
    timed_out = False
    try:
        async with get_pool().acquire(server, user_id=user_id, db=db) as handle:
            try:
                return await handle.call_tool(
                    tool_name, args, timeout=_TOOL_CALL_TIMEOUT
                )
            except (asyncio.TimeoutError, TimeoutError):
                timed_out = True
                raise
    except (McpError, asyncio.TimeoutError, TimeoutError) as exc:
        if timed_out or isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            raise McpTimeoutError(
                f"tool '{tool_name}' on '{server.name}' did not respond "
                f"within {int(_TOOL_CALL_TIMEOUT)}s"
            ) from exc
        raise
