"""Legacy subagents module with conditional tool registration."""

from __future__ import annotations

import importlib
from typing import Any, List, Optional

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.types import AgentState
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort


def _import_attr(module_path: str, attr_name: str):
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _get_legacy_capabilities(user: UserShort):
    get_legacy_capabilities = _import_attr(
        "giga_agent.modules.subagents_legacy.runtime",
        "get_legacy_capabilities",
    )
    return get_legacy_capabilities(user)


def _legacy_tool(module_path: str, attr_name: str) -> BaseTool:
    return _import_attr(module_path, attr_name)


class SubAgentLegacyModule(BaseModule):
    id: str = "subagents_legacy"

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
            },
            {
                "name": "RESEARCHER_LLM",
                "description": (
                    "LLM для researcher_agent. "
                    "Для корректной работы researcher_agent требуется модель "
                    "с поддержкой 7+ инструментов."
                ),
                "type": "llm_id",
            },
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = agent
        if user is None:
            return []

        caps = _get_legacy_capabilities(user)
        tools: list[BaseTool] = []

        if caps.has_llm:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.lean_canvas",
                    "lean_canvas",
                )
            )

        if caps.has_search:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.researcher.graph",
                    "researcher_agent",
                )
            )

        if caps.has_twogis_token:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.gis_agent.graph",
                    "city_explore",
                )
            )

        if caps.has_llm and caps.has_salute_speech:
            tools.append(
                _legacy_tool(
                    "giga_agent.modules.subagents_legacy.agents.podcast.graph",
                    "podcast_generate",
                )
            )

        if caps.has_llm and caps.has_image_generator:
            tools.extend(
                [
                    _legacy_tool(
                        "giga_agent.modules.subagents_legacy.agents.landing_agent.graph",
                        "create_landing",
                    ),
                    _legacy_tool(
                        "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph",
                        "generate_presentation",
                    ),
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

        caps = _get_legacy_capabilities(user)
        instructions: list[str] = []

        if caps.has_llm and caps.has_search:
            instructions.append(
                "- **lean_canvas** — Создает lean canvas. "
                "Полезен при проработке идей, стартапов."
            )

        if caps.has_search:
            instructions.append(
                """- **researcher_agent** — Агент для проведения исследования. Используй это, если пользователю нужно написать исследовательский отчет на какую-либо тему. Агент сам сделает поиск и исследует тему, тебе нужно лишь передать ему задачу.
Когда пользователь задает какой-то вопрос на поиск, уточни у него, хочет ли он проводить глубокое исследование или простой поиск.
В зависимости от ответа пользователя, выбирай инструмент:
- search - для простых поисковых запросов
- researcher_agent - если пользователь захотел глубокое исследование."""
            )

        if caps.has_llm and caps.has_salute_speech:
            instructions.append(
                "- **podcast_generate** — Генерирует подкаст. "
                "Используй это, если пользователь нужно сгенерировать подкаст."
            )

        if caps.has_llm and caps.has_image_generator:
            instructions.append(
                """- **generate_presentation** — Создает презентацию. Всегда используй 'generate_presentation', если пользователь просить создать презентацию!
- **podcast_generate** — Генерирует подкаст. Используй это, если пользователь нужно сгенерировать подкаст.
- **create_meme** — Создает мем исходя из запроса пользователя."""
            )
        if not instructions:
            return ""
        instructions_text = '\n'.join(instructions)
        return f"""АГЕНТЫ
Ты можешь вызвать следующие инструменты:
{instructions_text}

Также в некоторых случаях тебе может возвращаться thread_id. Используй thread_id, если тебе нужно продолжить работу с результатом агента."""
