"""Unified server descriptor used by the MCP client.

Both DB-backed servers (:class:`McpServer`) and file-based local servers (from
``.giga_agent/mcp.json``) are normalized into a :class:`ResolvedServer` so the
client can open a session uniformly regardless of source/transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from giga_agent.models.mcp_server import McpServer


@dataclass
class ResolvedServer:
    name: str  # identifier the model/UI uses (db: name/id; file: local_<ns>)
    transport: str  # "http" | "stdio"
    is_local: bool
    cache_id: str  # stable id for the cashews discovery key
    source: str  # "db" | "file"
    auth_type: str = "none"
    # http
    url: str | None = None
    headers: dict[str, str] | None = None
    # stdio
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    # back-reference to the DB row (for bearer/oauth auth resolution)
    db_server: "McpServer | None" = None


def resolve_db_server(server: "McpServer") -> ResolvedServer:
    return ResolvedServer(
        name=server.name or str(server.id),
        transport="http",
        is_local=bool(server.is_local),
        cache_id=str(server.id),
        source="db",
        auth_type=server.auth_type or "none",
        url=server.url,
        db_server=server,
    )
