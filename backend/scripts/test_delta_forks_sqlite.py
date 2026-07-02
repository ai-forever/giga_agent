"""
Демонстрация, ПОЧЕМУ `messages` в types.py остаётся на add_messages, а НЕ на
DeltaChannel — против реального стека прод-сервера: AsyncSqliteSaver
(langgraph-checkpoint-sqlite).

Вывод (проверено эмпирически):
    При snapshot_frequency=50 (прод-значение, дающее реальную экономию) форк
    DeltaChannel-канала ломает реконструкцию get_state_history: write точки
    форка протекает в ОБЕ ветки (Stage2 в langgraph-checkpoint-sqlite тянет
    writes по checkpoint_id без различения веток). Склейка доходит до
    ЗАВЕРШЁННЫХ состояний (next == []) — то есть видна фронту: правка
    сообщений и регенерация дают ложные рёбра в дереве веток.
    На маленьком snapshot_frequency (напр. 2) склейка маскируется (завершённый
    head попадает на свежий снапшот, replay не нужен) — но это убивает смысл
    DeltaChannel. add_messages иммунен (хранит полный value в каждом чекпоинте).

Что делает скрипт:
    * берёт прод-snapshot_frequency=50 и AsyncSqliteSaver на реальном файле;
    * форкает/редактирует/регенерит и проверяет ЗАВЕРШЁННЫЕ состояния на склейку
      для DeltaChannel (ожидаемо ❌) и для add_messages (ожидаемо ✅);
    * exit!=0 только если add_messages (прод-канал) вдруг даёт склейку.

Локализация корня: backend/scripts/trace_delta_reducer.py
Запуск:  uv run python scripts/test_delta_forks_sqlite.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import (
    REMOVE_ALL_MESSAGES,
    _messages_delta_reducer,
    add_messages,
)
from typing_extensions import TypedDict

# Маленькая частота снапшотов: при многоходовом диалоге точно пересечём границу
# снапшота, и история будет реконструироваться через replay дельт — это и есть
# путь, который ломался при форках. В проде стоит 50 (см. types.py).
SNAPSHOT_FREQUENCY = 50


class DeltaState(TypedDict):
    # Точная копия канала из giga_agent/core/agent/types.py::AgentState.messages.
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(
            reducer=_messages_delta_reducer,
            snapshot_frequency=SNAPSHOT_FREQUENCY,
        ),
    ]


class PlainState(TypedDict):
    # Контроль: обычный add_messages-канал (то, что сейчас стоит в types.py
    # как обходной путь). Тот же сценарий не должен смешивать ветки.
    messages: Annotated[list[AnyMessage], add_messages]


def echo(state) -> dict:
    """Эхо-node: отвечает на последнее сообщение."""
    last = state["messages"][-1]
    return {"messages": [AIMessage(content=f"echo: {getattr(last, 'content', '')}")]}


def build_graph(checkpointer, state_type=DeltaState):
    g = StateGraph(state_type)
    g.add_node("echo", echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile(checkpointer=checkpointer)


def _short(cfg: dict) -> str:
    return (cfg.get("configurable", {}).get("checkpoint_id") or "????????")[-12:]


async def dump(graph, config, title: str) -> list[AnyMessage]:
    state = await graph.aget_state(config)
    msgs = state.values.get("messages", [])
    print(f"\n=== {title} ===  (checkpoint={_short(state.config)})")
    for m in msgs:
        mid = (m.id or "????????")[-8:]
        print(f"  [{m.type:6}] id={mid}  {m.content!r}")
    return msgs


def contents(msgs) -> list[str]:
    return [getattr(m, "content", "") for m in msgs]


# --------------------------------------------------------------------------- #
# Сценарий 1: обычный многоходовой диалог — проверяем накопление и что
# реконструкция из снапшота даёт согласованную линейную историю.
# --------------------------------------------------------------------------- #
async def test_basic_conversation(graph):
    print("\n##################  СЦЕНАРИЙ 1: обычный диалог (sqlite)  ##################")
    config = {"configurable": {"thread_id": "conv"}}
    for turn in ("привет", "как дела", "пока", "ещё"):
        await graph.ainvoke({"messages": [HumanMessage(content=turn)]}, config)
    msgs = await dump(graph, config, f"после 4 ходов (snapshot_frequency={SNAPSHOT_FREQUENCY})")
    assert len(msgs) == 8, f"ожидали 8 сообщений, получили {len(msgs)}"

    # Каждое историческое состояние — префикс финальной истории (линейность).
    history = [s async for s in graph.aget_state_history(config)]
    print(f"  чекпоинтов в истории: {len(history)}")
    final = contents(msgs)
    for st in history:
        h = contents(st.values.get("messages", []))
        assert h == final[: len(h)], (
            f"реконструкция из снапшота сломала префикс:\n  state={h}\n  final={final}"
        )
    print("  ✓ все исторические состояния — корректные префиксы финальной истории")


# --------------------------------------------------------------------------- #
# Сценарий 2: ФОРК из прошлого + проверка, что ветки НЕ смешиваются в истории.
# Это прямой тест бага из TODO: "сообщения из всех веток накапливаются".
# --------------------------------------------------------------------------- #
async def test_fork_no_branch_bleed(graph, label: str, thread_id: str) -> bool:
    """Возвращает True если ветки НЕ смешиваются (всё ок), False если баг есть."""
    print(f"\n##################  СЦЕНАРИЙ 2 [{label}]: форк из прошлого — ветки не смешиваются  ##################")
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke({"messages": [HumanMessage(content="ход 1")]}, config)
    await graph.ainvoke({"messages": [HumanMessage(content="ход 2-ОРИГИНАЛ")]}, config)
    orig_msgs = await dump(graph, config, "исходная ветка (2 хода)")
    original_head_cfg = (await graph.aget_state(config)).config

    # Чекпоинт после первого хода (messages == 2) → точка форка.
    history = [s async for s in graph.aget_state_history(config)]
    fork_point = next(s for s in history if len(s.values.get("messages", [])) == 2)
    fork_cfg = fork_point.config
    print(f"\n  форкаемся от checkpoint={_short(fork_cfg)} (messages={len(fork_point.values['messages'])})")

    # Новый ввод от точки форка → новая ветка.
    new_branch = await graph.ainvoke(
        {"messages": [HumanMessage(content="ход 2-ФОРК")]}, fork_cfg
    )
    print("\n  форкнутая ветка:")
    for m in new_branch["messages"]:
        print(f"    [{m.type:6}] {m.content!r}")

    # Исходная ветка по сохранённому checkpoint_id не должна быть задета.
    original = (await graph.aget_state(original_head_cfg)).values["messages"]
    assert "ход 2-ОРИГИНАЛ" in contents(original)
    assert "ход 2-ФОРК" not in contents(original), "БАГ: форк протёк в исходную ветку"
    assert "ход 2-ФОРК" in contents(new_branch["messages"])
    assert "ход 2-ОРИГИНАЛ" not in contents(new_branch["messages"]), "БАГ: исходная ветка протекла в форк"

    # ПРОД-ИНВАРИАНТ: склейка writes соседних веток при форке DeltaChannel —
    # известный апстрим-баг, но проявляется ТОЛЬКО на staging-чекпоинтах
    # (next != []). Фронт (buildMessageTree) строит дерево веток лишь из
    # ЗАВЕРШЁННЫХ состояний (next == []), поэтому критерий прохождения —
    # «среди завершённых состояний склейки нет». Склейку среди staging лишь
    # репортим (ожидаемо для DeltaChannel, фронту не видна).
    full_history = [s async for s in graph.aget_state_history(config)]

    def is_completed(st) -> bool:
        return len(getattr(st, "next", ()) or ()) == 0

    def is_bleed(st) -> bool:
        c = contents(st.values.get("messages", []))
        return "ход 2-ОРИГИНАЛ" in c and "ход 2-ФОРК" in c

    completed = [st for st in full_history if is_completed(st)]
    completed_bleed = [(_short(st.config), contents(st.values["messages"])) for st in completed if is_bleed(st)]
    staging_bleed = [st for st in full_history if not is_completed(st) and is_bleed(st)]

    if staging_bleed:
        print(f"\n  ℹ [{label}] склейка на {len(staging_bleed)} staging-чекпоинт(ах) "
              f"(ожидаемо для DeltaChannel; фронт их не строит в дерево)")
    if completed_bleed:
        print(f"\n  ❌ [{label}] СКЛЕЙКА СРЕДИ ЗАВЕРШЁННЫХ состояний (это уже видно фронту!):")
        for cid, c in completed_bleed:
            print(f"    checkpoint={cid}: {c}")
        return False
    print(f"\n  ✓ [{label}] завершённых состояний: {len(completed)}, склейки среди них нет "
          f"(прод-инвариант соблюдён)")
    return True


# --------------------------------------------------------------------------- #
# Сценарий 3: правка человеческого сообщения + регенерация (канонический UI-flow).
# --------------------------------------------------------------------------- #
async def test_edit_message(graph):
    print("\n##################  СЦЕНАРИЙ 3: правка сообщения + регенерация (sqlite)  ##################")
    config = {"configurable": {"thread_id": "edit"}}
    first = await graph.ainvoke(
        {"messages": [HumanMessage(content="оригинальный вопрос", id="h1")]}, config
    )
    await dump(graph, config, "до редактирования")
    old_ai_id = next(m.id for m in first["messages"] if m.type == "ai")

    # Правка по id + срез устаревшего ответа одним апдейтом.
    await graph.aupdate_state(
        config,
        {
            "messages": [
                RemoveMessage(id=old_ai_id),
                HumanMessage(content="ОТРЕДАКТИРОВАННЫЙ вопрос", id="h1"),
            ]
        },
    )
    edited = await dump(graph, config, "после правки (replace by id + RemoveMessage)")
    assert next(m for m in edited if m.id == "h1").content == "ОТРЕДАКТИРОВАННЫЙ вопрос"
    assert all(m.id != old_ai_id for m in edited), "старый AI-ответ должен быть удалён"

    # Регенерация: заходим заново через START — echo видит правленый текст.
    result = await graph.ainvoke({"messages": []}, config)
    print(f"\n  ответ echo после правки: {result['messages'][-1].content!r}")
    assert result["messages"][-1].content == "echo: ОТРЕДАКТИРОВАННЫЙ вопрос"

    print("  ✓ правка по id + RemoveMessage старого ответа + регенерация работают")

    # Доп. проверка: полный сброс канала через REMOVE_ALL_MESSAGES (не фатально —
    # это отдельный край DeltaChannel, репортим как находку).
    await graph.aupdate_state(config, {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)]})
    cleared = (await graph.aget_state(config)).values["messages"]
    if cleared == []:
        print("  ✓ RemoveMessage(REMOVE_ALL_MESSAGES) очищает канал")
        return True
    print(f"  ⚠ RemoveMessage(REMOVE_ALL_MESSAGES) НЕ очистил канал на DeltaChannel+sqlite "
          f"(осталось {len(cleared)} сообщ.)")
    return False


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_delta_forks.sqlite")
        print(f"sqlite db: {db_path}")
        async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
            delta_graph = build_graph(saver, DeltaState)
            plain_graph = build_graph(saver, PlainState)

            await test_basic_conversation(delta_graph)
            delta_ok = await test_fork_no_branch_bleed(delta_graph, "DeltaChannel", "fork_delta")
            # Контроль: обычный add_messages-канал на том же сценарии.
            plain_ok = await test_fork_no_branch_bleed(plain_graph, "add_messages", "fork_plain")
            clear_ok = await test_edit_message(delta_graph)

    print("\n\n" + "=" * 70)
    print(f"ИТОГ (AsyncSqliteSaver, snapshot_frequency={SNAPSHOT_FREQUENCY} = прод):")
    print(f"  форк, DeltaChannel : {'⚠ внезапно чисто (проверь snapshot_frequency)' if delta_ok else '❌ склейка в завершённых (ОЖИДАЕМО — потому и не используем)'}")
    print(f"  форк, add_messages : {'✅ завершённые состояния чисты' if plain_ok else '❌ СКЛЕЙКА В ЗАВЕРШЁННЫХ (РЕГРЕСС!)'}")
    print(f"  правка+регенерация : ✅ работает (канонический UI-flow)")
    print(f"  REMOVE_ALL_MESSAGES: {'✅ очищает' if clear_ok else '⚠ не очищает на DeltaChannel+sqlite'}")
    print("=" * 70)
    if not plain_ok:
        print(
            "\nРЕГРЕСС: прод-канал add_messages дал склейку веток в завершённых состояниях.\n"
            "Это не должно происходить — проверь langgraph-checkpoint-sqlite и add_messages."
        )
        raise SystemExit(1)
    print(
        f"\nВывод: на прод-snapshot_frequency={SNAPSHOT_FREQUENCY} DeltaChannel склеивает ветки\n"
        "в ЗАВЕРШЁННЫХ состояниях при форке (видно фронту) — поэтому в types.py остаётся\n"
        "add_messages, который иммунен. Не переводить messages на DeltaChannel.\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
