"""
Тест форков / редактирования сообщений в LangGraph при хранении `messages`
в DeltaChannel (см. https://www.langchain.com/blog/delta-channels-evolving-agent-runtime).

DeltaChannel хранит в чекпоинте только дельту каждого шага и периодически делает
полный снапшот, реконструируя state проигрыванием ancestor-writes через reducer.
В отличие от обычного reducer (`add_messages(left, right)`), DeltaChannel требует
batched-reducer вида `reducer(state, [w1, w2, ...]) -> new_state`, который обязан
быть batching-invariant:

    reducer(reducer(state, xs), ys) == reducer(state, xs + ys)

Граф максимально простой: только `messages` и один node-эхо.

Запуск:  python scripts/test_delta_forks.py
"""

from typing import Annotated, Any, Sequence

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
)
from langgraph.channels.delta import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from typing_extensions import TypedDict


# --------------------------------------------------------------------------- #
# Batched reducer для DeltaChannel поверх стандартного add_messages.
# add_messages(left, right) — чистый left-fold, поэтому свёртка батча writes
# слева направо даёт тот же результат, что и конкатенация батчей → batching-invariant.
# add_messages умеет: дедуп по id (замена сообщения с тем же id) и RemoveMessage.
# --------------------------------------------------------------------------- #
def add_messages_delta(
    state: Sequence[AnyMessage], writes: Sequence[Any]
) -> list[AnyMessage]:
    result: Any = list(state)
    for w in writes:
        result = add_messages(result, w)
    return result


class State(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(reducer=add_messages_delta, snapshot_frequency=3),
    ]


def echo(state: State) -> dict:
    """Эхо-node: отвечает на последнее человеческое сообщение."""
    last = state["messages"][-1]
    text = getattr(last, "content", "")
    return {"messages": [AIMessage(content=f"echo: {text}")]}


