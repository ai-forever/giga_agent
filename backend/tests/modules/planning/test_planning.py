"""Unit-тесты подробного plan-mode и рабочего todo-листа."""

import asyncio
import types
import unittest
from unittest.mock import patch

from langchain_core.tools import tool

from giga_agent.core.agent.graph_factory import _filter_plan_mode_tools
from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    annotate_known_provider_tool,
    tool_extras,
)
from giga_agent.modules.planning.middleware import PlanningMiddleware
from giga_agent.modules.planning.module import PlanningModule
from giga_agent.modules.planning.tools import (
    TodoPatchArg,
    present_plan,
    update_plan,
    write_todo,
)


def _runtime(state=None, call_id="call_1"):
    return types.SimpleNamespace(tool_call_id=call_id, state=state or {})


def _todo(todo_id, content, status="pending", note=None):
    item = {"id": todo_id, "content": content, "status": status}
    if note is not None:
        item["note"] = note
    return item


class WriteTodoTests(unittest.TestCase):
    def test_replace_assigns_numeric_ids(self):
        cmd = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[
                    TodoPatchArg(content="Собрать данные"),
                    TodoPatchArg(content="Подготовить результат"),
                ],
                runtime=_runtime({"mode": "normal"}),
            )
        )
        self.assertEqual([todo["id"] for todo in cmd.update["todos"]], ["1", "2"])
        self.assertEqual(cmd.update["todo_id_seq"], 2)
        planning = cmd.update["messages"][0].additional_kwargs["planning"]
        self.assertEqual(planning["type"], "todo_snapshot")
        self.assertEqual(planning["assigned_ids"], ["1", "2"])

    def test_merge_accepts_partial_patch_and_parallel_progress(self):
        state = {
            "mode": "normal",
            "todos": [_todo("1", "A"), _todo("2", "B")],
            "todo_id_seq": 2,
        }
        cmd = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[
                    TodoPatchArg(id="1", status="in_progress"),
                    TodoPatchArg(id="2", status="in_progress"),
                ],
                runtime=_runtime(state),
            )
        )
        self.assertEqual(
            [todo["status"] for todo in cmd.update["todos"]],
            ["in_progress", "in_progress"],
        )

    def test_unknown_id_without_content_is_error_and_does_not_update_state(self):
        cmd = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[TodoPatchArg(id="99", status="completed")],
                runtime=_runtime(
                    {
                        "mode": "normal",
                        "todos": [_todo("1", "A")],
                        "todo_id_seq": 1,
                    }
                ),
            )
        )
        self.assertNotIn("todos", cmd.update)
        self.assertEqual(cmd.update["messages"][0].status, "error")
        self.assertEqual(
            cmd.update["messages"][0].additional_kwargs["planning"],
            {"type": "todo_error", "todos": [_todo("1", "A")]},
        )

    def test_creation_accepts_explicit_id(self):
        replaced = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[
                    TodoPatchArg(id="analysis", content="Собрать данные"),
                    TodoPatchArg(id="42", content="Подготовить результат"),
                ],
                runtime=_runtime({"mode": "normal"}),
            )
        )
        self.assertEqual(
            [todo["id"] for todo in replaced.update["todos"]], ["analysis", "42"]
        )
        self.assertEqual(replaced.update["todo_id_seq"], 42)

        created = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[TodoPatchArg(id="verify", content="Проверить результат")],
                runtime=_runtime(
                    {
                        "mode": "normal",
                        "todos": replaced.update["todos"],
                        "todo_id_seq": replaced.update["todo_id_seq"],
                    }
                ),
            )
        )
        self.assertEqual(created.update["todos"][-1]["id"], "verify")

    def test_locked_plan_allows_content_status_and_note(self):
        state = {
            "mode": "normal",
            "plan_approved": True,
            "todos": [_todo("1", "A"), _todo("2", "B")],
            "todo_id_seq": 2,
        }
        ok = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[
                    TodoPatchArg(id="1", status="completed", note="готово"),
                ],
                runtime=_runtime(state),
            )
        )
        self.assertEqual(ok.update["todos"][0]["note"], "готово")

        content_changed = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[TodoPatchArg(id="1", content="другая формулировка")],
                runtime=_runtime(state),
            )
        )
        self.assertEqual(
            content_changed.update["todos"][0]["content"],
            "другая формулировка",
        )

        new_item = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[TodoPatchArg(content="Новый пункт")],
                runtime=_runtime(state),
            )
        )
        self.assertNotIn("todos", new_item.update)
        self.assertEqual(new_item.update["messages"][0].status, "error")

    def test_empty_approved_plan_allows_future_todo_edits(self):
        initial_state = {
            "mode": "normal",
            "plan_approved": True,
            "todos_editable": True,
            "todos": [],
            "todo_id_seq": 0,
        }
        created = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[TodoPatchArg(content="A"), TodoPatchArg(content="B")],
                runtime=_runtime(initial_state),
            )
        )
        self.assertTrue(created.update["todos_editable"])

        changed = asyncio.run(
            write_todo.coroutine(
                merge=True,
                todos=[TodoPatchArg(id="1", content="Обновлённый A")],
                runtime=_runtime(
                    {
                        **initial_state,
                        "todos": created.update["todos"],
                        "todo_id_seq": created.update["todo_id_seq"],
                    }
                ),
            )
        )
        self.assertEqual(changed.update["todos"][0]["content"], "Обновлённый A")

    def test_empty_and_single_replacement_are_invalid(self):
        empty = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[],
                runtime=_runtime({"mode": "normal"}),
            )
        )
        single = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[TodoPatchArg(content="Один")],
                runtime=_runtime({"mode": "normal"}),
            )
        )
        self.assertEqual(empty.update["messages"][0].status, "error")
        self.assertEqual(single.update["messages"][0].status, "error")

    def test_replacement_accepts_explicit_null_id(self):
        result = asyncio.run(
            write_todo.coroutine(
                merge=False,
                todos=[
                    TodoPatchArg.model_validate({"id": None, "content": "Первый"}),
                    TodoPatchArg(content="Второй"),
                ],
                runtime=_runtime({"mode": "normal"}),
            )
        )
        self.assertEqual([todo["id"] for todo in result.update["todos"]], ["1", "2"])


