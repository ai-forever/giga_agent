"""Typed errors for backend MCP execution.

All of these are caught in the meta-tools and turned into agent-facing tool
results (never raised to crash the run).
"""

from __future__ import annotations


class McpError(Exception):
    """Base class for backend MCP errors."""


class McpLocalBlockedError(McpError):
    """Server points at a local/private host but GIGA_AGENT_RUNTIME_LOCAL is off."""


class McpTimeoutError(McpError):
    """The MCP server did not respond within the allotted time."""


class McpUnreachableError(McpError):
    """The MCP server could not be reached (connection refused / DNS / TLS)."""


class McpAuthRequiredError(McpError):
    """The server needs interactive authorization that is not yet completed."""


class McpToolError(McpError):
    """The MCP server returned an error result for a tool call."""
