"""Backend-managed MCP connectors.

See the migration plan: servers are stored in the DB (``McpServer``), tools are
discovered server-side and exposed to the agent through two meta-tools
(``mcp_get_info`` / ``mcp_call_tool``). The browser/localhost MCP flow in
``front/src/components/mcp`` is unrelated and runs in parallel.
"""

from giga_agent.modules.mcp.module import McpModule

__all__ = ["McpModule"]
