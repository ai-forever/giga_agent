import re
import uuid
from typing import Any, Mapping

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph_sdk import get_client

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository


_TITLE_MAX_LEN = 80
_MESSAGE_MAX_LEN = 1200
_JSON_PARSER = JsonOutputParser()


def _resolve_thread_id(config: RunnableConfig | dict[str, Any]) -> str | None:
    if not isinstance(config, dict):
        return None

    metadata = config.get("metadata", {}) or {}
    thread_id = metadata.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    configurable = config.get("configurable", {}) or {}
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    return None


def _resolve_owner_id(config: RunnableConfig | dict[str, Any]) -> uuid.UUID | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable", {}) or {}
    user = configurable.get("langgraph_auth_user", {}) or {}
    identity = user.get("identity")
    if identity is None:
        return None
    if isinstance(identity, uuid.UUID):
        return identity
    if isinstance(identity, str):
        try:
            return uuid.UUID(identity)
        except ValueError:
            return None
    return None


def _extract_metadata(config: Any) -> dict[str, Any]:
    if isinstance(config, dict):
        meta = config.get("metadata")
        return dict(meta) if isinstance(meta, Mapping) else {}
    meta = getattr(config, "metadata", None)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _pick_first_user_message(state: AgentState) -> str | None:
    for msg in state.get("messages", []):
        if getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
            if content is not None:
                as_str = str(content).strip()
                if as_str:
                    return as_str
    return None


def _sanitize_title(raw: str) -> str:
    title = raw.strip()
    title = title.strip('"').strip("'").strip()
    title = re.sub(r"\s+", " ", title)
    title = title.replace("\n", " ").strip()
    if len(title) > _TITLE_MAX_LEN:
        title = title[:_TITLE_MAX_LEN].rstrip()
    return title or "Новый чат"


def _fallback_title_from_message(message: str) -> str:
    words = [w for w in re.split(r"\s+", message.strip()) if w]
    return _sanitize_title(" ".join(words[:3])) if words else "Новый чат"


def _extract_thread_title_from_json(raw: str) -> str | None:
    try:
        payload = _JSON_PARSER.parse(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("thread_title")
    if isinstance(value, str) and value.strip():
        return _sanitize_title(value)
    return None


async def _generate_title(llm: Any, first_message: str) -> str:
    prompt = (
        "Сгенерируй короткое название чата по первому сообщению пользователя.\n"
        "Верни ответ в формате JSON.\n"
        f'{{"thread_title": "<название>"}} \n'
        "Требования к thread_title:\n"
        "- 3–8 слов\n"
        "- без кавычек, без точки в конце, без эмодзи\n"
        "- одна строка\n"
    )
    excerpt = first_message.strip()
    if len(excerpt) > _MESSAGE_MAX_LEN:
        excerpt = excerpt[:_MESSAGE_MAX_LEN].rstrip()

    try:
        resp = await llm.with_config(tags=["nostream"]).ainvoke(
            [SystemMessage(content=prompt), HumanMessage(content=excerpt)]
        )
        content = (
            str(resp.content)
            if isinstance(resp, AIMessage)
            else str(getattr(resp, "content", resp))
        )
        extracted = _extract_thread_title_from_json(content)
        if extracted is not None:
            return extracted
        return _fallback_title_from_message(excerpt)
    except Exception as e:
        return _fallback_title_from_message(excerpt)


class ThreadTitleMiddleware(AgentMiddleware):
    async def before_agent(
        self,
        state: AgentState,
        runtime: Runtime[Context],
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        _ = runtime
        thread_id = _resolve_thread_id(config)
        if not thread_id or thread_id.startswith("temporary/"):
            return None

        metadata = _extract_metadata(config)
        existing_title = metadata.get("thread_title")
        if isinstance(existing_title, str) and existing_title.strip():
            return None

        first_message = _pick_first_user_message(state)
        if not first_message:
            return None

        owner_id = _resolve_owner_id(config)
        if owner_id is None:
            return None

        factory = await get_session_factory()
        async with factory() as session:
            user = await UserRepository.get_cached_or_db(owner_id, session=session)
            if user is None:
                return None

            llm_id = user.fast_llm_id or user.llm_id
            if not llm_id:
                return None

            llm_runtime = await LLMManager.resolve_by_id(llm_id, session=session)
            llm = llm_runtime.llm

        title = await _generate_title(llm, first_message)
        metadata = {"thread_title": title}
        try:
            client = get_client()
            await client.threads.update(thread_id, metadata=metadata)
        except Exception:
            return None

        return None
