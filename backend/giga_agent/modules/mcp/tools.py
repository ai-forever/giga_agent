"""MCP-specific helpers shared by the MCP source and the MCP HTTP API.

The agent-facing dispatch (``connector_get_info`` / ``connector_call_tool``) now
lives in ``giga_agent.core.agent.connectors``; this module only keeps the
MCP-only bits: MCP Apps widget metadata helpers, the favicon URL convention and
human-readable error text. ``McpToolSource`` (``modules/mcp/source.py``) and the
``/ui-call`` API (``api/servers.py``) import from here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from giga_agent.modules.mcp.errors import (
    McpAuthRequiredError,
    McpError,
    McpLocalBlockedError,
    McpTimeoutError,
    McpUnreachableError,
)
from giga_agent.modules.mcp.resolved import ResolvedServer


def _tool_ui_meta(tool_info: dict[str, Any]) -> dict[str, Any]:
    """The ``meta.ui`` block of an MCP Apps tool, or ``{}``."""
    meta = tool_info.get("meta")
    if not isinstance(meta, dict):
        return {}
    ui = meta.get("ui")
    return ui if isinstance(ui, dict) else {}


def _ui_resource_uri(tool_info: dict[str, Any]) -> str | None:
    """``ui://…`` widget resource a tool instantiates, or ``None``.

    Accepts both the nested (``meta.ui.resourceUri``) and flat
    (``meta["ui/resourceUri"]``) forms some servers emit.
    """
    ui = _tool_ui_meta(tool_info)
    if ui.get("resourceUri"):
        return str(ui["resourceUri"])
    meta = tool_info.get("meta")
    flat = meta.get("ui/resourceUri") if isinstance(meta, dict) else None
    return str(flat) if flat else None


def _visible_to_model(tool_info: dict[str, Any]) -> bool:
    """False for app-only tools (``meta.ui.visibility`` without ``"model"``).

    MCP Apps tools default to ``["model", "app"]``; tools scoped to ``["app"]``
    are invoked by the widget over the host bridge, not by the LLM.
    """
    visibility = _tool_ui_meta(tool_info).get("visibility")
    if isinstance(visibility, list):
        return "model" in visibility
    return True


def _server_icon_url(server: ResolvedServer) -> str | None:
    """A best-effort favicon URL for an MCP server (its registrable domain).

    Mirrors the catalog's icon convention. Used to brand the widget's fullscreen
    header; the frontend falls back to a generic icon if it fails to load.
    """
    if not server.url:
        return None
    host = urlparse(server.url).hostname
    if not host:
        return None
    labels = host.split(".")
    domain = ".".join(labels[-2:]) if len(labels) > 2 else host
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _callable_by_app(tool_info: dict[str, Any]) -> bool:
    """True when an MCP App widget may invoke this tool over the host bridge.

    Default visibility (``["model", "app"]``) includes ``app``; the host
    ``/ui-call`` proxy uses this as a security gate so a widget can only reach
    tools the server explicitly exposes to it.
    """
    visibility = _tool_ui_meta(tool_info).get("visibility")
    if isinstance(visibility, list):
        return "app" in visibility
    return True


def _error_text(server: ResolvedServer, exc: McpError) -> str:
    label = server.name
    if isinstance(exc, McpLocalBlockedError):
        return (
            f"server '{label}' points to a local/private host; local execution is "
            "disabled in this runtime"
        )
    if isinstance(exc, McpAuthRequiredError):
        return f"server '{label}' requires authorization; open MCP settings to connect"
    if isinstance(exc, McpTimeoutError):
        return f"server '{label}' did not respond (timeout)"
    if isinstance(exc, McpUnreachableError):
        return f"server '{label}' is unreachable"
    return f"server '{label}' error: {exc}"
