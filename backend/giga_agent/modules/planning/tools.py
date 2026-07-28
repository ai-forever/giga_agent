"""Инструменты режима планирования: update_plan и present_plan.

Оба — state-mutating: возвращают Command(update={...}). Обязательное требование
tool_node (core/agent/tool_node.py): в update должен быть ToolMessage с
tool_call_id текущего вызова, иначе ValueError.

См. docs/PLANNING_MODE.md.
"""

from __future__ import annotations

from typing import Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph.ui import push_ui_message
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    tool_extras,
)

TodoStatus = Literal["pending", "in_progress", "completed", "skipped"]


def _push_plan(plan: list[dict], tool_call_id: str) -> None:
    """Шлёт план на фронт по каналу кастомного UI (как deep_research).

    Чат стримится в режиме messages, поэтому новое поле state["plan"] само не
    долетает — пушим явно. Вне графового контекста (CLI/тесты) writer'а нет,
    поэтому глушим ошибку, чтобы не ронять тул.
    """
    try:
        push_ui_message("plan_update", {"plan": plan, "tool_call_id": tool_call_id})
    except Exception:  # noqa: BLE001 - стрим UI не критичен для исполнения
        pass


class TodoItemArg(BaseModel):
    """Один пункт плана."""

    id: str = Field(description="Стабильный идентификатор пункта (например, '1', '2').")
    title: str = Field(
        description=(
            "Короткая формулировка задачи НА ЯЗЫКЕ ПОЛЬЗОВАТЕЛЯ. "
            "Если пользователь пишет по-русски — title тоже по-русски."
        )
    )
    status: TodoStatus = Field(
        default="pending",
        description="pending | in_progress | completed | skipped.",
    )
    note: str | None = Field(
        default=None,
        description="Необязательно: краткий результат или причина skip.",
    )


def _to_dicts(todos: list[TodoItemArg]) -> list[dict]:
    out: list[dict] = []
    for t in todos:
        item: dict = {"id": t.id, "title": t.title, "status": t.status}
        if t.note:
            item["note"] = t.note
        out.append(item)
    return out


def _validate(todos: list[TodoItemArg]) -> str | None:
    """Возвращает текст ошибки или None, если план валиден."""
    in_progress = [t for t in todos if t.status == "in_progress"]
    if len(in_progress) > 1:
        return (
            "В плане больше одного пункта 'in_progress' "
            f"({len(in_progress)}). Оставь ровно один активный пункт."
        )
    ids = [t.id for t in todos]
    if len(ids) != len(set(ids)):
        return "Идентификаторы пунктов (id) должны быть уникальными."
    return None


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        plan_mode=ToolPlanMode.ALLOW,
        repl_save=False,
    ),
)
async def update_plan(
    todos: list[TodoItemArg],
    runtime: ToolRuntime,
) -> Command:
    """Создаёт или обновляет список задач (todo) текущего хода.

    Вызывай для запросов из нескольких нетривиальных шагов: сначала чтобы
    выложить план, потом чтобы отмечать прогресс. Передавай ВЕСЬ список целиком
    (он заменяет предыдущий). Держи ровно один пункт 'in_progress'. Передай
    пустой список, чтобы очистить план.

    Args:
        todos: Полный список пунктов плана со статусами.
    """
    tool_call_id = runtime.tool_call_id
    error = _validate(todos)
    if error:
        return Command(
            update={
                "messages": [
                    ToolMessage(f"План не обновлён. {error}", tool_call_id=tool_call_id)
                ]
            }
        )
    plan = _to_dicts(todos)
    done = sum(1 for t in plan if t["status"] in ("completed", "skipped"))
    _push_plan(plan, tool_call_id)
    return Command(
        update={
            "plan": plan,
            "messages": [
                ToolMessage(
                    f"План обновлён: {done}/{len(plan)} готово.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool(
    parse_docstring=True,
    extras=tool_extras(
        ToolEffect.WRITE,
        plan_mode=ToolPlanMode.ALLOW,
        repl_save=False,
    ),
)
async def present_plan(
    todos: list[TodoItemArg],
    runtime: ToolRuntime,
) -> Command:
    """Показывает финальный план пользователю и ждёт подтверждения (plan mode).

    Вызывай ТОЛЬКО в режиме планирования, когда список шагов готов. Работа
    приостановится; пользователь подтвердит, отредактирует или отклонит план.

    Args:
        todos: Финальный список шагов для подтверждения.
    """
    tool_call_id = runtime.tool_call_id
    error = _validate(todos)
    if error:
        return Command(
            update={
                "messages": [
                    ToolMessage(f"План не показан. {error}", tool_call_id=tool_call_id)
                ]
            }
        )

    proposed = _to_dicts(todos)
    # Пауза: фронт получает payload {"type": "plan_approval", ...} и резюмит run
    # через Command(resume=...). Контракт совпадает с tool_result.py:447.
    decision = interrupt({"type": "plan_approval", "plan": proposed})
    action = (decision or {}).get("action", "approve")

    if action == "reject":
        feedback = (decision or {}).get("feedback") or "Пользователь отклонил план."
        # Остаёмся в plan mode, фидбек влетает как сообщение пользователя → re-plan.
        return Command(
            update={
                "messages": [
                    ToolMessage("План отклонён.", tool_call_id=tool_call_id),
                    HumanMessage(feedback),
                ]
            }
        )

    # approve | edit: переключаемся в normal и идём исполнять (возможно отред. план).
    final_plan = (decision or {}).get("plan") or proposed
    _push_plan(final_plan, tool_call_id)
    return Command(
        update={
            "plan": final_plan,
            "mode": "normal",
            "messages": [ToolMessage("План подтверждён.", tool_call_id=tool_call_id)],
        }
    )
