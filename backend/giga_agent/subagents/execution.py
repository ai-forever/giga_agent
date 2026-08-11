from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.runnables import RunnableConfig

from giga_agent.core.db import get_session_factory
from giga_agent.models.agent import AgentProfileRepository
from giga_agent.models.mcp_server import McpServerRepository
from giga_agent.subagents.registry import AgentDefinition

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.models.users import UserShort


@dataclass(frozen=True)
class AgentExecutionProfile:
    definition: AgentDefinition
    skill_names: frozenset[str]
    mcp_server_ids: frozenset[uuid.UUID]
    allowed_tool_effects: frozenset[str] = frozenset({"read"})


def configured_subagent_ref(config: RunnableConfig | None) -> str | None:
    if not isinstance(config, dict):
        return None
    value = (config.get("configurable") or {}).get("subagent_id")
    return str(value) if value else None


def execution_module_ids(profile: AgentExecutionProfile) -> frozenset[str]:
    """Return modules that may participate in one sub-agent execution."""
    module_ids = set(profile.definition.modules)
    if profile.definition.source == "builtin":
        # Legacy manifests rely on these infrastructure modules for their
        # requirements and catalog-based MCP resolution.
        module_ids.update({"rag", "skills", "mcp"})
    else:
        if profile.skill_names:
            module_ids.add("skills")
        if profile.mcp_server_ids:
            module_ids.add("mcp")
    return frozenset(module_ids)


async def resolve_execution_profile(
    agent: "BaseAgent",
    user: "UserShort",
    config: RunnableConfig | None,
) -> AgentExecutionProfile | None:
    """Resolve the server-owned profile from only ``subagent_id``.

    No caller-provided modules, tools, connectors, LLM, or prompt are trusted.
    This helper is deliberately used at both bind and execution boundaries.
    """

    ref = configured_subagent_ref(config)
    if ref is None:
        return None
    factory = await get_session_factory()
    async with factory() as session:
        definition = await agent.subagent_registry.resolve(
            session,
            user,
            ref,
            require_runnable=True,
            config=config,
        )
        if definition is None:
            raise ValueError(f"Subagent {ref!r} is unavailable or needs setup")

        skill_names: set[str] = set()
        mcp_ids: set[uuid.UUID] = set()
        repository = AgentProfileRepository(session)
        if definition.source == "custom":
            skill_names.update(definition.skill_names)
            mcp_ids.update(definition.mcp_server_ids)
        elif definition.profile_id is not None:
            for binding in await repository.skill_bindings(definition.profile_id):
                if binding.skill_id is not None:
                    skill_names.add(binding.requirement_name)
            for binding in await repository.connector_bindings(definition.profile_id):
                if binding.mcp_server_id is not None:
                    mcp_ids.add(binding.mcp_server_id)
        else:
            # A built-in without an override can safely auto-bind only an
            # unambiguous catalog entry.
            servers = await McpServerRepository(session).get_readable_for_user(
                user.id, only_active=True
            )
            for catalog_id in definition.connectors:
                candidates = [s for s in servers if s.catalog_id == catalog_id]
                if len(candidates) == 1:
                    mcp_ids.add(candidates[0].id)
        return AgentExecutionProfile(
            definition=definition,
            skill_names=frozenset(skill_names),
            mcp_server_ids=frozenset(mcp_ids),
            allowed_tool_effects=frozenset(definition.allowed_tool_effects),
        )


def tool_ref(module_id: str, tool_name: str) -> str:
    return f"{module_id}/{tool_name}"


def direct_tool_allowed(
    profile: AgentExecutionProfile,
    module_id: str,
    tool: Any,
    *,
    parent_plan_mode: bool = False,
) -> bool:
    from giga_agent.core.agent.tool_policy import (
        ToolEffect,
        effective_tool_effect,
        resolve_tool_policy,
    )

    policy = resolve_tool_policy(tool)
    if policy is None:
        return False
    effect = effective_tool_effect(policy)
    if effect is None:
        return False
    if parent_plan_mode:
        return effect is ToolEffect.READ
    if getattr(profile.definition, "source", "builtin") == "custom":
        return effect.value in profile.allowed_tool_effects

    ref = tool_ref(module_id, tool.name)
    rules = profile.definition.tools
    if ref in rules.deny:
        return False
    if effect is ToolEffect.READ:
        return True
    return ref in rules.allow
