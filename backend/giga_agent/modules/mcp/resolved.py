"""Unified server descriptor used by the MCP client.

Both DB-backed servers (:class:`McpServer`) and file-based local servers (from
``.giga_agent/mcp.json``) are normalized into a :class:`ResolvedServer` so the
client can open a session uniformly regardless of source/transport.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from giga_agent.models.mcp_server import McpServer


def config_sig(cfg: dict) -> str:
    """Stable hash of a server's connection config; changes iff the config is edited.

    Shared by file servers (``local_config``) and DB servers so both hash
    identically and deterministically across pods (each pod re-resolves the
    server per request and compares sigs in the pool's ``_lease``).
    """
    raw = json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def base_name_from_url(url: str | None) -> str | None:
    """Derive a connector name from a remote MCP URL: its hostname.

    ``https://api.arcade.dev/mcp/gw_…`` → ``api.arcade.dev``. Returns ``None``
    when no hostname can be parsed. Used as the model-facing name (a hint about
    what the MCP is) when a server has no explicit name assigned.
    """
    if not url:
        return None
    return urlparse(url).hostname or None


def _path_discriminator(url: str | None) -> str | None:
    """Last URL path segment, used to disambiguate same-host servers."""
    if not url:
        return None
    path = urlparse(url).path.strip("/")
    if not path:
        return None
    return path.split("/")[-1] or None


def disambiguate_names(servers: "list[ResolvedServer]") -> None:
    """Make ``name`` unique across *servers* (mutates in place).

    Several servers can share a host — the unnamed-server fallback derives the
    name from the URL hostname, so two MCPs on ``api.arcade.dev`` would collide
    and the model-facing connector name would be ambiguous. Colliding names get
    a URL path segment appended (``api.arcade.dev`` →
    ``api.arcade.dev/gw_3Fd…``), then a numeric suffix if that is still not
    enough.
    """
    counts = Counter(s.name.lower() for s in servers)
    used = {s.name.lower() for s in servers if counts[s.name.lower()] == 1}
    for s in servers:
        if counts[s.name.lower()] == 1:
            continue
        disc = _path_discriminator(s.url)
        candidate = f"{s.name}/{disc}" if disc else s.name
        base = candidate
        suffix = 2
        while candidate.lower() in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate.lower())
        s.name = candidate


@dataclass
class ResolvedServer:
    name: str  # identifier the model/UI uses (db: name/id; file: local_<ns>)
    transport: str  # "http" | "stdio"
    is_local: bool
    cache_id: str  # stable id for the cashews discovery key
    source: str  # "db" | "file"
    auth_type: str = "none"
    # Content fingerprint of the source config (file servers only). When this
    # changes — i.e. the mcp.json entry was edited — the session pool recycles
    # the warm worker instead of serving from the now-stale subprocess. ``None``
    # for DB servers (they invalidate through their own repository path).
    config_sig: str | None = None
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
    # Hash the connection *identity* only: url / auth_type / is_local / settings.
    # For bearer, ``settings`` carries the token+header (a token edit MUST recycle
    # the warm session); for oauth2 it carries the client identity (client_id /
    # secret / scope). The OAuth access/refresh tokens live in a separate table
    # (``core_oauth_connections``), NOT in ``settings`` — so this sig is naturally
    # immune to token-refresh churn, and only changes when the server is edited.
    sig = config_sig(
        {
            "url": server.url,
            "auth_type": server.auth_type or "none",
            "is_local": bool(server.is_local),
            "settings": server.settings or {},
        }
    )
    return ResolvedServer(
        name=server.name or base_name_from_url(server.url) or str(server.id),
        transport="http",
        is_local=bool(server.is_local),
        cache_id=str(server.id),
        source="db",
        auth_type=server.auth_type or "none",
        config_sig=sig,
        url=server.url,
        db_server=server,
    )
