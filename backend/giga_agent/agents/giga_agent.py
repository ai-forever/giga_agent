from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule
from giga_agent.memory.module import MemoryModule
from giga_agent.modules.analyze_images import AnalyzeImagesModule
from giga_agent.modules.auth.module import AuthModule
from giga_agent.modules.clarify import ClarifyModule
from giga_agent.modules.deep_research import DeepResearchModule
from giga_agent.modules.image import ImageModule
from giga_agent.modules.integrations.vk import VKModule
from giga_agent.modules.integrations.yandex_calendar.module import YandexCalendarModule
from giga_agent.modules.integrations.yandex_disk import YandexDiskModule
from giga_agent.modules.integrations.yandex_mail import YandexMailModule
from giga_agent.modules.io import IOModule
from giga_agent.modules.mcp import McpModule
from giga_agent.modules.projects import ProjectsModule
from giga_agent.modules.rag import RagModule
from giga_agent.modules.repl import ReplModule
from giga_agent.modules.scheduler.module import SchedulerModule
from giga_agent.modules.scraper import ScraperModule
from giga_agent.modules.search import SearchModule
from giga_agent.modules.skills.module import SkillsModule
from giga_agent.modules.subagents_legacy.module import SubAgentLegacyModule
from giga_agent.modules.weather import WeatherModule


class GigaAgent(BaseAgent):
    def get_modules(self) -> list[BaseModule]:
        return [
            AuthModule(),
            ClarifyModule(),
            ReplModule(),
            ImageModule(),
            AnalyzeImagesModule(),
            IOModule(),
            ProjectsModule(),
            ScraperModule(),
            SearchModule(),
            RagModule(),
            MemoryModule(),
            SkillsModule(),
            McpModule(),
            VKModule(),
            YandexDiskModule(),
            YandexMailModule(),
            YandexCalendarModule(),
            WeatherModule(),
            DeepResearchModule(),
            SchedulerModule(),
            SubAgentLegacyModule(),
        ]
