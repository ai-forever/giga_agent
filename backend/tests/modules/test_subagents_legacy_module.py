import sys
import types
import unittest
import uuid
from unittest.mock import patch

from langchain.tools import tool

from giga_agent.modules.subagents_legacy.module import SubAgentLegacyModule


@tool
def researcher_agent(question: str) -> str:
    """Test tool stub."""
    return question


@tool
def lean_canvas(theme: str) -> str:
    """Test tool stub."""
    return theme


@tool
def city_explore(city: str) -> str:
    """Test tool stub."""
    return city


@tool
def podcast_generate(url: str) -> str:
    """Test tool stub."""
    return url


@tool
def create_landing(task: str) -> str:
    """Test tool stub."""
    return task


@tool
def generate_presentation(task: str) -> str:
    """Test tool stub."""
    return task


@tool
def create_meme(task: str) -> str:
    """Test tool stub."""
    return task


class SubagentsLegacyModuleTests(unittest.IsolatedAsyncioTestCase):
    def _patch_modules(self):
        return patch.dict(
            sys.modules,
            {
                "giga_agent.modules.subagents_legacy.agents.researcher.graph": types.SimpleNamespace(
                    researcher_agent=researcher_agent
                ),
                "giga_agent.modules.subagents_legacy.agents.lean_canvas": types.SimpleNamespace(
                    lean_canvas=lean_canvas
                ),
                "giga_agent.modules.subagents_legacy.agents.gis_agent.graph": types.SimpleNamespace(
                    city_explore=city_explore
                ),
                "giga_agent.modules.subagents_legacy.agents.podcast.graph": types.SimpleNamespace(
                    podcast_generate=podcast_generate
                ),
                "giga_agent.modules.subagents_legacy.agents.landing_agent.graph": types.SimpleNamespace(
                    create_landing=create_landing
                ),
                "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph": types.SimpleNamespace(
                    generate_presentation=generate_presentation
                ),
                "giga_agent.modules.subagents_legacy.agents.meme_agent.graph": types.SimpleNamespace(
                    create_meme=create_meme
                ),
            },
        )

    async def test_module_hides_tools_when_prerequisites_missing(self):
        module = SubAgentLegacyModule()
        user = types.SimpleNamespace(
            llm_id=None,
            search_engine_id=None,
            image_generator_id=None,
            secrets={},
        )
        tools = await module.get_tools(user=user, agent=object())
        self.assertEqual(tools, [])

    async def test_module_enables_expected_tools(self):
        module = SubAgentLegacyModule()
        user = types.SimpleNamespace(
            llm_id=uuid.uuid4(),
            search_engine_id=uuid.uuid4(),
            image_generator_id=uuid.uuid4(),
            secrets={
                "TWOGIS_TOKEN": "x",
                "SALUTE_SPEECH": "y",
            },
        )
        with self._patch_modules():
            tools = await module.get_tools(user=user, agent=object())

        names = sorted(tool.name for tool in tools)
        self.assertEqual(
            names,
            sorted(
                [
                    "lean_canvas",
                    "city_explore",
                    "podcast_generate",
                    "create_landing",
                    "generate_presentation",
                    "create_meme",
                    "researcher_agent",
                ]
            ),
        )

    def test_get_subgraphs_returns_expected_legacy_entries(self):
        module = SubAgentLegacyModule()
        self.assertEqual(
            module.get_subgraphs(),
            {
                "landing": "giga_agent.modules.subagents_legacy.agents.landing_agent.graph:graph",
                "presentation": "giga_agent.modules.subagents_legacy.agents.presentation_agent.graph:graph",
                "meme": "giga_agent.modules.subagents_legacy.agents.meme_agent.graph:graph",
                "lean_canvas": "giga_agent.modules.subagents_legacy.agents.lean_canvas:app",
                "podcast": "giga_agent.modules.subagents_legacy.agents.podcast.graph:graph",
            },
        )
