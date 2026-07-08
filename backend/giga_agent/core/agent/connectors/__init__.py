"""Connectors: the agent-level dispatch over lazily-delivered tool sources.

This is core agent infrastructure (like ``think`` / ``multi_tool_use``), not a
removable module. A :class:`ToolSource` is anything that can list its tools and
call one by name; both MCP servers and native modules flagged ``lazy_tools`` feed
into it. The model reaches every source through two built-in meta-tools,
``connector_get_info`` and ``connector_call_tool``, instead of binding each tool
directly — which keeps the bound tool list small for weaker models.
"""

from giga_agent.core.agent.connectors.sources import (
    ModuleToolSource,
    ToolCallOutcome,
    ToolSource,
    ToolSpec,
    collect_sources,
    match_source,
)
from giga_agent.core.agent.connectors.tools import (
    connector_call_tool,
    connector_get_info,
)

__all__ = [
    "ModuleToolSource",
    "ToolCallOutcome",
    "ToolSource",
    "ToolSpec",
    "collect_sources",
    "match_source",
    "connector_call_tool",
    "connector_get_info",
]