class UpdatePlanTests(unittest.TestCase):
    def test_initializes_markdown_and_todos_atomically(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                replace_string="# Цель\n\nСделать результат",
                todos=[
                    TodoPatchArg(content="Шаг A"),
                    TodoPatchArg(content="Шаг B"),
                ],
                runtime=_runtime({"mode": "plan"}),
            )
        )
        self.assertEqual(cmd.update["plan_content"], "# Цель\n\nСделать результат")
        self.assertEqual([todo["id"] for todo in cmd.update["todos"]], ["1", "2"])
        self.assertEqual(cmd.update["todo_id_seq"], 2)
        result = cmd.update["messages"][0].content
        self.assertIn("Режим планирования остаётся активным", result)
        self.assertIn("вызови present_plan без аргументов", result)

    def test_nonempty_plan_requires_find_string(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                replace_string="# Новый план",
                runtime=_runtime({"mode": "plan", "plan_content": "# Старый план"}),
            )
        )

        self.assertEqual(cmd.update["messages"][0].status, "error")
        self.assertIn("find_string обязателен", cmd.update["messages"][0].content)

    def test_exact_replace_remove_and_create_preserve_sequence(self):
        state = {
            "mode": "plan",
            "plan_content": "# Старый план",
            "todos": [_todo("1", "A"), _todo("2", "B"), _todo("3", "C")],
            "todo_id_seq": 3,
        }
        cmd = asyncio.run(
            update_plan.coroutine(
                find_string="Старый",
                replace_string="Новый",
                todos=[TodoPatchArg(content="D")],
                remove_todo_ids=["3"],
                runtime=_runtime(state),
            )
        )
        self.assertEqual(cmd.update["plan_content"], "# Новый план")
        self.assertEqual(
            [todo["id"] for todo in cmd.update["todos"]],
            ["1", "2", "4"],
        )
        self.assertEqual(cmd.update["todo_id_seq"], 4)

    def test_mixed_invalid_call_is_atomic(self):
        state = {
            "mode": "plan",
            "plan_content": "# Старый план",
            "todos": [_todo("1", "A"), _todo("2", "B")],
            "todo_id_seq": 2,
        }
        cmd = asyncio.run(
            update_plan.coroutine(
                find_string="Старый",
                replace_string="Новый",
                todos=[TodoPatchArg(id="99", status="completed")],
                runtime=_runtime(state),
            )
        )
        self.assertNotIn("plan_content", cmd.update)
        self.assertNotIn("todos", cmd.update)
        self.assertEqual(cmd.update["messages"][0].status, "error")

    def test_find_string_must_be_unique(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                find_string="шаг",
                replace_string="этап",
                runtime=_runtime(
                    {
                        "mode": "plan",
                        "plan_content": "шаг и ещё шаг",
                        "todos": [],
                    }
                ),
            )
        )
        self.assertNotIn("plan_content", cmd.update)
        self.assertEqual(cmd.update["messages"][0].status, "error")
        self.assertIn("найдено 2", cmd.update["messages"][0].content)

    def test_update_plan_is_rejected_in_normal_mode(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                find_string="",
                replace_string="# План",
                runtime=_runtime({"mode": "normal"}),
            )
        )
        self.assertEqual(cmd.update["messages"][0].status, "error")

    def test_markdown_only_draft_can_be_presented(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                find_string="",
                replace_string="# План",
                runtime=_runtime({"mode": "plan"}),
            )
        )

        result = cmd.update["messages"][0].content
        self.assertIn("вызови present_plan без аргументов", result)


