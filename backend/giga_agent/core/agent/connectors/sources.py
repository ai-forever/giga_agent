"""The :class:`ToolSource` abstraction and its in-process module implementation.

A :class:`ToolSource` exposes a named bundle of tools that the model invokes
lazily via the connector meta-tools. :class:`ModuleToolSource` wraps the
``BaseTool``s of a native module flagged ``lazy_tools`` — the same tools that
would otherwise be bound directly. MCP servers provide their own source
(``giga_agent.modules.mcp.source.McpToolSource``).

Output of a call is normalized into :class:`ToolCallOutcome` so the connector
meta-tools can serialize both kinds of source identically. ``inner_name`` /
``inner_extras`` carry the wrapped tool's identity and ``extras`` so the
``ToolResultMiddleware`` applies that tool's semantics (``not_process`` /
``not_compress`` / result-file naming) rather than the meta-tool's.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from giga_agent.core.agent.tool_invoke import invoke_inner_tool
from giga_agent.core.agent.tool_policy import ToolPolicy, resolve_tool_policy

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.models.users import UserShort


# --------------------------------------------------------------------------- #
# Shared tool-spec helpers (used by ModuleToolSource and McpToolSource).
# --------------------------------------------------------------------------- #


def example_for_prop(prop: dict[str, Any]) -> Any:
    """A plausible example value for a single JSON-schema property."""
    if not isinstance(prop, dict):
        return None
    if "enum" in prop and isinstance(prop["enum"], list) and prop["enum"]:
        return prop["enum"][0]
    if "default" in prop:
        return prop["default"]
    prop_type = prop.get("type")
    if isinstance(prop_type, list):
        prop_type = next((t for t in prop_type if t != "null"), None)
    if prop_type == "string":
        return "example"
    if prop_type == "integer":
        return 1
    if prop_type == "number":
        return 1
    if prop_type == "boolean":
        return True
    if prop_type == "array":
        items = prop.get("items") if isinstance(prop.get("items"), dict) else {}
        return [example_for_prop(items)] if items else []
    if prop_type == "object":
        return {}
    return None


def build_args_example(schema: dict[str, Any], required: list[str]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    keys = required or list(properties.keys())
    return {key: example_for_prop(properties.get(key, {})) for key in keys}


@dataclass
class ToolSpec:
    """Model-facing description of a single tool within a source."""

    name: str
    description: str
    required: list[str] = field(default_factory=list)
    params_example: str = "{}"
    policy: ToolPolicy | None = None

    @classmethod
    def from_schema(
        cls,
        *,
        name: str,
        description: str,
        schema: dict[str, Any] | None,
        policy: ToolPolicy | None = None,
    ) -> "ToolSpec":
        schema = schema or {}
        required = schema.get("required") if isinstance(schema, dict) else None
        required = [str(r) for r in required] if isinstance(required, list) else []
        description = (description or "").strip()
        if len(description) > 400:
            description = description[:400] + "…"
        return cls(
            name=name,
            description=description,
            required=required,
            # JSON-строка, как ожидает params в connector_call_tool.
            params_example=json.dumps(
                build_args_example(schema, required), ensure_ascii=False
            ),
            policy=policy,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "params_example": self.params_example,
        }


@dataclass
class ToolCallOutcome:
    """Uniform result of calling a tool through any :class:`ToolSource`."""

    content: Any
    attachments: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    # Extra attachment the frontend host bridge needs (e.g. an MCP Apps widget).
    extra_attachment: dict[str, Any] | None = None
    # Identity/extras of the wrapped tool, for ToolResultMiddleware (see §8).
    inner_name: str | None = None
    inner_extras: dict[str, Any] | None = None
    # Placement signal from the inner tool: render the result as a standalone
    # widget OUTSIDE the collapsible agent run (см. build_widget_tool_message).
    response_widget: bool = False


@runtime_checkable
class ToolSource(Protocol):
    """A named bundle of tools the model invokes lazily via the meta-tools."""

    name: str
    label: str
    icon: str | None

    async def list_tools(self, *, user_id: uuid.UUID) -> list[ToolSpec]: ...

    async def call_tool(
        self,
        tool: str,
        params: dict[str, Any],
        runtime: ToolRuntime,
        *,
        user_id: uuid.UUID,
    ) -> ToolCallOutcome: ...


# --------------------------------------------------------------------------- #
# Native module source.
# --------------------------------------------------------------------------- #


class ModuleToolSource:
    """Wraps the ``BaseTool``s of a ``lazy_tools`` module as a single source."""

    def __init__(
        self,
        name: str,
        label: str,
        icon: str | None,
        tools: list[BaseTool],
    ) -> None:
        self.name = name
        self.label = label or name
        self.icon = icon or None
        self._tools = list(tools)
        self._by_name = {t.name: t for t in self._tools}

    async def list_tools(self, *, user_id: uuid.UUID) -> list[ToolSpec]:
        _ = user_id
        specs: list[ToolSpec] = []
        for t in self._tools:
            try:
                schema = t.tool_call_schema.model_json_schema()
            except Exception:  # noqa: BLE001 — schema introspection is best-effort
                schema = {}
            specs.append(
                ToolSpec.from_schema(
                    name=t.name,
                    description=t.description or "",
                    schema=schema,
                    policy=resolve_tool_policy(t),
                )
            )
        return specs

    async def call_tool(
        self,
        tool: str,
        params: dict[str, Any],
        runtime: ToolRuntime,
        *,
        user_id: uuid.UUID,
    ) -> ToolCallOutcome:
        _ = user_id
        target = self._by_name.get(tool)
        if target is None:
            available = ", ".join(self._by_name) or "<нет>"
            return ToolCallOutcome(
                content=(
                    f"connector '{self.name}' has no tool '{tool}'; "
                    f"available: {available}"
                ),
                is_error=True,
            )

        result = await invoke_inner_tool(target, params, runtime)
        inner_extras = dict(target.extras or {})

        if isinstance(result, ToolMessage):
            inner_ak = result.additional_kwargs or {}
            attachments = inner_ak.get("tool_attachments", [])
            return ToolCallOutcome(
                content=result.content,
                attachments=list(attachments) if attachments else [],
                is_error=result.status == "error",
                inner_name=target.name,
                inner_extras=inner_extras,
                response_widget=bool(inner_ak.get("response_widget")),
            )

        return ToolCallOutcome(
            content=result,
            is_error=False,
            inner_name=target.name,
            inner_extras=inner_extras,
        )


class RestrictedToolSource:
    """Fail-closed view of a source for one resolved subagent profile."""

    def __init__(
        self, source: ToolSource, profile: Any, ref_prefix: str, plan_mode: bool
    ):
        self._source = source
        self._profile = profile
        self._ref_prefix = ref_prefix
        self._plan_mode = plan_mode
        self.name = source.name
        self.label = source.label
        self.icon = source.icon

    def _allowed(self, spec: ToolSpec, params: dict[str, Any] | None = None) -> bool:
        from giga_agent.core.agent.tool_policy import ToolEffect, effective_tool_effect

        if spec.policy is None:
            return False
        effect = effective_tool_effect(spec.policy, params)
        if effect is None:
            return False
        if self._plan_mode:
            return effect is ToolEffect.READ
        if getattr(self._profile.definition, "source", "builtin") == "custom":
            return effect.value in self._profile.allowed_tool_effects

        ref = f"{self._ref_prefix}/{spec.name}"
        rules = self._profile.definition.tools
        if ref in rules.deny:
            return False
        return effect is ToolEffect.READ or ref in rules.allow

    async def list_tools(self, *, user_id: uuid.UUID) -> list[ToolSpec]:
        return [
            spec
            for spec in await self._source.list_tools(user_id=user_id)
            if self._allowed(spec)
        ]

    async def call_tool(
        self,
        tool: str,
        params: dict[str, Any],
        runtime: ToolRuntime,
        *,
        user_id: uuid.UUID,
    ) -> ToolCallOutcome:
        spec = next(
            (
                item
                for item in await self._source.list_tools(user_id=user_id)
                if item.name == tool
            ),
            None,
        )
        if spec is None or not self._allowed(spec, params):
            return ToolCallOutcome(
                content=f"tool '{self.name}/{tool}' is not allowed for this subagent",
                is_error=True,
            )
        return await self._source.call_tool(tool, params, runtime, user_id=user_id)


# --------------------------------------------------------------------------- #
# Aggregation + lookup.
# --------------------------------------------------------------------------- #


async def collect_sources(
    agent: "BaseAgent",
    user: "UserShort | None",
    config: Any | None,
) -> list[ToolSource]:
    """All tool sources available to ``user``, honoring disabled modules.

    Walks ``agent.all_modules`` and collects each module's
    :meth:`BaseModule.get_tool_sources`. Modules the user disabled (via
    ``config.configurable.disabled_modules`` or ``user.settings.disabledModules``)
    contribute nothing.
    """
    if user is None:
        return []
    # Lazy import: base.py imports graph_factory which imports this module.
    from giga_agent.core.agent.base import _disabled_module_ids

    from giga_agent.subagents.execution import (
        execution_module_ids,
        resolve_execution_profile,
    )

    execution = await resolve_execution_profile(agent, user, config)
    disabled = _disabled_module_ids(config, user)
    sources: list[ToolSource] = []
    for module in agent.all_modules:
        if module.id in disabled:
            continue
        if execution is not None:
            if module.id not in execution_module_ids(execution):
                continue
        module_sources = await module.get_tool_sources(user, agent, config=config)
        if execution is None:
            sources.extend(module_sources)
            continue
        plan_mode = bool(
            ((config or {}).get("configurable") or {}).get("subagent_parent_plan_mode")
        )
        for source in module_sources:
            if module.id == "mcp":
                server = getattr(source, "_server", None)
                db_server = getattr(server, "db_server", None)
                if db_server is None or db_server.id not in execution.mcp_server_ids:
                    continue
                prefix = f"connector:{db_server.catalog_id or db_server.id}"
            else:
                prefix = module.id
            sources.append(RestrictedToolSource(source, execution, prefix, plan_mode))
    return sources


def match_source(sources: list[ToolSource], ref: str) -> ToolSource | None:
    ref_norm = (ref or "").strip().lower()
    for source in sources:
        if source.name.strip().lower() == ref_norm:
            return source
    for source in sources:
        if (source.label or "").strip().lower() == ref_norm:
            return source
    return None
