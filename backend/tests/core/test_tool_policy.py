"""Unit and inventory tests for tool safety policy metadata."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from giga_agent.core.agent.multi_tool_use import expand_multi_tool_use
from giga_agent.core.agent.tool_invoke import invoke_inner_tool
from giga_agent.core.agent.tool_node import AgentToolRuntime, ToolNode
from giga_agent.core.agent.tool_policy import (
    BLOCKED_ERROR_CODE,
    GIGA_AGENT_EXTRAS_KEY,
    ToolConfirmation,
    ToolEffect,
    ToolPlanMode,
    annotate_known_provider_tool,
    blocked_tool_message,
    is_tool_allowed,
    policy_from_mcp_annotations,
    resolve_tool_policy,
    tool_extras,
)
from giga_agent.middlewares.tool_result import ToolResultMiddleware
from langchain_core.messages import AIMessage
from langchain_core.tools import tool


def test_tool_extras_preserves_existing_metadata() -> None:
    extras = tool_extras(
        ToolEffect.WRITE,
        confirmation=ToolConfirmation.CONDITIONAL,
        module_id="io",
        repl_skip=True,
        args_hack={"path": "file_path"},
    )

    assert extras["module_id"] == "io"
    assert extras["repl_skip"] is True
    assert extras["args_hack"] == {"path": "file_path"}
    assert extras[GIGA_AGENT_EXTRAS_KEY] == {
        "effect": "write",
        "plan_mode": "auto",
        "confirmation": "conditional",
    }


def test_policy_parsing_and_invalid_values() -> None:
    policy = resolve_tool_policy(
        tool_extras(
            ToolEffect.READ,
            plan_mode=ToolPlanMode.ALLOW,
            confirmation=ToolConfirmation.ALWAYS,
        )
    )
    assert policy is not None
    assert policy.effect is ToolEffect.READ
    assert policy.plan_mode is ToolPlanMode.ALLOW
    assert policy.confirmation is ToolConfirmation.ALWAYS

    assert resolve_tool_policy({"effect": "unknown"}) is None
    assert resolve_tool_policy({"plan_mode": "auto"}) is None
    assert resolve_tool_policy({"effect": "read", "effect_resolver": 42}) is None


@pytest.mark.parametrize(
    ("effect", "allowed"),
    [
        (ToolEffect.READ, True),
        (ToolEffect.WRITE, False),
        (ToolEffect.DESTRUCTIVE, False),
        (ToolEffect.DELEGATED, True),
    ],
)
def test_plan_mode_auto_rules(effect: ToolEffect, allowed: bool) -> None:
    assert is_tool_allowed(tool_extras(effect), "plan") is allowed


def test_plan_mode_overrides_and_normal_mode_compatibility() -> None:
    write_allowed = tool_extras(ToolEffect.WRITE, plan_mode=ToolPlanMode.ALLOW)
    read_denied = tool_extras(ToolEffect.READ, plan_mode=ToolPlanMode.DENY)

    assert is_tool_allowed(write_allowed, "plan")
    assert not is_tool_allowed(read_denied, "plan")
    assert not is_tool_allowed({}, "plan")

    assert is_tool_allowed(write_allowed, "normal")
    assert is_tool_allowed(read_denied, "normal")
    assert is_tool_allowed({}, "normal")


def test_effect_resolver_uses_arguments_and_fails_closed() -> None:
    seen: list[dict[str, object]] = []

    def resolver(args):
        seen.append(dict(args))
        return ToolEffect.READ if args["preview"] else ToolEffect.WRITE

    extras = tool_extras(ToolEffect.WRITE, effect_resolver=resolver)
    assert is_tool_allowed(extras, "plan", args={"preview": True})
    assert not is_tool_allowed(extras, "plan", args={"preview": False})
    assert seen == [{"preview": True}, {"preview": False}]

    def raises(_args):
        raise RuntimeError("broken evaluator")

    assert not is_tool_allowed(
        tool_extras(ToolEffect.READ, effect_resolver=raises),
        "plan",
        args={},
    )
    assert not is_tool_allowed(
        tool_extras(ToolEffect.READ, effect_resolver=lambda _args: "invalid"),
        "plan",
        args={},
    )


def test_known_provider_tool_and_unknown_default() -> None:
    known = annotate_known_provider_tool({"type": "web_search"})
    unknown = annotate_known_provider_tool({"type": "vendor_mutation"})

    assert resolve_tool_policy(known).effect is ToolEffect.READ
    assert is_tool_allowed(known, "plan")
    assert resolve_tool_policy(unknown) is None
    assert not is_tool_allowed(unknown, "plan")
    assert is_tool_allowed(unknown, "normal")


@pytest.mark.parametrize(
    ("annotations", "effect"),
    [
        ({"readOnlyHint": True, "destructiveHint": True}, ToolEffect.READ),
        ({"readOnlyHint": False, "destructiveHint": False}, ToolEffect.WRITE),
        ({"destructiveHint": True}, ToolEffect.DESTRUCTIVE),
        ({}, ToolEffect.DESTRUCTIVE),
        (None, ToolEffect.DESTRUCTIVE),
    ],
)
def test_mcp_annotation_mapping(annotations, effect: ToolEffect) -> None:
    assert policy_from_mcp_annotations(annotations).effect is effect


def test_blocked_message_contract() -> None:
    message = blocked_tool_message("write_file", "call-1")

    assert message.status == "error"
    assert message.content == (
        "Инструмент 'write_file' недоступен в режиме планирования."
    )
    assert message.tool_call_id == "call-1"
    assert message.additional_kwargs == {
        "error_code": BLOCKED_ERROR_CODE,
        "tool_name": "write_file",
        "mode": "plan",
    }


@pytest.mark.anyio
async def test_inner_tool_execution_guard_blocks_write_but_runs_read() -> None:
    calls: list[str] = []

    @tool(extras=tool_extras(ToolEffect.READ))
    def inspect_value() -> str:
        """Inspect a value."""
        calls.append("read")
        return "read"

    @tool(extras=tool_extras(ToolEffect.WRITE))
    def change_value() -> str:
        """Change a value."""
        calls.append("write")
        return "write"

    runtime = SimpleNamespace(
        state={"mode": "plan"},
        config={},
        tool_call_id="inner-1",
    )

    assert await invoke_inner_tool(inspect_value, {}, runtime) == "read"
    blocked = await invoke_inner_tool(change_value, {}, runtime)
    assert blocked.status == "error"
    assert blocked.additional_kwargs["error_code"] == BLOCKED_ERROR_CODE
    assert calls == ["read"]


@pytest.mark.anyio
async def test_tool_node_blocks_fabricated_write_call_after_multi_tool_expansion() -> (
    None
):
    calls: list[str] = []

    @tool(extras=tool_extras(ToolEffect.WRITE))
    def change_value(value: int) -> str:
        """Change a value."""
        calls.append(str(value))
        return "changed"

    node = ToolNode([change_value], agent=SimpleNamespace())
    node._tools_by_name = {change_value.name: change_value}
    bundled = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "bundle-1",
                "name": "multi_tool_use",
                "args": {
                    "tool_uses": [
                        {
                            "recipient_name": "change_value",
                            "parameters": '{"value": 7}',
                        }
                    ]
                },
            }
        ],
    )
    call = expand_multi_tool_use(bundled).tool_calls[0]
    runtime = AgentToolRuntime(
        state={"mode": "plan"},
        tool_call_id=call["id"],
        config={},
        context=None,
        store=None,
        stream_writer=None,
        agent=SimpleNamespace(),
    )

    blocked = await node._arun_one(call, "tool_calls", runtime)

    assert blocked.status == "error"
    assert blocked.additional_kwargs["error_code"] == BLOCKED_ERROR_CODE
    assert calls == []


@pytest.mark.anyio
async def test_direct_frontend_mcp_call_respects_annotations() -> None:
    state = {
        "mode": "plan",
        "mcp_tools": [
            {
                "name": "remote_write",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                },
            }
        ],
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "mcp-1",
                        "name": "remote_write",
                        "args": {"value": 1},
                    }
                ],
            )
        ],
    }

    update = await ToolResultMiddleware().after_model(state, None, {})

    assert update["messages"][0].status == "error"
    assert update["messages"][0].additional_kwargs["error_code"] == BLOCKED_ERROR_CODE


def test_all_production_tool_declarations_have_policy() -> None:
    package_root = Path(__file__).parents[2] / "giga_agent"
    declarations: list[tuple[Path, int]] = []
    missing: list[tuple[Path, int]] = []

    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        policy_constants = {
            target.id
            for assignment in ast.walk(tree)
            if isinstance(assignment, (ast.Assign, ast.AnnAssign))
            for target in (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            if isinstance(target, ast.Name)
            and isinstance(assignment.value, ast.AST)
            and any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "tool_extras"
                for child in ast.walk(assignment.value)
            )
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call is not None else decorator
                name = target.id if isinstance(target, ast.Name) else None
                if name not in {"tool", "make_tool"}:
                    continue
                declarations.append((path, node.lineno))
                extras = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "extras"
                    ),
                    None,
                )
                has_policy = (
                    isinstance(extras, ast.Call)
                    and isinstance(extras.func, ast.Name)
                    and extras.func.id == "tool_extras"
                ) or (isinstance(extras, ast.Name) and extras.id in policy_constants)
                if not has_policy:
                    missing.append((path, node.lineno))

    assert len(declarations) == 79
    assert missing == []
