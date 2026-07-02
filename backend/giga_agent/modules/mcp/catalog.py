"""Curated catalog of quick-connect remote MCP servers.

A static, read-only registry shipped with the backend (``catalog.json``). Each
entry is a *template* for a managed (DB) MCP server — connecting one just calls
the regular ``POST /servers`` create flow with the entry's url/auth_type and any
user-provided secrets. The catalog itself stores no connection state.

Only remote (HTTP) servers live here; local ``mcp.json`` servers are out of
scope. The bundled file can be overridden with the ``GIGA_AGENT_MCP_CATALOG``
env var (absolute path) for custom deployments.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from giga_agent.core.logging import get_logger
from giga_agent.models.mcp_server import AUTH_TYPES

logger = get_logger(__name__)

_DEFAULT_PATH = Path(__file__).with_name("catalog.json")


def _catalog_path() -> Path:
    override = os.getenv("GIGA_AGENT_MCP_CATALOG")
    return Path(override) if override else _DEFAULT_PATH


class CatalogRequiredField(BaseModel):
    """A secret/parameter the user must provide before connecting.

    ``key`` maps into the server ``settings`` (e.g. ``token`` for bearer auth).
    """

    key: str
    label: str
    secret: bool = False
    placeholder: str | None = None
    help_url: str | None = None


class CatalogEntry(BaseModel):
    id: str
    name: str
    description: str | None = None
    icon: str | None = None  # external URL
    homepage: str | None = None
    categories: list[str] = Field(default_factory=list)
    url: str
    auth_type: str = "none"
    oauth_scope: str | None = None
    requires: list[CatalogRequiredField] = Field(default_factory=list)
    # Maps a server ``settings`` key (e.g. "client_id") to the env var holding
    # its value. The entry is only shown when every referenced env var is set,
    # and the values are injected server-side at connect time (never exposed).
    oauth_client_env: dict[str, str] = Field(default_factory=dict)


def _parse(data: dict) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for raw in data.get("servers") or []:
        try:
            entry = CatalogEntry.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping invalid MCP catalog entry %r: %s", raw, exc)
            continue
        if entry.auth_type not in AUTH_TYPES:
            logger.warning(
                "MCP catalog entry '%s' has unknown auth_type '%s'; skipped",
                entry.id,
                entry.auth_type,
            )
            continue
        if entry.id in seen:
            logger.warning("Duplicate MCP catalog id '%s'; skipped", entry.id)
            continue
        seen.add(entry.id)
        entries.append(entry)
    return entries


@lru_cache(maxsize=1)
def load_catalog() -> list[CatalogEntry]:
    """Parse and validate the bundled catalog (cached for the process)."""
    path = _catalog_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("MCP catalog file not found: %s", path)
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read MCP catalog %s: %s", path, exc)
        return []
    return _parse(data)


def _entry_env_ready(entry: CatalogEntry) -> bool:
    """True when every env var the entry depends on is set (non-empty)."""
    return all(os.getenv(var) for var in entry.oauth_client_env.values())


def visible_catalog() -> list[CatalogEntry]:
    """Catalog filtered to entries whose required env vars are configured.

    Not cached — env-dependent visibility is evaluated per request.
    """
    return [entry for entry in load_catalog() if _entry_env_ready(entry)]


def get_entry(entry_id: str) -> CatalogEntry | None:
    """Return a visible catalog entry by id, or None."""
    return next((e for e in visible_catalog() if e.id == entry_id), None)


def resolve_oauth_env_settings(entry: CatalogEntry) -> dict[str, str]:
    """Read the entry's env-backed OAuth client creds into a settings dict."""
    out: dict[str, str] = {}
    for setting_key, env_var in entry.oauth_client_env.items():
        value = os.getenv(env_var)
        if value:
            out[setting_key] = value
    return out
