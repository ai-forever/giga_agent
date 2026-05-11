from __future__ import annotations

from langchain.tools import ToolRuntime

from giga_agent.core.agent.runtime_resolver import RuntimeResolver


def _validate_texts(texts: list[str]) -> None:
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise ValueError("All texts must be strings.")


async def _resolve_user_llm(tool_runtime: ToolRuntime):
    resolver = RuntimeResolver.from_config(tool_runtime.config)
    fast_llm_runtime = await resolver.get_fast_llm_runtime()
    return await fast_llm_runtime.get_llm()


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
