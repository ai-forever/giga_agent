"""
Трассировка reducer'а DeltaChannel при форке — чтобы понять, ГДЕ слипаются ветки.

Идея:
    * подменяем reducer канала на обёртку tracing_reducer, которая на каждый
      вызов печатает: фазу, компактный langgraph-стек (кто звал — `update`
      живого шага vs `replay_writes` реконструкции), входной state и batch
      writes;
    * дополнительно оборачиваем AsyncSqliteSaver.aget_delta_channel_history —
      именно он на реконструкции отдаёт цепочку предков (chain_by_ch) и writes,
      которые потом скармливаются reducer'у через replay_writes. Если ветки
      слипаются, видно либо в цепочке (chain), либо в наборе writes.

Минимальный сценарий: 1 ход → форк из прошлого вторым ходом → читаем историю
через aget_state_history и ловим состояние, где есть и ОРИГИНАЛ, и ФОРК.

Запуск:  uv run python scripts/trace_delta_reducer.py
"""

from __future__ import annotations

import asyncio
import tempfile
import traceback
from pathlib import Path
from typing import Annotated, Any, Sequence

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import _messages_delta_reducer
from typing_extensions import TypedDict

SNAPSHOT_FREQUENCY = 2
PHASE = "init"  # выставляется по ходу сценария, попадает в каждую трейс-строку


def _phase(name: str) -> None:
    global PHASE
    PHASE = name
    print(f"\n{'─' * 78}\n▶ ФАЗА: {name}\n{'─' * 78}")


def _short_msg(m: Any) -> str:
    """Компактное представление одного writes-элемента/сообщения."""
    t = getattr(m, "type", None)
    c = getattr(m, "content", None)
    if t is not None:
        mid = (getattr(m, "id", None) or "????")[-4:]
        return f"{t}:{c!r}#{mid}"
    return repr(m)


def _render_writes(writes: Sequence[Any]) -> str:
    """writes для messages-канала — это список батчей, каждый = список сообщений."""
    parts = []
    for w in writes:
        if isinstance(w, (list, tuple)):
            parts.append("[" + ", ".join(_short_msg(x) for x in w) + "]")
        else:
            parts.append(_short_msg(w))
    return " | ".join(parts) if parts else "(пусто)"


def _lg_stack(depth: int = 7) -> str:
    """Последние langgraph-фреймы стека: показывает, КТО зовёт reducer."""
    frames = traceback.extract_stack()[:-2]  # отбрасываем сам tracing_reducer
    picked = [
        f"{fr.name}@{Path(fr.filename).name}:{fr.lineno}"
        for fr in frames
        if "langgraph" in fr.filename
    ]
    return " ◂ ".join(reversed(picked[-depth:])) or "(нет langgraph-фреймов)"


# --------------------------------------------------------------------------- #
# Свой reducer-обёртка: делегирует прод-реализации, но трассирует каждый вызов.
# --------------------------------------------------------------------------- #
def tracing_reducer(state: Any, writes: Sequence[Any]) -> Any:
    in_contents = [getattr(m, "content", m) for m in (state or [])]
    out = _messages_delta_reducer(state, writes)
    out_contents = [getattr(m, "content", m) for m in (out or [])]
    merged = "ход 2-ОРИГИНАЛ" in out_contents and "ход 2-ФОРК" in out_contents
    flag = "  ⚠️⚠️ СЛИПЛИСЬ ВЕТКИ" if merged else ""
    print(
        f"\n  ┌─ reducer вызван [{PHASE}]{flag}"
        f"\n  │  кто звал : {_lg_stack()}"
        f"\n  │  state in : {in_contents}"
        f"\n  │  writes   : {_render_writes(writes)}"
        f"\n  └─ state out: {out_contents}"
    )
    return out


class DeltaState(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(reducer=tracing_reducer, snapshot_frequency=SNAPSHOT_FREQUENCY),
    ]


def echo(state) -> dict:
    last = state["messages"][-1]
    return {"messages": [AIMessage(content=f"echo: {getattr(last, 'content', '')}")]}


