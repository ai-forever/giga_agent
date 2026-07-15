"""Repair of dangling tool_calls left in history after a stopped run.

When a user stops a run (frontend Stop button, Telegram reset, a crash), the
checkpoint may keep an AIMessage whose tool_calls never received their
ToolMessages. GigaChat rejects such history with 422 ("every function result
must have an assistant function call in history" — see the note in
graph_factory.amodel_node), so before a new run starts we persist stub
ToolMessages right after the dangling AIMessage and drop orphan ToolMessages
(a function result without a matching assistant call).
"""

import uuid
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    RemoveMessage,
    ToolMessage,
)

STOPPED_BY_USER_CONTENT = "Выполнение задачи было остановлено пользователем"


def _stub_tool_message(call: dict[str, Any]) -> ToolMessage:
    return ToolMessage(
        id=str(uuid.uuid4()),
        tool_call_id=call["id"],
        content=STOPPED_BY_USER_CONTENT,
        additional_kwargs={"stopped_by_user": True, "tool_name": call.get("name")},
    )


def repair_dangling_tool_calls(
    messages: list[AnyMessage],
) -> list[BaseMessage] | None:
    """Build a messages delta that fixes dangling tool_calls, or None if clean.

    Only runs when the history ends with a HumanMessage — i.e. at the start of
    a fresh run. Resumes from an interrupt end with an AIMessage whose
    tool_calls are still being processed, and stubbing those would break the
    resume.

    The returned delta is meant for the `add_messages` reducer. Orphans are
    dropped with plain RemoveMessages (relative order survives a deletion).
    For stub insertion the tail after the first stub position is removed and
    re-appended with FRESH ids: `add_messages` treats a re-added existing id
    as an in-place replacement at the old position, so moving a message is
    only possible as remove-old-id + append-new-id.
    """
    if not messages or messages[-1].type != "human":
        return None

    desired: list[AnyMessage] = []
    dropped: list[AnyMessage] = []
    stub_ids: set[str] = set()
    # Unanswered tool_calls of the most recent AIMessage block. Any non-tool
    # message closes the block: leftover calls get stubs before it.
    pending: dict[str, dict[str, Any]] = {}

    def close_block() -> None:
        for call in pending.values():
            stub = _stub_tool_message(call)
            stub_ids.add(stub.id)
            desired.append(stub)
        pending.clear()

    for message in messages:
        if isinstance(message, ToolMessage):
            if message.tool_call_id in pending:
                pending.pop(message.tool_call_id)
                desired.append(message)
            else:
                # Orphan or duplicate result — drop it, GigaChat rejects
                # results without a matching open assistant call.
                dropped.append(message)
            continue
        close_block()
        desired.append(message)
        if isinstance(message, AIMessage) and message.tool_calls:
            pending = {
                call["id"]: call for call in message.tool_calls if call.get("id")
            }

    # The trailing HumanMessage already closed the last block above.
    delta: list[BaseMessage] = [RemoveMessage(id=m.id) for m in dropped if m.id]

    first_stub = next((i for i, m in enumerate(desired) if m.id in stub_ids), None)
    if first_stub is None:
        return delta or None

    # Everything from the first stub on is re-appended; the original
    # messages in that tail get fresh ids so add_messages actually moves
    # them instead of replacing them in place.
    for message in desired[first_stub:]:
        if message.id in stub_ids:
            delta.append(message)
        else:
            if message.id:
                delta.append(RemoveMessage(id=message.id))
            delta.append(message.model_copy(update={"id": str(uuid.uuid4())}))
    return delta
