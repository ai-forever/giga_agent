"""Safety metadata and plan-mode enforcement for agent tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

GIGA_AGENT_EXTRAS_KEY = "giga_agent"
PROVIDER_POLICY_KEY = "_giga_agent"
PLAN_MODE = "plan"
BLOCKED_ERROR_CODE = "tool_not_allowed_in_plan"
CLI_PLAN_MODE_TOOL_NAMES = frozenset({"python", "shell"})


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    DELEGATED = "delegated"


class ToolPlanMode(StrEnum):
    AUTO = "auto"
    ALLOW = "allow"
    DENY = "deny"


class ToolConfirmation(StrEnum):
    NEVER = "never"
    ALWAYS = "always"
    CONDITIONAL = "conditional"


ToolEffectResolver = Callable[[Mapping[str, Any]], ToolEffect]


@dataclass(frozen=True)
class ToolPolicy:
    effect: ToolEffect
    plan_mode: ToolPlanMode = ToolPlanMode.AUTO
    confirmation: ToolConfirmation = ToolConfirmation.NEVER
    effect_resolver: ToolEffectResolver | None = None


def tool_extras(
    effect: ToolEffect | str,
    *,
    plan_mode: ToolPlanMode | str = ToolPlanMode.AUTO,
    confirmation: ToolConfirmation | str = ToolConfirmation.NEVER,
    effect_resolver: ToolEffectResolver | None = None,
    **existing: Any,
) -> dict[str, Any]:
    """Build ``BaseTool.extras`` while preserving existing internal metadata."""
    policy: dict[str, Any] = {
        "effect": ToolEffect(effect).value,
        "plan_mode": ToolPlanMode(plan_mode).value,
        "confirmation": ToolConfirmation(confirmation).value,
    }
    if effect_resolver is not None:
        policy["effect_resolver"] = effect_resolver
    return {**existing, GIGA_AGENT_EXTRAS_KEY: policy}


def policy_to_mapping(policy: ToolPolicy) -> dict[str, Any]:
    result: dict[str, Any] = {
        "effect": policy.effect.value,
        "plan_mode": policy.plan_mode.value,
        "confirmation": policy.confirmation.value,
    }
    if policy.effect_resolver is not None:
        result["effect_resolver"] = policy.effect_resolver
    return result


def _parse_policy(raw: Any) -> ToolPolicy | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        effect = ToolEffect(raw["effect"])
        plan_mode = ToolPlanMode(raw.get("plan_mode", ToolPlanMode.AUTO))
        confirmation = ToolConfirmation(raw.get("confirmation", ToolConfirmation.NEVER))
    except (KeyError, TypeError, ValueError):
        return None
    resolver = raw.get("effect_resolver")
    if resolver is not None and not callable(resolver):
        return None
    return ToolPolicy(
        effect=effect,
        plan_mode=plan_mode,
        confirmation=confirmation,
        effect_resolver=resolver,
    )


def resolve_tool_policy(tool_or_mapping: Any) -> ToolPolicy | None:
    """Resolve policy from a ``BaseTool``, provider dict, extras, or raw policy."""
    if isinstance(tool_or_mapping, ToolPolicy):
        return tool_or_mapping

    if isinstance(tool_or_mapping, BaseTool):
        extras = tool_or_mapping.extras or {}
        return _parse_policy(extras.get(GIGA_AGENT_EXTRAS_KEY))

    if isinstance(tool_or_mapping, Mapping):
        if PROVIDER_POLICY_KEY in tool_or_mapping:
            return _parse_policy(tool_or_mapping.get(PROVIDER_POLICY_KEY))
        nested = tool_or_mapping.get(GIGA_AGENT_EXTRAS_KEY)
        if nested is not None:
            return _parse_policy(nested)
        extras = tool_or_mapping.get("extras")
        if isinstance(extras, Mapping):
            nested = extras.get(GIGA_AGENT_EXTRAS_KEY)
            if nested is not None:
                return _parse_policy(nested)
        if "effect" in tool_or_mapping:
            return _parse_policy(tool_or_mapping)
    return None


def effective_tool_effect(
    policy: ToolPolicy,
    args: Mapping[str, Any] | None = None,
) -> ToolEffect | None:
    if policy.effect_resolver is None or args is None:
        return policy.effect
    try:
        resolved = policy.effect_resolver(args)
        effect = ToolEffect(resolved)
    except Exception:  # noqa: BLE001 - a faulty resolver must fail closed
        return None
    return effect


def _tool_name(tool_or_mapping: Any) -> str | None:
    if isinstance(tool_or_mapping, BaseTool):
        return tool_or_mapping.name
    if isinstance(tool_or_mapping, Mapping):
        name = tool_or_mapping.get("name")
        return name if isinstance(name, str) else None
    return None


def is_tool_allowed(
    tool_or_policy: Any,
    mode: str | None,
    *,
    args: Mapping[str, Any] | None = None,
    runtime_mode: str | None = None,
) -> bool:
    """Return whether a tool may be exposed/executed in the current mode."""
    if mode != PLAN_MODE:
        return True
    if (
        runtime_mode != "cli"
        and _tool_name(tool_or_policy) in CLI_PLAN_MODE_TOOL_NAMES
    ):
        return False
    policy = resolve_tool_policy(tool_or_policy)
    if policy is None:
        return False
    if policy.plan_mode is ToolPlanMode.DENY:
        return False
    if policy.plan_mode is ToolPlanMode.ALLOW:
        return True
    effect = effective_tool_effect(policy, args)
    return effect in (ToolEffect.READ, ToolEffect.DELEGATED)


def filter_tools_for_mode(
    tools: list[Any],
    mode: str | None,
    *,
    runtime_mode: str | None = None,
) -> list[Any]:
    if mode != PLAN_MODE:
        return list(tools)
    return [
        tool
        for tool in tools
        if is_tool_allowed(tool, mode, runtime_mode=runtime_mode)
    ]


def blocked_tool_message(tool_name: str, tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        status="error",
        content=f"Инструмент '{tool_name}' недоступен в режиме планирования.",
        tool_call_id=tool_call_id,
        name=tool_name,
        additional_kwargs={
            "error_code": BLOCKED_ERROR_CODE,
            "tool_name": tool_name,
            "mode": PLAN_MODE,
        },
    )


def policy_from_mcp_annotations(annotations: Any) -> ToolPolicy:
    """Map trusted MCP annotations using their pessimistic protocol defaults."""
    raw = annotations if isinstance(annotations, Mapping) else {}
    if raw.get("readOnlyHint") is True:
        effect = ToolEffect.READ
    elif raw.get("destructiveHint", True) is True:
        effect = ToolEffect.DESTRUCTIVE
    else:
        effect = ToolEffect.WRITE
    return ToolPolicy(effect=effect)


def attach_provider_policy(
    definition: Mapping[str, Any],
    policy: ToolPolicy,
) -> dict[str, Any]:
    result = deepcopy(dict(definition))
    result[PROVIDER_POLICY_KEY] = policy_to_mapping(policy)
    return result


_KNOWN_PROVIDER_TOOL_POLICIES: dict[str, ToolPolicy] = {
    "web_search": ToolPolicy(effect=ToolEffect.READ),
    "web_search_preview": ToolPolicy(effect=ToolEffect.READ),
}


def annotate_known_provider_tool(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Attach policy for provider-native tool definitions known to GigaAgent."""
    if PROVIDER_POLICY_KEY in definition:
        return deepcopy(dict(definition))
    tool_type = definition.get("type")
    policy = (
        _KNOWN_PROVIDER_TOOL_POLICIES.get(str(tool_type))
        if tool_type is not None
        else None
    )
    return (
        attach_provider_policy(definition, policy)
        if policy is not None
        else deepcopy(dict(definition))
    )
