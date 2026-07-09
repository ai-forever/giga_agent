import re

from langchain_core.messages import ToolMessage

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", flags=re.DOTALL)


def strip_thinking(text: str) -> str:
    """Удалить приватные ``<thinking>...</thinking>`` блоки из текста ответа."""
    if not text:
        return ""
    return _THINKING_RE.sub("", text).strip()


def filter_tool_messages(messages):
    filtered_messages = []
    for idx, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            if idx - 1 <= 0:
                continue
            ai_message_tool_called = (
                messages[idx - 1].additional_kwargs.get("function_call")
                or messages[idx - 1].tool_calls
            )
            if not ai_message_tool_called:
                continue
        filtered_messages.append(msg)
    return filtered_messages


def filter_tool_calls(message):
    last_mes = message.model_copy()
    if last_mes.tool_calls or "tool_calls" in last_mes.additional_kwargs:
        if not last_mes.content:
            last_mes.content = "."
        if "tool_calls" in last_mes.additional_kwargs:
            last_mes.additional_kwargs.pop("tool_calls")
        last_mes.tool_calls = []
    last_mes.additional_kwargs["function_call"] = None
    last_mes.additional_kwargs["functions_state_id"] = None
    return last_mes
