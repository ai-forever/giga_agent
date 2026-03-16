from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime

from giga_agent.core.db import get_session_factory
from giga_agent.llm.manager import LLMManager
from giga_agent.models.users import UserRepository


def _validate_texts(texts: list[str]) -> None:
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise ValueError("All texts must be strings.")


async def _resolve_user_llm(tool_runtime: ToolRuntime):
    user_id = tool_runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
        if user is None:
            raise ValueError(f"Пользователь {owner_id} не найден")

        llm_id = user.fast_llm_id or user.llm_id
        if llm_id is None:
            raise ValueError(
                "У пользователя не настроен LLM для summarize. "
                "Укажите fast_llm_id или llm_id."
            )

        llm_runtime = await LLMManager.resolve_by_id(llm_id, session=session)
        return await llm_runtime.get_llm()


async def summarize(
    texts: list[str],
    addition: str = "",
    tool_runtime: ToolRuntime | None = None,
) -> str:
    """Суммаризирует список текстов

    Args:
        texts: Список текстов на суммаризацию
        addition: На что во время суммаризации стоит обратить внимание
        tool_runtime: Runtime текущего вызова инструмента

    """
    _validate_texts(texts)
    if tool_runtime is None:
        raise ValueError("tool_runtime is required for summarize.")

    llm = await _resolve_user_llm(tool_runtime)
    extra = f"\nОбрати особое внимание на {addition}\n" if addition else ""
    texts_blob = "\n----\n".join(texts)
    response = await llm.ainvoke(
        [("system", f"Суммаризируй текста ниже{extra}\n{texts_blob}")],
    )
    return str(response.content)