class PresentPlanTests(unittest.TestCase):
    def _state(self):
        return {
            "mode": "plan",
            "plan_content": "# План\n\nПодробности",
            "todos": [_todo("1", "A"), _todo("2", "B")],
            "todo_id_seq": 2,
        }

    def test_approve_switches_to_normal_and_persists_snapshot(self):
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "approve"},
        ):
            cmd = asyncio.run(present_plan.coroutine(runtime=_runtime(self._state())))
        self.assertEqual(cmd.update["mode"], "normal")
        self.assertTrue(cmd.update["plan_approved"])
        self.assertFalse(cmd.update["todos_editable"])
        planning = cmd.update["messages"][0].additional_kwargs["planning"]
        self.assertEqual(planning["type"], "approved_plan")
        self.assertEqual(planning["plan_content"], "# План\n\nПодробности")
        self.assertEqual(
            cmd.update["messages"][0].content,
            "План подтверждён. Теперь тебе доступны все инструменты. "
            "Переходи к выполнению утверждённого плана.",
        )

    def test_approve_allows_plan_without_todos(self):
        state = {"mode": "plan", "plan_content": "# План", "todos": []}
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "approve"},
        ):
            cmd = asyncio.run(present_plan.coroutine(runtime=_runtime(state)))

        self.assertEqual(cmd.update["mode"], "normal")
        self.assertEqual(
            cmd.update["messages"][0].additional_kwargs["planning"]["todos"], []
        )
        self.assertTrue(cmd.update["todos_editable"])

    def test_reject_requires_feedback(self):
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "reject", "feedback": "  "},
        ):
            cmd = asyncio.run(present_plan.coroutine(runtime=_runtime(self._state())))
        self.assertEqual(cmd.update["messages"][0].status, "error")

    def test_reject_appends_feedback_and_stays_in_plan(self):
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "reject", "feedback": "сделай иначе"},
        ):
            cmd = asyncio.run(present_plan.coroutine(runtime=_runtime(self._state())))
        self.assertNotIn("mode", cmd.update)
        self.assertFalse(cmd.update["plan_approved"])
        planning = cmd.update["messages"][0].additional_kwargs["planning"]
        self.assertEqual(planning["type"], "rejected_plan")
        self.assertEqual(planning["plan_content"], "# План\n\nПодробности")
        self.assertEqual(len(planning["todos"]), 2)
        self.assertIn(
            "План отправлен на доработку.",
            [message.content for message in cmd.update["messages"]],
        )
        self.assertIn("human", [message.type for message in cmd.update["messages"]])

    def test_requires_nonempty_content_and_validates_present_todos(self):
        invalid_states = [
            {"mode": "plan", "plan_content": "", "todos": []},
            {
                "mode": "plan",
                "plan_content": "# План",
                "todos": [_todo("1", "A", "completed")],
            },
            {
                "mode": "plan",
                "plan_content": "# План",
                "todos": [_todo("1", "A", "completed"), _todo("2", "B")],
            },
        ]
        for state in invalid_states:
            with self.subTest(state=state):
                cmd = asyncio.run(present_plan.coroutine(runtime=_runtime(state)))
                self.assertEqual(cmd.update["messages"][0].status, "error")


