"""Инструменты подробного plan-mode и рабочего todo-листа."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field

from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    tool_extras,
)

TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]
PLANNING_KWARG = "planning"


class TodoPatchArg(BaseModel):
    """Создание нового todo или частичное изменение существующего."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description=(
            "ID существующего todo для изменения. Не передавай id при создании: "
            "backend назначит следующий числовой идентификатор."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "Содержание todo на языке пользователя. Обязательно при создании; "
            "при изменении можно не передавать."
        ),
    )
    status: TodoStatus | None = Field(
        default=None,
        description=(
            "Статус todo: pending, in_progress, completed или cancelled. "
            "При создании по умолчанию pending."
        ),
    )
    note: str | None = Field(
        default=None,
        description=(
            "Необязательная краткая заметка. Передай null в patch существующего "
            "todo, чтобы удалить заметку."
        ),
    )


def _tool_message(
    runtime: ToolRuntime,
    content: str,
    *,
    is_error: bool = False,
    planning: dict[str, Any] | None = None,
) -> ToolMessage:
    additional_kwargs = {PLANNING_KWARG: planning} if planning is not None else {}
    return ToolMessage(
        content=content,
        tool_call_id=runtime.tool_call_id,
        status="error" if is_error else "success",
        additional_kwargs=additional_kwargs,
    )


def _error(runtime: ToolRuntime, content: str) -> Command:
    return Command(
        update={"messages": [_tool_message(runtime, content, is_error=True)]}
    )


def _runtime_state(runtime: ToolRuntime) -> dict[str, Any]:
    state = runtime.state
    if isinstance(state, dict):
        return state
    if hasattr(state, "model_dump"):
        return state.model_dump()
    return dict(state)