def build_graph(checkpointer):
    g = StateGraph(DeltaState)
    g.add_node("echo", echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- #
# Обёртка над источником writes: видно цепочку предков и сырые writes,
# которые движок передаёт в replay_writes → reducer.
# --------------------------------------------------------------------------- #
def patch_saver_history(saver: AsyncSqliteSaver) -> None:
    orig = saver.aget_delta_channel_history

    async def traced(*, config, channels):
        cid = (config.get("configurable", {}) or {}).get("checkpoint_id")
        result = await orig(config=config, channels=channels)
        for ch, hist in result.items():
            writes = hist.get("writes", [])
            print(
                f"\n  ╔═ aget_delta_channel_history [{PHASE}]"
                f"\n  ║  target checkpoint: {(cid or '????')[-12:]}  channel={ch!r}"
                f"\n  ║  writes для replay ({len(writes)}):"
            )
            for w in writes:
                # PendingWrite = (task_id, channel, value); value = батч сообщений.
                val = w[2] if isinstance(w, tuple) and len(w) >= 3 else w
                print(f"  ║    • {_render_writes([val])}")
            print("  ╚═")
        return result

    saver.aget_delta_channel_history = traced  # type: ignore[method-assign]


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "trace.sqlite")
        async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
            patch_saver_history(saver)
            graph = build_graph(saver)
            config = {"configurable": {"thread_id": "t"}}

            _phase("ход 1 (живой шаг)")
            await graph.ainvoke({"messages": [HumanMessage(content="ход 1")]}, config)

            _phase("ход 2-ОРИГИНАЛ (живой шаг)")
            await graph.ainvoke(
                {"messages": [HumanMessage(content="ход 2-ОРИГИНАЛ")]}, config
            )

            _phase("ищем точку форка (messages==2)")
            history = [s async for s in graph.aget_state_history(config)]
            fork_point = next(
                s for s in history if len(s.values.get("messages", [])) == 2
            )
            fork_cfg = fork_point.config
            print(
                f"  точка форка: checkpoint={fork_cfg['configurable']['checkpoint_id'][-12:]}"
            )

            _phase("ход 2-ФОРК (живой шаг от точки форка)")
            await graph.ainvoke(
                {"messages": [HumanMessage(content="ход 2-ФОРК")]}, fork_cfg
            )

            _phase("ЧТЕНИЕ ИСТОРИИ через aget_state_history (здесь и ищем слипание)")
            full = [s async for s in graph.aget_state_history(config)]
            print(f"\n  === итоговая история ({len(full)} состояний) ===")
            for st in full:
                c = [getattr(m, "content", m) for m in st.values.get("messages", [])]
                merged = "ход 2-ОРИГИНАЛ" in c and "ход 2-ФОРК" in c
                cid = st.config["configurable"]["checkpoint_id"][-12:]
                par = (
                    (st.parent_config or {})
                    .get("configurable", {})
                    .get("checkpoint_id")
                )
                print(
                    f"    {'⚠️' if merged else '  '} checkpoint={cid}  parent={(par or '----')[-12:]}: {c}"
                )

            _phase("СЫРЫЕ ТАБЛИЦЫ sqlite (доказательство корня)")
            await _dump_raw_tables(saver, thread_id="t")


async def _dump_raw_tables(saver: AsyncSqliteSaver, thread_id: str) -> None:
    """Печатает топологию чекпоинтов и writes канала 'messages' прямо из БД.

    Корень бага: writes двух форкнутых супершагов лежат под ОДНИМ
    checkpoint_id (родителем-точкой форка), а Stage2 выбирает их по
    `checkpoint_id IN (цепочка)` — то есть тащит writes обеих веток.
    """
    async with saver.lock, saver.conn.cursor() as cur:
        await cur.execute(
            "SELECT checkpoint_id, parent_checkpoint_id FROM checkpoints "
            "WHERE thread_id=? ORDER BY checkpoint_id",
            (thread_id,),
        )
        ckpts = await cur.fetchall()
        await cur.execute(
            "SELECT checkpoint_id, task_id, idx, type, value FROM writes "
            "WHERE thread_id=? AND channel='messages' ORDER BY checkpoint_id, idx",
            (thread_id,),
        )
        rows = await cur.fetchall()

    # Сколько детей у каждого чекпоинта → точка форка = >1 ребёнка.
    children: dict[str, int] = {}
    for _cid, parent in ckpts:
        if parent:
            children[parent] = children.get(parent, 0) + 1
    writes_by_cid: dict[str, list[str]] = {}
    for cid, _task_id, _idx, type_tag, value in rows:
        val = saver.serde.loads_typed((type_tag, value))
        writes_by_cid.setdefault(cid, []).append(_render_writes([val]))

    print("\n  checkpoints (checkpoint_id ◂ parent | детей | write канала messages):")
    for cid, parent in ckpts:
        n = children.get(cid, 0)
        w = " ; ".join(writes_by_cid.get(cid, [])) or "—"
        is_fork = n > 1
        carries = bool(writes_by_cid.get(cid))
        tag = ""
        if is_fork:
            tag = "  ◀── ТОЧКА ФОРКА"
            if carries:
                tag += " + НЕСЁТ WRITE → этот write протекает в обе ветки ⚠️"
        print(
            f"    {cid[-12:]}  ◂  {(parent or '----')[-12:]}  | детей={n} | write={w}{tag}"
        )

    print(
        "\n  ВЫВОД: writes хранятся по checkpoint_id; Stage2 берёт их по "
        "`checkpoint_id IN (цепочка предков)`.\n"
        "  Write точки форки попадает в цепочку ОБЕИХ дочерних веток → reducer "
        "склеивает соседнюю ветку.\n"
        "  Reducer и replay_writes корректны; баг — в attribution writes при "
        "реконструкции (langgraph-checkpoint-sqlite)."
    )


if __name__ == "__main__":
    asyncio.run(main())
