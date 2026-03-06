"""Legacy subagents module with conditional tool registration."""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.subagents_legacy.runtime import get_legacy_capabilities
from giga_agent.modules.subagents_legacy.agents.lean_canvas import (
    lean_canvas,
)
from giga_agent.modules.subagents_legacy.agents.podcast.graph import (
    podcast_generate,
)
from giga_agent.modules.subagents_legacy.agents.landing_agent.graph import (
    create_landing,
)
from giga_agent.modules.subagents_legacy.agents.presentation_agent.graph import (
    generate_presentation,
)
from giga_agent.modules.subagents_legacy.agents.meme_agent.graph import (
    create_meme,
)
from giga_agent.modules.subagents_legacy.agents.gis_agent.graph import (
    city_explore,
)
from giga_agent.modules.subagents_legacy.agents.researcher.graph import (
    researcher_agent,
)


class SubAgentLegacyModule(BaseModule):
    id: str = "subagents_legacy"

    def get_subgraphs(self) -> dict[str, str]:
        return {
            "landing": "giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph",
            "presentation": "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph",
            "meme": "giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph",
            "lean_canvas": "giga_agent.modules.subagents_legacy.agents.lean_canvas:app",
            "podcast": "giga_agent.modules.subagents_legacy.agents.podcast.graph:graph",
        }

    def get_secrets(self) -> list[SecretMetadata]:
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
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = agent
        if user is None:
            return []

        caps = get_legacy_capabilities(user)
        tools: list[BaseTool] = []

        if caps.has_llm and caps.has_search:
            tools.extend([lean_canvas])

        if caps.has_search:
            tools.append(researcher_agent)

        if caps.has_twogis_token:
            tools.append(city_explore)

        if caps.has_llm and caps.has_salute_speech:
            tools.append(podcast_generate)

        if caps.has_llm and caps.has_image_generator:
            tools.extend([create_landing, generate_presentation, create_meme])

        return tools

    async def get_instructions(
        self, user: UserShort | None, agent: BaseAgent
    ) -> str | None:
        _ = agent
        if user is None:
            return []

        caps = get_legacy_capabilities(user)
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