class GatingTests(unittest.TestCase):
    @staticmethod
    def _Tool(name, effect=None, *, plan_mode=ToolPlanMode.AUTO):
        def placeholder():
            """Test-only placeholder tool."""
            return None

        extras = tool_extras(effect, plan_mode=plan_mode) if effect else None
        return tool(name, extras=extras)(placeholder)

    def _tools(self):
        return [
            annotate_known_provider_tool({"type": "web_search"}),
            self._Tool(
                "write_todo",
                ToolEffect.WRITE,
                plan_mode=ToolPlanMode.DENY,
            ),
            self._Tool(
                "update_plan",
                ToolEffect.WRITE,
                plan_mode=ToolPlanMode.ALLOW,
            ),
            self._Tool(
                "present_plan",
                ToolEffect.WRITE,
                plan_mode=ToolPlanMode.ALLOW,
            ),
            self._Tool("python", ToolEffect.DESTRUCTIVE, plan_mode=ToolPlanMode.ALLOW),
            self._Tool("shell", ToolEffect.DESTRUCTIVE, plan_mode=ToolPlanMode.ALLOW),
            self._Tool("await_shell", ToolEffect.READ),
            self._Tool("web_search_tool", ToolEffect.READ),
            self._Tool("connector_call_tool", ToolEffect.DELEGATED),
            self._Tool("unknown"),
        ]

    @staticmethod
    def _names(tools):
        return [t.name if hasattr(t, "name") else t.get("type") for t in tools]

    def test_plan_mode_tool_matrix(self):
        with patch(
            "giga_agent.core.agent.graph_factory.get_settings",
            return_value=types.SimpleNamespace(giga_agent_runtime="local"),
        ):
            kept = self._names(_filter_plan_mode_tools(self._tools(), "plan"))
        self.assertNotIn("write_todo", kept)
        self.assertNotIn("python", kept)
        self.assertNotIn("shell", kept)
        self.assertNotIn("unknown", kept)
        for name in (
            "update_plan",
            "present_plan",
            "await_shell",
            "web_search_tool",
            "connector_call_tool",
            "web_search",
        ):
            self.assertIn(name, kept)

    def test_cli_plan_mode_allows_python_and_shell(self):
        with patch(
            "giga_agent.core.agent.graph_factory.get_settings",
            return_value=types.SimpleNamespace(giga_agent_runtime="cli"),
        ):
            kept = self._names(_filter_plan_mode_tools(self._tools(), "plan"))

        self.assertIn("python", kept)
        self.assertIn("shell", kept)
        self.assertIn("await_shell", kept)

    def test_normal_mode_tool_matrix(self):
        for mode in ("normal", None):
            kept = self._names(_filter_plan_mode_tools(self._tools(), mode))
            self.assertIn("write_todo", kept)
            self.assertNotIn("update_plan", kept)
            self.assertNotIn("present_plan", kept)
            self.assertIn("python", kept)
            self.assertIn("shell", kept)


class MiddlewareSeedTests(unittest.TestCase):
    @staticmethod
    def _seed(config):
        middleware = PlanningMiddleware()
        return asyncio.run(middleware.before_agent({}, None, config))

    def test_plan_turn_starts_clean_draft(self):
        self.assertEqual(
            self._seed({"configurable": {"plan_mode": True}}),
            {
                "mode": "plan",
                "plan_content": "",
                "todos": [],
                "todo_id_seq": 0,
                "plan_approved": False,
                "todos_editable": False,
            },
        )

    def test_normal_turn_only_unlocks_plan(self):
        self.assertEqual(
            self._seed({"configurable": {}}),
            {"mode": "normal", "plan_approved": False, "todos_editable": False},
        )

    def test_module_does_not_duplicate_plan_mode_instructions(self):
        module = PlanningModule()

        instructions = asyncio.run(
            module.get_instructions(
                user=None,
                agent=None,
                state={"mode": "plan"},
            )
        )

        self.assertIsNone(instructions)


if __name__ == "__main__":
    unittest.main()
