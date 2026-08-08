from __future__ import annotations

import asyncio

from giga_agent.modules.clarify.module import ClarifyModule


def test_clarify_module_disables_tools_in_cli_prompt_mode() -> None:
    module = ClarifyModule()

    tools = asyncio.run(
        module._get_tools(
            None,
            object(),
            config={"metadata": {"cli_prompt_mode": True}},
        )
    )
    instructions = asyncio.run(
        module.get_instructions(
            None,
            object(),
            config={"metadata": {"cli_prompt_mode": True}},
        )
    )

    assert tools == []
    assert instructions is None


def test_clarify_module_keeps_tools_in_interactive_cli_mode() -> None:
    module = ClarifyModule()

    tools = asyncio.run(module._get_tools(None, object(), config={"metadata": {}}))

    assert [tool.name for tool in tools] == ["ask_questions"]
