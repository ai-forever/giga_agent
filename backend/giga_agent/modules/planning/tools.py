"""Инструменты подробного plan-mode и рабочего todo-листа."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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


def _todo_error(runtime: ToolRuntime, content: str) -> Command:
    """Сохранить неудачную попытку изменить todo вместе с текущим снимком."""
    state = _runtime_state(runtime)
    snapshot = {
        "type": "todo_error",
        "todos": deepcopy(list(state.get("todos") or [])),
    }
    return Command(
        update={
            "messages": [
                _tool_message(
                    runtime,
                    content,
                    is_error=True,
                    planning=snapshot,
                )
            ]
        }
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

    patch_ids = [patch.id.strip() for patch in patches if patch.id is not None]
    if any(not todo_id for todo_id in patch_ids):
        return current, seq, [], "id создаваемого todo не может быть пустым."
    if len(patch_ids) != len(set(patch_ids)):
        return current, seq, [], "Один id нельзя изменять несколько раз за вызов."

    assigned: list[str] = []
    for patch in patches:
        fields = _patch_fields(patch)
        todo_id = patch.id.strip() if patch.id is not None else None
        if todo_id is None or todo_id not in index:
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
            if todo_id is None:
                seq += 1
                while str(seq) in index:
                    seq += 1
                todo_id = str(seq)
            elif todo_id.isdigit():
                seq = max(seq, int(todo_id))
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

        if not fields:
            return current, seq, [], f"Patch todo id={todo_id!r} не содержит изменений."

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
    explicit_ids = [patch.id.strip() for patch in patches if patch.id is not None]
    if any(not todo_id for todo_id in explicit_ids):
        return [], 0, [], "id создаваемого todo не может быть пустым."
    if len(explicit_ids) != len(set(explicit_ids)):
        return [], 0, [], "Todos должны иметь уникальные id."

    result: list[dict[str, Any]] = []
    assigned: list[str] = []
    used_ids = set(explicit_ids)
    seq = max((int(todo_id) for todo_id in used_ids if todo_id.isdigit()), default=0)
    for patch in patches:
        content = _clean_content(patch.content)
        if content is None:
            return [], 0, [], "При создании каждого todo обязателен content."
        if "status" in patch.model_fields_set and patch.status is None:
            return [], 0, [], "status создаваемого todo не может быть null."
        if patch.id is None:
            seq += 1
            while str(seq) in used_ids:
                seq += 1
            todo_id = str(seq)
            used_ids.add(todo_id)
        else:
            todo_id = patch.id.strip()
        item: dict[str, Any] = {
            "id": todo_id,
            "content": content,
            "status": patch.status or "pending",
        }
        if "note" in patch.model_fields_set and patch.note:
            item["note"] = patch.note.strip()
        result.append(item)
        assigned.append(todo_id)
    return result, seq, assigned, None


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
        return _todo_error(runtime, "write_todo недоступен в режиме планирования.")
    if not todos:
        return _todo_error(runtime, "Список todos не может быть пустым.")

    current = list(state.get("todos") or [])
    seq = _next_seq(current, state.get("todo_id_seq"))
    # Todo created after approving a plan without one are working notes, not a
    # confirmed part of the plan. Preserve that decision after the first write.
    todos_editable = bool(state.get("todos_editable", not current))
    locked = bool(state.get("plan_approved")) and not todos_editable
    if locked and not merge:
        return _todo_error(
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
        return _todo_error(runtime, f"Todo не обновлён. {error}")

    done = sum(t["status"] in ("completed", "cancelled") for t in updated)
    snapshot = {
        "type": "todo_snapshot",
        "todos": updated,
        "assigned_ids": assigned,
    }
    update: dict[str, Any] = {
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
    if state.get("plan_approved"):
        update["todos_editable"] = todos_editable
    return Command(update=update)


@tool(
    description=(
        "Создаёт или точечно обновляет подробный Markdown-план и его todo-пункты "
        "в режиме планирования. Для пустого плана достаточно replace_string; "
        "дальнейшие правки требуют точную пару find_string/replace_string. Todo "
        "без id создаётся, todo с id обновляется."
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
        str(state.get("plan_content") or "").replace("\r\n", "\n").replace("\r", "\n")
    )
    updated_content = current_content
    if has_text_operation:
        if replace_string is None:
            return _error(
                runtime,
                "Для изменения текста плана обязателен replace_string.",
            )
        if find_string is None:
            if current_content:
                return _error(
                    runtime,
                    "В непустом плане find_string обязателен.",
                )
            find_string = ""
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

    readiness_error = _validate_present_plan(updated_content, updated_todos)
    if readiness_error:
        next_step = (
            " Режим планирования остаётся активным. План пока нельзя показать: "
            f"{readiness_error} Продолжи read-only исследование, при необходимости "
            "задай существенные вопросы через ask_questions и обнови черновик "
            "через update_plan."
        )
    else:
        next_step = (
            " Режим планирования остаётся активным. Если план уже полностью "
            "проработан, вызови present_plan без аргументов; иначе продолжи "
            "read-only исследование, задай существенные вопросы через "
            "ask_questions или уточни черновик через update_plan."
        )

    return Command(
        update={
            "plan_content": updated_content,
            "todos": updated_todos,
            "todo_id_seq": next_seq,
            "messages": [
                _tool_message(
                    runtime,
                    "Черновик плана обновлён." + _assigned_text(assigned) + next_step,
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
    if not todos:
        return None
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
        "как update_plan создал непустой plan_content. Todo необязательны; если "
        "они есть, все должны иметь status='pending'."
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
        snapshot = {
            "type": "rejected_plan",
            "plan_content": plan_content,
            "todos": todos,
        }
        return Command(
            update={
                "plan_approved": False,
                "messages": [
                    _tool_message(
                        runtime,
                        "План отменён.",
                        planning=snapshot,
                    ),
                    AIMessage("План отправлен на доработку."),
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
            "todos_editable": not bool(todos),
            "messages": [
                _tool_message(
                    runtime,
                    "План подтверждён.",
                    planning=snapshot,
                )
            ],
        }
    )
