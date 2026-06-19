"""Backend MCP client over streamable HTTP.

Short-lived sessions (open → initialize → operate → close) per invocation; no
global pool. Tool discovery is cached in cashews keyed by ``server_id`` and
shared across threads/users to avoid hammering remote servers (decision #5).
"""

from __future__ import annotations

import asyncio
import json
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

# Hard per-operation timeout (mirrors the frontend 15s in mcp-modal.tsx).
_OPERATION_TIMEOUT = 15.0
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
) -> AsyncIterator[ClientSession]:
    """Open and initialize an MCP session, or raise a typed error."""
    _ensure_local_allowed(server)

    # Serialize OAuth sessions per (user, server) so concurrent calls don't
    # race on token refresh and invalidate each other's refresh token.
    if server.auth_type == "oauth2":
        refresh_lock = cache.lock(f"mcp:refresh:{user_id}:{server.cache_id}", expire=30)
    else:
        refresh_lock = nullcontext()

    async with _semaphore_for(server.cache_id), refresh_lock:
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
            raise McpUnreachableError(
                f"server '{server.name}' is unreachable: {exc}"
            ) from exc


def _serialize_tool(tool: Any) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "inputSchema": tool.inputSchema or {},
    }


async def list_server_tools(
    server: ResolvedServer,
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None" = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Return the server's tool catalog, served from a shared cashews cache."""
    key = McpServerRepository.cache_key(server.cache_id)
    if not force_refresh:
        cached = await cache.get(key)
        if cached is not None:
            return cached

    async with _open_session(server, user_id=user_id, db=db) as session:
        result = await asyncio.wait_for(
            session.list_tools(), timeout=_OPERATION_TIMEOUT
        )
    tools = [_serialize_tool(t) for t in result.tools]
    await cache.set(key, tools, expire=_TOOLS_CACHE_TTL)
    return tools


async def call_server_tool(
    server: ResolvedServer,
    tool_name: str,
    args: dict[str, Any],
    *,
    user_id: uuid.UUID,
    db: "AsyncSession | None" = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Call a tool and return ``(content_parts, is_error)``.

    ``content_parts`` are plain dicts compatible with
    :func:`giga_agent.middlewares.tool_result.process_mcp_content`.
    """
    async with _open_session(server, user_id=user_id, db=db) as session:
        result = await asyncio.wait_for(
            session.call_tool(tool_name, args or {}), timeout=_OPERATION_TIMEOUT
        )
    parts = [part.model_dump() for part in (result.content or [])]

    # Guard against absurdly large payloads before normalization/upload.
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
        )
    return parts, bool(result.isError)
