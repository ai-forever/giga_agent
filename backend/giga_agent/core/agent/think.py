"""Think-tool helpers: forced multi-hop reasoning, hop collapsing, fast-model delegation."""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from giga_agent.llm.manager import LLMManager

THINK_TOOL_NAME = "think"
MAX_FORCED_THINK_FOLLOWUPS = 2
THINK_VIA_FAST_MODEL = False
THINK_HOP_RESULT = (
    "Подумай еще глубже и подробнее. Проверь, что ты мог упустить, "
    "покритикуй свой текущий ход мысли, проверь слабые места плана. "
    "Пересмотри выводы, попробуй найти оставшиеся противоречия, неочевидные "
    "риски и альтернативные трактовки. Убедись, что твой следующий шаг "
    "действительно самый лучший."
)
FAST_MODEL_THINK_PROMPT = (
    "Расширь и углуби предыдущие рассуждения ассистента. "
    "Найди слабые места, оцени плюсы и минусы подхода, "
    "предложи альтернативы и укажи, что ещё стоит учесть. "
)


def _count_trailing_think_tool_pairs(messages: list[AnyMessage]) -> int:
    """Count trailing consecutive AI(think) -> ToolMessage pairs."""
    pairs = 0
    index = len(messages) - 1

    while index >= 1:
        tool_message = messages[index]
        ai_message = messages[index - 1]

        if not isinstance(tool_message, ToolMessage):
            break
        if not isinstance(ai_message, AIMessage):
            break
        if len(ai_message.tool_calls) != 1:
            break

        tool_call = ai_message.tool_calls[0]
        if tool_call.get("name") != THINK_TOOL_NAME:
            break
        if tool_call.get("id") != tool_message.tool_call_id:
            break

        pairs += 1
        index -= 2

    return pairs


def _is_think_pair(ai_msg: AnyMessage, tool_msg: AnyMessage) -> bool:
    """Check if an AI+ToolMessage pair is a single think tool call."""
    if not isinstance(ai_msg, AIMessage) or not isinstance(tool_msg, ToolMessage):
        return False
    if len(ai_msg.tool_calls) != 1:
        return False
    call = ai_msg.tool_calls[0]
    return (
        call.get("name") == THINK_TOOL_NAME
        and call.get("id") == tool_msg.tool_call_id
    )


def _extract_think_thoughts(ai_message: AIMessage) -> str:
    """Extract thoughts text from a single think tool_call."""
    args = ai_message.tool_calls[0].get("args", {})
    return args.get("thoughts") or args.get("thought") or ""


def _merge_think_group(
    pairs: list[tuple[AIMessage, ToolMessage]],
) -> list[AnyMessage]:
    """Collapse a group of consecutive think pairs into one AI+ToolMessage.

    Single pairs are returned as-is. For 2+ pairs the thoughts are joined
    and content on the merged AIMessage is cleared.
    """
    if len(pairs) == 1:
        return [pairs[0][0], pairs[0][1]]

    thoughts = [_extract_think_thoughts(ai) for ai, _ in pairs]
    merged_thoughts = "\n".join(t for t in thoughts if t)

    last_ai, last_tool = pairs[-1]

    merged_call = last_ai.tool_calls[0].copy()
    merged_args = dict(merged_call.get("args", {}))
    merged_args["thoughts"] = merged_thoughts
    merged_call["args"] = merged_args

    merged_ai = last_ai.model_copy(
        update={"tool_calls": [merged_call], "content": ""}
    )
    return [merged_ai, last_tool]


def collapse_think_hops(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Merge every run of consecutive AI(think)+ToolMessage pairs across
    the whole conversation into a single pair per run.
    """
    if len(messages) < 4:
        return messages

    from typing import cast

    result: list[AnyMessage] = []
    i = 0

    while i < len(messages) - 1:
        if _is_think_pair(messages[i], messages[i + 1]):
            group: list[tuple[AIMessage, ToolMessage]] = []
            while (
                i < len(messages) - 1
                and _is_think_pair(messages[i], messages[i + 1])
            ):
                group.append(
                    (cast("AIMessage", messages[i]),
                     cast("ToolMessage", messages[i + 1]))
                )
                i += 2
            result.extend(_merge_think_group(group))
        else:
            result.append(messages[i])
            i += 1

    if i < len(messages):
        result.append(messages[i])

    return result


def resolve_bound_tool_choice(messages: list[AnyMessage]) -> str:
    """Force repeated think calls for a limited trailing think/tool chain."""
    trailing = _count_trailing_think_tool_pairs(messages)
    if trailing < MAX_FORCED_THINK_FOLLOWUPS:
        return THINK_TOOL_NAME
    return "auto"


def is_single_think_call(ai_message: AIMessage) -> bool:
    """Check if AIMessage contains exactly one think tool_call and nothing else."""
    return (
        len(ai_message.tool_calls) == 1
        and ai_message.tool_calls[0].get("name") == THINK_TOOL_NAME
    )


async def process_think_via_fast_model(
    ai_message: AIMessage,
    *,
    user,
    session,
    messages_for_llm: list[AnyMessage],
    system_message: SystemMessage,
    tools: list[BaseTool],
) -> list[AnyMessage]:
    """Replace think tool_call with fast_model reasoning and return patched messages.

    Flow:
    1. Strip think tool_call from AIMessage, move thoughts into content
    2. Append HumanMessage asking fast_model to critique/analyze
    3. Call fast_model
    4. Wrap fast_model answer as ToolMessage for the original think call
    5. Return [original AIMessage with tool_call, ToolMessage with fast_model answer]
    """
    thoughts = _extract_think_thoughts(ai_message)
    think_call = ai_message.tool_calls[0]

    fast_llm_id = user.fast_llm_id or user.llm_id
    if fast_llm_id is None:
        return [ai_message]

    fast_llm_runtime = await LLMManager.resolve_by_id(fast_llm_id, session=session)
    fast_llm = await fast_llm_runtime.get_llm()
    fast_llm = fast_llm.with_config(tags=["nostream"])

    ai_as_content = ai_message.model_copy(
        update={"tool_calls": [], "content": f"{thoughts}", "additional_kwargs": {}}
    )
    critique_request = HumanMessage(content=FAST_MODEL_THINK_PROMPT)
    fast_messages = [system_message] + messages_for_llm[:-1] + [ai_as_content, critique_request]
    agent = fast_llm
    fast_response = await agent.ainvoke(fast_messages)
    fast_text = (
        fast_response.content
        if isinstance(fast_response.content, str)
        else str(fast_response.content)
    )
    think_call['args']['thoughts'] = thoughts + "\n" + fast_text

    return [ai_message.model_copy(update={"tool_calls": [think_call]})]