def _clean_content(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _next_seq(todos: list[dict[str, Any]], stored_seq: int | None) -> int:
    numeric_ids = [int(t["id"]) for t in todos if str(t.get("id", "")).isdigit()]
    return max([stored_seq or 0, *numeric_ids])


def _patch_fields(patch: TodoPatchArg) -> set[str]:
    return set(patch.model_fields_set) - {"id"}


def _apply_patches(
    current: list[dict[str, Any]],
    patches: list[TodoPatchArg],
    seq: int,
    *,
    locked: bool = False,
) -> tuple[list[dict[str, Any]], int, list[str], str | None]:
    """Применить todo-patches к копии списка, не меняя входные данные."""
    result = deepcopy(current)
    index = {str(item.get("id")): pos for pos, item in enumerate(result)}
    if len(index) != len(result):
        return current, seq, [], "В текущем todo-листе обнаружены повторяющиеся id."

    patch_ids = [patch.id for patch in patches if patch.id is not None]
    if len(patch_ids) != len(set(patch_ids)):
        return current, seq, [], "Один id нельзя изменять несколько раз за вызов."

    assigned: list[str] = []
    for patch in patches:
        fields = _patch_fields(patch)
        if patch.id is None:
            if "id" in patch.model_fields_set:
                return (
                    current,
                    seq,
                    [],
                    "При создании todo поле id нельзя передавать, включая null.",
                )
            if locked:
                return (
                    current,
                    seq,
                    [],
                    "После подтверждения плана нельзя создавать новые todo.",
                )
            content = _clean_content(patch.content)
            if content is None:
                return current, seq, [], "При создании todo обязателен content."
            if "status" in patch.model_fields_set and patch.status is None:
                return current, seq, [], "status создаваемого todo не может быть null."
            seq += 1
            todo_id = str(seq)
            item: dict[str, Any] = {
                "id": todo_id,
                "content": content,
                "status": patch.status or "pending",
            }
            if "note" in patch.model_fields_set and patch.note:
                item["note"] = patch.note.strip()
            result.append(item)
            index[todo_id] = len(result) - 1
            assigned.append(todo_id)
            continue

        todo_id = patch.id
        if todo_id not in index:
            return (
                current,
                seq,
                [],
                f"Todo с id={todo_id!r} не существует. Для создания не передавай id.",
            )
        if not fields:
            return current, seq, [], f"Patch todo id={todo_id!r} не содержит изменений."
        if locked and not fields <= {"status", "note"}:
            return (
                current,
                seq,
                [],
                "После подтверждения плана можно менять только status и note.",
            )

        item = result[index[todo_id]]
        if "content" in fields:
            content = _clean_content(patch.content)
            if content is None:
                return (
                    current,
                    seq,
                    [],
                    "content существующего todo не может быть пустым.",
                )
            item["content"] = content
        if "status" in fields:
            if patch.status is None:
                return current, seq, [], "status существующего todo не может быть null."
            item["status"] = patch.status
        if "note" in fields:
            if patch.note is None or not patch.note.strip():
                item.pop("note", None)
            else:
                item["note"] = patch.note.strip()

    return result, seq, assigned, None


def _replace_todos(
    patches: list[TodoPatchArg],
) -> tuple[list[dict[str, Any]], int, list[str], str | None]:
    if len(patches) < 2:
        return [], 0, [], "При полной замене требуется минимум два todo."
    for patch in patches:
        if "id" in patch.model_fields_set:
            return (
                [],
                0,
                [],
                "При полной замене нельзя передавать поле id, включая null.",
            )

    result: list[dict[str, Any]] = []
    assigned: list[str] = []
    for position, patch in enumerate(patches, start=1):
        content = _clean_content(patch.content)
        if content is None:
            return [], 0, [], "При создании каждого todo обязателен content."
        if "status" in patch.model_fields_set and patch.status is None:
            return [], 0, [], "status создаваемого todo не может быть null."
        todo_id = str(position)
        item: dict[str, Any] = {
            "id": todo_id,
            "content": content,
            "status": patch.status or "pending",
        }
        if "note" in patch.model_fields_set and patch.note:
            item["note"] = patch.note.strip()
        result.append(item)
        assigned.append(todo_id)
    return result, len(result), assigned, None


def _assigned_text(assigned: list[str]) -> str:
    if not assigned:
        return ""
    return " Созданным todo назначены id: " + ", ".join(assigned) + "."


@tool(
    description=(
        "Создаёт и обновляет структурированный список задач текущего рабочего "
        "сеанса. Используй в обычном режиме, когда чеклист помогает отслеживать "
        "ход многошаговой задачи."
    ),
    extras=tool_extras(
        ToolEffect.WRITE,
        plan_mode=ToolPlanMode.DENY,
        repl_save=False,
    ),
)
async def write_todo(
    merge: bool,
    todos: list[TodoPatchArg],
    runtime: ToolRuntime,
) -> Command:
    """Создать, заменить или частично обновить рабочий todo-лист."""
    state = _runtime_state(runtime)
    if state.get("mode") == "plan":
        return _error(runtime, "write_todo недоступен в режиме планирования.")
    if not todos:
        return _error(runtime, "Список todos не может быть пустым.")

    current = list(state.get("todos") or [])
    seq = _next_seq(current, state.get("todo_id_seq"))
    locked = bool(state.get("plan_approved"))
    if locked and not merge:
        return _error(
            runtime,
            "После подтверждения плана нельзя полностью заменять todo-лист.",
        )

    if merge:
        updated, next_seq, assigned, error = _apply_patches(
            current,
            todos,
            seq,
            locked=locked,
        )
    else:
        updated, next_seq, assigned, error = _replace_todos(todos)
    if error:
        return _error(runtime, f"Todo не обновлён. {error}")

    done = sum(t["status"] in ("completed", "cancelled") for t in updated)
    snapshot = {
        "type": "todo_snapshot",
        "todos": updated,
        "assigned_ids": assigned,
    }
    return Command(
        update={
            "todos": updated,
            "todo_id_seq": next_seq,
            "messages": [
                _tool_message(
                    runtime,
                    f"Todo обновлён: {done}/{len(updated)} завершено."
                    + _assigned_text(assigned),
                    planning=snapshot,
                )
            ],
        }
    )


@tool(
    description=(
        "Создаёт или точечно обновляет подробный Markdown-план и его todo-пункты "
        "в режиме планирования. Текст изменяется только через точную пару "
        "find_string/replace_string; todo без id создаётся, todo с id обновляется."
    ),
    extras=tool_extras(
        ToolEffect.WRITE,
        plan_mode=ToolPlanMode.ALLOW,
        repl_save=False,
    ),
)
async def update_plan(
    runtime: ToolRuntime,
    find_string: str | None = None,
    replace_string: str | None = None,
    todos: list[TodoPatchArg] | None = None,
    remove_todo_ids: list[str] | None = None,
) -> Command:
    """Атомарно обновить черновик подробного плана."""
    state = _runtime_state(runtime)
    if state.get("mode") != "plan":
        return _error(runtime, "update_plan доступен только в режиме планирования.")

    has_text_operation = find_string is not None or replace_string is not None
    has_todo_operation = bool(todos) or bool(remove_todo_ids)
    if not has_text_operation and not has_todo_operation:
        return _error(runtime, "Не передано ни одного изменения плана.")

    current_content = (
        str(state.get("plan_content") or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    updated_content = current_content
    if has_text_operation:
        if find_string is None or replace_string is None:
            return _error(
                runtime,
                "find_string и replace_string должны передаваться вместе.",
            )
        find_string = find_string.replace("\r\n", "\n").replace("\r", "\n")
        replace_string = replace_string.replace("\r\n", "\n").replace("\r", "\n")
        if find_string == replace_string:
            return _error(runtime, "find_string и replace_string не должны совпадать.")
        if not current_content:
            if find_string != "":
                return _error(
                    runtime,
                    "Для создания первого plan_content передай find_string=''.",
                )
            if not replace_string.strip():
                return _error(runtime, "Первый plan_content не может быть пустым.")
            updated_content = replace_string
        else:
            if not find_string:
                return _error(
                    runtime, "В непустом плане find_string не может быть пустым."
                )
            count = current_content.count(find_string)
            if count != 1:
                return _error(
                    runtime,
                    f"find_string должен встречаться ровно один раз; найдено {count}.",
                )
            updated_content = current_content.replace(find_string, replace_string, 1)

    current_todos = list(state.get("todos") or [])
    seq = _next_seq(current_todos, state.get("todo_id_seq"))
    removals = list(remove_todo_ids or [])
    if len(removals) != len(set(removals)):
        return _error(runtime, "remove_todo_ids содержит повторяющиеся id.")
    patched_ids = {patch.id for patch in todos or [] if patch.id is not None}
    overlap = patched_ids.intersection(removals)
    if overlap:
        return _error(
            runtime,
            "Нельзя одновременно изменить и удалить todo: "
            + ", ".join(sorted(overlap)),
        )

    existing_ids = {str(item.get("id")) for item in current_todos}
    missing_removals = [todo_id for todo_id in removals if todo_id not in existing_ids]
    if missing_removals:
        return _error(
            runtime,
            "Нельзя удалить несуществующие todo: " + ", ".join(missing_removals),
        )
    after_removal = [
        deepcopy(item) for item in current_todos if str(item.get("id")) not in removals
    ]
    updated_todos, next_seq, assigned, error = _apply_patches(
        after_removal,
        list(todos or []),
        seq,
    )
    if error:
        return _error(runtime, f"План не обновлён. {error}")

    return Command(
        update={
            "plan_content": updated_content,
            "todos": updated_todos,
            "todo_id_seq": next_seq,
            "messages": [
                _tool_message(
                    runtime,
                    "Черновик плана обновлён." + _assigned_text(assigned),
                )
            ],
        }
    )


def _validate_present_plan(
    plan_content: str,
    todos: list[dict[str, Any]],
) -> str | None:
    if not plan_content.strip():
        return "plan_content отсутствует или пуст."
    if len(todos) < 2:
        return "Для подтверждения требуется минимум два todo."
    ids = [str(todo.get("id", "")) for todo in todos]
    if not all(ids) or len(ids) != len(set(ids)):
        return "Todos должны иметь уникальные непустые id."
    for todo in todos:
        if not str(todo.get("content", "")).strip():
            return f"Todo id={todo.get('id')!r} не содержит content."
        if todo.get("status") != "pending":
            return "Перед подтверждением все todo должны иметь status='pending'."
    return None


@tool(
    description=(
        "Показывает готовый подробный план пользователю и приостанавливает "
        "выполнение до подтверждения. Вызывай без аргументов только после того, "
        "как update_plan создал plan_content и минимум два pending todo."
    ),
    extras=tool_extras(
        ToolEffect.WRITE,
        plan_mode=ToolPlanMode.ALLOW,
        repl_save=False,
    ),
)
async def present_plan(runtime: ToolRuntime) -> Command:
    """Показать сохранённый в state план и дождаться решения пользователя."""
    state = _runtime_state(runtime)
    if state.get("mode") != "plan":
        return _error(runtime, "present_plan доступен только в режиме планирования.")

    plan_content = str(state.get("plan_content") or "")
    todos = deepcopy(list(state.get("todos") or []))
    error = _validate_present_plan(plan_content, todos)
    if error:
        return _error(runtime, f"План не показан. {error}")

    decision = interrupt(
        {
            "type": "plan_approval",
            "plan_content": plan_content,
            "todos": todos,
        }
    )
    action = (decision or {}).get("action")
    if action == "reject":
        feedback = str((decision or {}).get("feedback") or "").strip()
        if not feedback:
            return _error(runtime, "Для отклонения плана обязателен feedback.")
        return Command(
            update={
                "plan_approved": False,
                "messages": [
                    _tool_message(runtime, "План отклонён."),
                    HumanMessage(feedback),
                ],
            }
        )
    if action != "approve":
        return _error(runtime, "Неизвестное действие с планом.")

    snapshot = {
        "type": "approved_plan",
        "plan_content": plan_content,
        "todos": todos,
    }
    return Command(
        update={
            "mode": "normal",
            "plan_approved": True,
            "messages": [
                _tool_message(
                    runtime,
                    "План подтверждён.",
                    planning=snapshot,
                )
            ],
        }
    )
