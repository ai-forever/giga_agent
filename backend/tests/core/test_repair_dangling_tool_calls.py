import operator
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages

from giga_agent.core.agent.repair import (
    STOPPED_BY_USER_CONTENT,
    repair_dangling_tool_calls,
)
from giga_agent.core.agent.utils import reduce_updates


def apply(messages, delta):
    """Run the delta through the real channel reducer."""
    return add_messages(messages, delta)


def tool_call(cid, name="search"):
    return {"id": cid, "name": name, "args": {}}


def test_dangling_block_gets_stubs_before_human():
    messages = [
        HumanMessage("задача", id="h1"),
        AIMessage("", id="a1", tool_calls=[tool_call("c1"), tool_call("c2")]),
        HumanMessage("новый вопрос", id="h2"),
    ]
    delta = repair_dangling_tool_calls(messages)
    assert delta is not None

    result = apply(messages, delta)
    types = [m.type for m in result]
    assert types == ["human", "ai", "tool", "tool", "human"]
    # Перенесённый human пере-добавлен с новым id (иначе add_messages
    # заменил бы его на старой позиции), контент сохранён.
    assert result[-1].content == "новый вопрос"
    assert result[-1].id != "h2"
    stubs = result[2:4]
    assert {s.tool_call_id for s in stubs} == {"c1", "c2"}
    for stub in stubs:
        assert stub.content == STOPPED_BY_USER_CONTENT
        assert stub.additional_kwargs["stopped_by_user"] is True
        assert stub.additional_kwargs["tool_name"] == "search"


def test_partial_tool_results_only_missing_stubbed():
    messages = [
        AIMessage("", id="a1", tool_calls=[tool_call("c1"), tool_call("c2")]),
        ToolMessage("done", id="t1", tool_call_id="c1"),
        HumanMessage("дальше", id="h1"),
    ]
    result = apply(messages, repair_dangling_tool_calls(messages))
    assert [m.type for m in result] == ["ai", "tool", "tool", "human"]
    assert result[1].id == "t1"
    assert result[2].tool_call_id == "c2"
    assert result[2].additional_kwargs["stopped_by_user"] is True


def test_clean_history_is_noop():
    messages = [
        HumanMessage("задача", id="h1"),
        AIMessage("", id="a1", tool_calls=[tool_call("c1")]),
        ToolMessage("done", id="t1", tool_call_id="c1"),
        AIMessage("готово", id="a2"),
        HumanMessage("ещё", id="h2"),
    ]
    assert repair_dangling_tool_calls(messages) is None


def test_guard_last_message_not_human():
    messages = [
        HumanMessage("задача", id="h1"),
        AIMessage("", id="a1", tool_calls=[tool_call("c1")]),
    ]
    assert repair_dangling_tool_calls(messages) is None
    assert repair_dangling_tool_calls([]) is None


def test_orphan_tool_message_dropped():
    messages = [
        HumanMessage("задача", id="h1"),
        ToolMessage("orphan", id="t0", tool_call_id="ghost"),
        AIMessage("ответ", id="a1"),
        HumanMessage("ещё", id="h2"),
    ]
    result = apply(messages, repair_dangling_tool_calls(messages))
    assert [m.id for m in result] == ["h1", "a1", "h2"]


def test_multiple_dangling_blocks():
    messages = [
        AIMessage("", id="a1", tool_calls=[tool_call("c1")]),
        AIMessage("", id="a2", tool_calls=[tool_call("c2")]),
        HumanMessage("дальше", id="h1"),
    ]
    result = apply(messages, repair_dangling_tool_calls(messages))
    assert [m.type for m in result] == ["ai", "tool", "ai", "tool", "human"]
    assert result[1].tool_call_id == "c1"
    assert result[3].tool_call_id == "c2"


def test_tool_call_without_id_skipped():
    messages = [
        AIMessage("", id="a1", tool_calls=[{"id": None, "name": "x", "args": {}}]),
        HumanMessage("дальше", id="h1"),
    ]
    assert repair_dangling_tool_calls(messages) is None


def test_duplicate_tool_result_dropped():
    messages = [
        AIMessage("", id="a1", tool_calls=[tool_call("c1")]),
        ToolMessage("done", id="t1", tool_call_id="c1"),
        ToolMessage("done again", id="t2", tool_call_id="c1"),
        HumanMessage("дальше", id="h1"),
    ]
    result = apply(messages, repair_dangling_tool_calls(messages))
    assert [m.id for m in result] == ["a1", "t1", "h1"]


class _State(TypedDict):
    messages: Annotated[list, add_messages]
    counter: Annotated[int, operator.add]
    plain: str


def test_reduce_updates_concatenates_messages_keeping_remove():
    remove = RemoveMessage(id="h1")
    human = HumanMessage("привет", id="h1")
    stub = ToolMessage("stop", id="t1", tool_call_id="c1")
    reduced = reduce_updates(
        [{"messages": [remove, stub]}, {"messages": [human]}], _State
    )
    assert reduced["messages"] == [remove, stub, human]


def test_reduce_updates_reducer_and_last_wins():
    reduced = reduce_updates(
        [{"counter": 1, "plain": "a"}, {"counter": 2, "plain": "b"}], _State
    )
    assert reduced["counter"] == 3
    assert reduced["plain"] == "b"
    assert reduce_updates([], _State) == {}
