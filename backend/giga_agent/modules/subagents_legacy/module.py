"""Legacy subagents module with conditional tool registration."""

from __future__ import annotations

import importlib
from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.conf import get_settings
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort


def _import_attr(module_path: str, attr_name: str):
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


async def _get_legacy_capabilities(user: UserShort, *, config=None):
    from giga_agent.modules.subagents_legacy.runtime import get_legacy_capabilities

    return await get_legacy_capabilities(user, config=config)


def _legacy_tool(module_path: str, attr_name: str) -> BaseTool:
    return _import_attr(module_path, attr_name)


class SubAgentLegacyModule(BaseModule):
    id: str = "subagents_legacy"
    label: str = "Креатив-агенты"
    description: str = "Lean Canvas, генерация мемов, подкастов, исследование городов"
    icon: str = "Sparkles"

    def get_subgraphs(self, **kwargs: Any) -> dict[str, str]:
        _ = kwargs
        return {
            "landing": "giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph",
            "presentation": "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph",
            "meme": "giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph",
            "lean_canvas": "giga_agent.modules.subagents_legacy.agents.lean_canvas:app",
            "podcast": "giga_agent.modules.subagents_legacy.agents.podcast.graph:graph",
        }

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": "TWOGIS_TOKEN",
                "description": "Токен от 2гис (с доступом к поиску и отображению карт)",
                "type": "pass",
            },
            {
                "name": "SALUTE_SPEECH",
                "description": "Токен SaluteSpeech",
                "type": "pass",
            },
            {
                "name": "SALUTE_SCOPE",
                "description": "Scope токена SaluteSpeech",
                "type": "text",
            },
            {
                "name": "SUBAGENTS_LLM",
                "description": "LLM для работы внутри субагентов",
                "type": "llm_id",
            }
        ]

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent
        if user is None:
            return []

        caps = await _get_legacy_capabilities(user, config=config)
        tools: list[BaseTool] = []
        is_cli = get_settings().giga_agent_runtime == "cli"

        if caps.has_llm:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.lean_canvas",
                    "lean_canvas",
                )
            )

        if caps.has_twogis_token and not is_cli:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.gis_agent.graph",
                    "city_explore",
                )
            )

        if caps.has_llm and caps.has_salute_speech and not is_cli:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.podcast.graph",
                    "podcast_generate",
                )
            )

        if caps.has_llm and caps.has_image_generator:
            if is_cli:
                tools.append(
                    _legacy_tool(
                        "giga_agent.modules.subagents_legacy.agents.meme_agent.graph",
                        "create_meme",
                    )
                )
            else:
                tools.extend(
                    [
                        # _legacy_tool(
                        #     "giga_agent.modules.subagents_legacy.agents.landing_agent.graph",
                        #     "create_landing",
                        # ),
                        # _legacy_tool(
                        #     "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph",
                        #     "generate_presentation",
                        # ),
                        _legacy_tool(
                            "giga_agent.modules.subagents_legacy.agents.meme_agent.graph",
                            "create_meme",
                        ),
                    ]
                )

        return tools

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state: Optional["AgentState"] = None,
        config=None,
        **kwargs: Any,
    ) -> str | None:
        _ = agent, state, config, kwargs
        if user is None:
            return ""

        caps = await _get_legacy_capabilities(user, config=config)
        instructions: list[str] = []
        is_cli = get_settings().giga_agent_runtime == "cli"

        if caps.has_llm and (caps.has_search or is_cli):
            instructions.append(
                "- **lean_canvas** — Создает lean canvas. "
                "Полезен при проработке идей, стартапов."
            )

        if caps.has_llm and caps.has_salute_speech and not is_cli:
            instructions.append(
                "- **podcast_generate** — Генерирует подкаст. "
                "Используй это, если пользователь нужно сгенерировать подкаст."
            )

        if caps.has_llm and caps.has_image_generator:
            if is_cli:
                instructions.append(
                    "- **create_meme** — Создает мем исходя из запроса пользователя."
                )
            else:
                instructions.append(
                    # - **generate_presentation** — Создает презентацию. Всегда используй 'generate_presentation', если пользователь просить создать презентацию!
                    """
- **create_meme** — Создает мем исходя из запроса пользователя."""
                )
        if not instructions:
            return ""
        instructions_text = "\n".join(instructions)
        return f"""АГЕНТЫ
Ты можешь вызвать следующие инструменты:
{instructions_text}

Также в некоторых случаях тебе может возвращаться thread_id. Используй thread_id, если тебе нужно продолжить работу с результатом агента."""
