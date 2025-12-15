import asyncio
import json
import os
from typing import TypedDict, Annotated, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.agents.browser_use import browser_task
from giga_agent.agents.gis_agent.graph import city_explore
from giga_agent.agents.landing_agent.graph import create_landing
from giga_agent.agents.lean_canvas import lean_canvas
from giga_agent.agents.meme_agent.graph import create_meme
from giga_agent.agents.podcast.graph import podcast_generate
from giga_agent.agents.presentation_agent.graph import generate_presentation
from giga_agent.agents.researcher.graph import researcher_agent
from giga_agent.repl_tools.llm import summarize
from giga_agent.repl_tools.sentiment import get_embeddings, predict_sentiments
from giga_agent.settings import settings
from giga_agent.tools.another import ask_about_image, gen_image, search
from giga_agent.tools.github import (
    get_pull_request,
    get_workflow_runs,
    list_pull_requests,
)
from giga_agent.tools.rag import get_documents, has_collections
from giga_agent.tools.repl import shell
from giga_agent.tools.scraper import get_urls
from giga_agent.tools.vk import vk_get_comments, vk_get_last_comments, vk_get_posts
from giga_agent.tools.weather import weather
from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import Collection
from giga_agent.utils.llm import load_embeddings

BASEDIR = os.path.abspath(os.path.dirname(__file__))


class Secret(TypedDict):
    name: str
    value: str
    description: Optional[str]


class AgentState(TypedDict):  # noqa: D101
    messages: Annotated[list[AnyMessage], add_messages]
    kernel_id: str
    tool_call_index: int
    tools: list
    collections: list[Collection]
    mcp_tools: list[dict[str, dict]]
    instructions: str
    secrets: list[Secret]


llm = load_llm()
emb = load_embeddings()
if settings.features.repl_from_message:
    from giga_agent.tools.repl.message_tool import python
else:
    from giga_agent.tools.repl.args_tool import python


MCP_CONFIG = json.loads(os.getenv("GIGA_AGENT_MCP_CONFIG", "{}").strip())

TOOLS_REQUIRED_ENVS = {
    gen_image.name: [settings.image_gen.image_gen_name],
    get_urls.name: [settings.external.tavily_api_key],
    search.name: [settings.external.tavily_api_key],
    lean_canvas.name: [],
    generate_presentation.name: [settings.image_gen.image_gen_name],
    create_landing.name: [settings.image_gen.image_gen_name],
    podcast_generate.name: [settings.external.salute_speech],
    create_meme.name: [settings.image_gen.image_gen_name],
    city_explore.name: [settings.external.twogis_token],
    vk_get_posts.name: [settings.external.vk_token],
    vk_get_comments.name: [settings.external.vk_token],
    vk_get_last_comments.name: [settings.external.vk_token],
    get_workflow_runs.name: [settings.external.github_personal_access_token],
    list_pull_requests.name: [settings.external.github_personal_access_token],
    get_pull_request.name: [settings.external.github_personal_access_token],
    researcher_agent.name: [settings.external.tavily_api_key],
    browser_task.name: ["DONT_NEED_RIGHT_NOW"],
    get_documents.name: [
        "LANGCONNECT_API_URL",
        "LANGCONNECT_API_SECRET_TOKEN",
    ],
}

TOOLS_AGENT_CHECKS = {get_documents.name: [has_collections]}


async def run_checks(tool_name: str, state: AgentState):
    for check in TOOLS_AGENT_CHECKS[tool_name]:
        if callable(check) and not check(state):
            return False
        if asyncio.iscoroutinefunction(check) and not await check(state):
            return False
    return True


def has_required_envs(tool) -> bool:
    """Проверяет, что для `tool` установлены все обязательные переменные окружения.

    Если тул не указан в `TOOLS_REQUIRED_ENVS`, считаем, что у него нет обязательных
    переменных окружения и включаем его.
    """
    required_env_names = TOOLS_REQUIRED_ENVS.get(tool.name)
    if required_env_names is None:
        return True
    for env_name in required_env_names:
        if isinstance(env_name, str):
            if not os.getenv(env_name):
                return False
        elif callable(env_name):
            if not env_name():
                return False
    return True


def filter_tools_by_env(tools: list) -> list:
    """Возвращает список тулов, прошедших проверку обязательных env переменных."""
    return [tool for tool in tools if has_required_envs(tool)]


SERVICE_TOOLS = filter_tools_by_env(
    [
        get_documents,
        weather,
        # VK TOOLS
        vk_get_posts,
        vk_get_comments,
        vk_get_last_comments,
        # GITHUB TOOLS
        get_workflow_runs,
        list_pull_requests,
        get_pull_request,
    ]
)

AGENTS = filter_tools_by_env(
    [
        ask_about_image,
        gen_image,
        get_urls,
        search,
        lean_canvas,
        generate_presentation,
        create_landing,
        podcast_generate,
        create_meme,
        city_explore,
        browser_task,
        researcher_agent,
    ]
)

TOOLS = (
    [
        # REPL
        python,
        shell,
    ]
    + AGENTS
    + SERVICE_TOOLS
)


REPL_TOOLS = [predict_sentiments, summarize, get_embeddings]

AGENT_MAP = {agent.name: agent for agent in AGENTS}