def build_graph():
    g = StateGraph(State)
    g.add_node("echo", echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile(checkpointer=InMemorySaver())


def dump(graph, config, title: str) -> None:
    msgs = graph.get_state(config).values["messages"]
    print(f"\n=== {title} ===")
    for m in msgs:
        print(f"  [{m.type:6}] id={m.id[-8:] if m.id else '????????'}  {m.content!r}")


# --------------------------------------------------------------------------- #
# Сценарий 1: обычный диалог в несколько ходов (проверяем накопление + снапшоты)
# --------------------------------------------------------------------------- #
def test_basic_conversation(graph):
    print("\n##################  СЦЕНАРИЙ 1: обычный диалог  ##################")
    config = {"configurable": {"thread_id": "conv"}}
    for turn in ("привет", "как дела", "пока"):
        graph.invoke({"messages": [HumanMessage(content=turn)]}, config)
    dump(graph, config, "после 3 ходов (snapshot_frequency=3)")
    # Проверим, что в истории есть несколько чекпоинтов
    history = list(graph.get_state_history(config))
    print(f"  чекпоинтов в истории: {len(history)}")
    assert len(graph.get_state(config).values["messages"]) == 6  # 3 human + 3 ai


# --------------------------------------------------------------------------- #
# Сценарий 2: ФОРК — перезапуск с прошлого чекпоинта с другим вводом.
# Берём checkpoint ДО второго хода и форкаем туда новый человеческий вопрос.
# Это создаёт новую ветку, оставляя исходную нетронутой.
# --------------------------------------------------------------------------- #
def test_fork_from_past(graph):
    print("\n##################  СЦЕНАРИЙ 2: форк из прошлого  ##################")
    config = {"configurable": {"thread_id": "fork"}}
    graph.invoke({"messages": [HumanMessage(content="ход 1")]}, config)
    graph.invoke({"messages": [HumanMessage(content="ход 2")]}, config)
    dump(graph, config, "исходная ветка (2 хода)")
    # Запоминаем head исходной ветки (по checkpoint_id) — форк не должен его задеть.
    original_head_cfg = graph.get_state(config).config

    # Находим чекпоинт после первого хода (4 чекпоинта на ход -> ищем по len messages == 2)
    history = list(graph.get_state_history(config))
    fork_point = next(s for s in history if len(s.values.get("messages", [])) == 2)
    fork_cfg = fork_point.config
    print(
        f"\n  форкаемся от checkpoint_id={fork_cfg['configurable']['checkpoint_id'][-12:]}"
        f" (messages={len(fork_point.values['messages'])})"
    )

    # Запускаем граф с этого чекпоинта с НОВЫМ вводом -> новая ветка
    new_branch = graph.invoke(
        {"messages": [HumanMessage(content="ход 2-ФОРК")]}, fork_cfg
    )
    print("\n  новая (форкнутая) ветка:")
    for m in new_branch["messages"]:
        print(f"    [{m.type:6}] {m.content!r}")

    # HEAD треда (доступ по одному thread_id) теперь указывает на форк — это ожидаемо.
    dump(graph, config, "HEAD треда ПОСЛЕ форка (переехал на форкнутую ветку)")
    # Но исходная ветка осталась нетронутой и доступна по своему checkpoint_id.
    original = graph.get_state(original_head_cfg).values["messages"]
    print("\n  исходная ветка по сохранённому checkpoint_id (не изменилась):")
    for m in original:
        print(f"    [{m.type:6}] {m.content!r}")

    assert any("ФОРК" in m.content for m in new_branch["messages"])
    assert not any("ФОРК" in m.content for m in original), (
        "исходная ветка не должна содержать форк"
    )


# --------------------------------------------------------------------------- #
# Сценарий 3: РЕДАКТИРОВАНИЕ человеческого сообщения + регенерация — канонический
# flow чат-UI ("изменить сообщение и перегенерировать ответ").
# Одним update_state: (1) удаляем устаревший AI-ответ через RemoveMessage,
# (2) подменяем человеческое сообщение, отправив новое с тем же id (add_messages
# дедуплицирует по id). Затем перезапускаем echo — последним снова человеческое
# сообщение, и эхо отвечает уже на отредактированный текст.
# --------------------------------------------------------------------------- #
def test_edit_message(graph):
    print(
        "\n##################  СЦЕНАРИЙ 3: правка сообщения + регенерация  ##################"
    )
    config = {"configurable": {"thread_id": "edit"}}
    first = graph.invoke(
        {"messages": [HumanMessage(content="оригинальный вопрос", id="h1")]}, config
    )
    dump(graph, config, "до редактирования")
    old_ai_id = next(m.id for m in first["messages"] if m.type == "ai")

    # Правка + срезание устаревшего ответа одним апдейтом.
    graph.update_state(
        config,
        {
            "messages": [
                RemoveMessage(id=old_ai_id),
                HumanMessage(content="ОТРЕДАКТИРОВАННЫЙ вопрос", id="h1"),
            ]
        },
    )
    dump(graph, config, "после правки (replace by id + RemoveMessage старого ответа)")
    edited = graph.get_state(config).values["messages"]
    assert next(m for m in edited if m.id == "h1").content == "ОТРЕДАКТИРОВАННЫЙ вопрос"
    assert all(m.id != old_ai_id for m in edited), "старый AI-ответ должен быть удалён"

    # Регенерация: invoke(None) был бы no-op (граф уже на END), поэтому заходим
    # заново через START пустым вводом — echo видит отредактированное сообщение.
    result = graph.invoke({"messages": []}, config)
    print("\n  ответ echo на отредактированное сообщение:")
    print(f"    {result['messages'][-1].content!r}")
    assert result["messages"][-1].content == "echo: ОТРЕДАКТИРОВАННЫЙ вопрос"

    # Полный сброс канала через RemoveMessage(REMOVE_ALL_MESSAGES).
    graph.update_state(config, {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)]})
    dump(graph, config, "после RemoveMessage(REMOVE_ALL_MESSAGES)")
    assert graph.get_state(config).values["messages"] == []


if __name__ == "__main__":
    graph = build_graph()
    test_basic_conversation(graph)
    test_fork_from_past(graph)
    test_edit_message(graph)
    print("\n\n✅ Все сценарии прошли: DeltaChannel + форки + редактирование работают.")
