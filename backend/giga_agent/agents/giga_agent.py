from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.modules.analyze_images import AnalyzeImagesModule
from giga_agent.modules.auth import AuthModule
from giga_agent.modules.deep_research import DeepResearchModule
from giga_agent.modules.github import GitHubModule
# from giga_agent.modules.github import GitHubModule
from giga_agent.modules.image import ImageModule
from giga_agent.modules.io import IOModule
from giga_agent.modules.mem_zero_memory.module import MemZeroModule
from giga_agent.modules.rag import RagModule
from giga_agent.modules.repl import ReplModule
from giga_agent.modules.scraper import ScraperModule
from giga_agent.modules.search import SearchModule
from giga_agent.modules.skills.module import SkillsModule
# from giga_agent.modules.subagents_legacy.module import SubAgentLegacyModule
# from giga_agent.modules.vk import VKModule
# from giga_agent.modules.weather import WeatherModule


class GigaAgent(BaseAgent):
    def get_modules(self) -> list[BaseModule]:
        return [
            AuthModule(),
            ReplModule(),
            ImageModule(),
            AnalyzeImagesModule(),
            IOModule(),
            ScraperModule(),
            SearchModule(),
            RagModule(),
            MemZeroModule(),
            SkillsModule(),
            # GitHubModule(),
            # VKModule(),
            # WeatherModule(),
            DeepResearchModule(),
            SubAgentLegacyModule(),
        ]
