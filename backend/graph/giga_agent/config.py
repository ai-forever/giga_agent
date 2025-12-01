import os
from operator import add
from typing import Annotated, List, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

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
from giga_agent.tools.repl import shell
from giga_agent.tools.scraper import get_urls
from giga_agent.tools.vk import vk_get_comments, vk_get_last_comments, vk_get_posts
from giga_agent.tools.weather import weather
from giga_agent.utils.llm import load_llm

BASEDIR = os.path.abspath(os.path.dirname(__file__))


class AgentState(TypedDict):  # noqa: D101
    messages: Annotated[list[AnyMessage], add_messages]
    file_ids: Annotated[List[str], add]
    kernel_id: str
    tool_call_index: int
    tools: list


llm = load_llm()

if settings.features.repl_from_message:
    from giga_agent.tools.repl.message_tool import python
else:
    from giga_agent.tools.repl.args_tool import python


MCP_CONFIG = {}


def has_required_envs(tool) -> bool:
    """Проверяет, что для `tool` установлены все обязательные переменные окружения."""
    if tool.name == gen_image.name:
        return bool(settings.image_gen.image_gen_name)
    if tool.name in [get_urls.name, search.name, researcher_agent.name]:
        return bool(settings.external.tavily_api_key)
    if tool.name == generate_presentation.name:
        return bool(settings.image_gen.image_gen_name)
    if tool.name == create_landing.name:
        return bool(settings.image_gen.image_gen_name)
    if tool.name == podcast_generate.name:
        return bool(settings.external.salute_speech)
    if tool.name == create_meme.name:
        return bool(settings.image_gen.image_gen_name)
    if tool.name == city_explore.name:
        return bool(settings.external.twogis_token)
    if tool.name in [
        vk_get_posts.name,
        vk_get_comments.name,
        vk_get_last_comments.name,
    ]:
        return bool(settings.external.vk_token)
    if tool.name in [
        get_workflow_runs.name,
        list_pull_requests.name,
        get_pull_request.name,
    ]:
        return bool(settings.external.github_personal_access_token)

    return True


def filter_tools_by_env(tools: list) -> list:
    """Возвращает список тулов, прошедших проверку обязательных env переменных."""
    return [tool for tool in tools if has_required_envs(tool)]


SERVICE_TOOLS = [
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

AGENTS = [
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
    researcher_agent,
]

TOOLS = filter_tools_by_env(
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
