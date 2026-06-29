"""Тесты режима планирования: валидация, тулы, гейтинг, сидирование mode.

E2E на реальный interrupt/resume против checkpointer вынесен отдельно (тяжёлый
харнесс с графом и LLM); здесь interrupt мокается, чтобы покрыть ветки
approve/edit/reject в present_plan без полного графа.
"""

import asyncio
import types
import unittest
from unittest.mock import patch

from giga_agent.core.agent.graph_factory import (
    PLAN_MODE_BLOCKED_MODULES,
    _filter_plan_mode_tools,
)
from giga_agent.modules.planning.middleware import PlanningMiddleware
from giga_agent.modules.planning.tools import (
    TodoItemArg,
    _to_dicts,
    _validate,
    present_plan,
    update_plan,
)


def _todos(*statuses, ids=None):
    ids = ids or [str(i) for i in range(len(statuses))]
    return [TodoItemArg(id=i, title=f"t{i}", status=s) for i, s in zip(ids, statuses)]


def _runtime(call_id="call_1"):
    return types.SimpleNamespace(tool_call_id=call_id)


class ValidationTests(unittest.TestCase):
    def test_single_in_progress_ok(self):
        self.assertIsNone(_validate(_todos("in_progress", "pending")))

    def test_empty_ok(self):
        self.assertIsNone(_validate([]))

    def test_two_in_progress_rejected(self):
        err = _validate(_todos("in_progress", "in_progress"))
        self.assertIsNotNone(err)
        self.assertIn("in_progress", err)

    def test_duplicate_ids_rejected(self):
        err = _validate(_todos("pending", "pending", ids=["1", "1"]))
        self.assertIsNotNone(err)

    def test_to_dicts_keeps_note_drops_empty(self):
        items = [
            TodoItemArg(id="1", title="a", status="skipped", note="reason"),
            TodoItemArg(id="2", title="b", status="pending"),
        ]
        self.assertEqual(
            _to_dicts(items),
            [
                {"id": "1", "title": "a", "status": "skipped", "note": "reason"},
                {"id": "2", "title": "b", "status": "pending"},
            ],
        )


class UpdatePlanTests(unittest.TestCase):
    def test_valid_plan_sets_state_and_tool_message(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                todos=_todos("in_progress", "pending"), runtime=_runtime("c1")
            )
        )
        self.assertEqual(len(cmd.update["plan"]), 2)
        msg = cmd.update["messages"][0]
        self.assertEqual(msg.tool_call_id, "c1")

    def test_empty_plan_clears(self):
        cmd = asyncio.run(update_plan.coroutine(todos=[], runtime=_runtime()))
        self.assertEqual(cmd.update["plan"], [])

    def test_invalid_plan_does_not_touch_state(self):
        cmd = asyncio.run(
            update_plan.coroutine(
                todos=_todos("in_progress", "in_progress"), runtime=_runtime()
            )
        )
        self.assertNotIn("plan", cmd.update)
        self.assertIn("не обновлён", cmd.update["messages"][0].content)


class PresentPlanTests(unittest.TestCase):
    def test_approve_switches_to_normal(self):
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "approve"},
        ):
            cmd = asyncio.run(
                present_plan.coroutine(
                    todos=_todos("pending", "pending"), runtime=_runtime()
                )
            )
        self.assertEqual(cmd.update["mode"], "normal")
        self.assertEqual(len(cmd.update["plan"]), 2)

    def test_edit_uses_edited_plan(self):
        edited = [{"id": "9", "title": "edited", "status": "pending"}]
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "edit", "plan": edited},
        ):
            cmd = asyncio.run(
                present_plan.coroutine(todos=_todos("pending"), runtime=_runtime())
            )
        self.assertEqual(cmd.update["mode"], "normal")
        self.assertEqual(cmd.update["plan"], edited)

    def test_reject_stays_in_plan_and_appends_feedback(self):
        with patch(
            "giga_agent.modules.planning.tools.interrupt",
            return_value={"action": "reject", "feedback": "сделай иначе"},
        ):
            cmd = asyncio.run(
                present_plan.coroutine(todos=_todos("pending"), runtime=_runtime())
            )
        self.assertNotIn("mode", cmd.update)  # остаёмся в plan mode
        types_in_msgs = [m.type for m in cmd.update["messages"]]
        self.assertIn("human", types_in_msgs)  # фидбек как user-сообщение


class GatingTests(unittest.TestCase):
    class _Tool:
        def __init__(self, name, module_id=None):
            self.name = name
            self.extras = {"module_id": module_id} if module_id else None

    def _tools(self):
        return [
            {"type": "web_search"},  # built-in dict, без extras
            self._Tool("update_plan"),  # planning, без module_id
            self._Tool("present_plan"),
            self._Tool("python", "repl"),
            self._Tool("upload_file", "io"),
            self._Tool("post_to_vk", "vk"),
            self._Tool("web_search_tool", "search"),
            self._Tool("rag_search", "rag"),
        ]

    def _names(self, tools):
        return [t.name if hasattr(t, "name") else t.get("type") for t in tools]

    def test_plan_mode_drops_side_effects_keeps_rest(self):
        kept = self._names(_filter_plan_mode_tools(self._tools(), "plan"))
        for blocked in ("python", "upload_file", "post_to_vk"):
            self.assertNotIn(blocked, kept)
        for keep in (
            "update_plan",
            "present_plan",
            "web_search_tool",
            "rag_search",
            "web_search",
        ):
            self.assertIn(keep, kept)

    def test_normal_mode_keeps_everything(self):
        tools = self._tools()
        self.assertEqual(len(_filter_plan_mode_tools(tools, "normal")), len(tools))
        self.assertEqual(len(_filter_plan_mode_tools(tools, None)), len(tools))

    def test_blocked_set_is_side_effecting_modules(self):
        self.assertEqual(
            PLAN_MODE_BLOCKED_MODULES,
            frozenset(
                {"repl", "io", "image", "github", "vk", "skills", "subagents_legacy"}
            ),
        )


class MiddlewareSeedTests(unittest.TestCase):
    def _seed(self, config):
        mw = PlanningMiddleware()
        return asyncio.run(mw.before_agent({}, None, config))

    def test_toggle_on_seeds_plan(self):
        self.assertEqual(
            self._seed({"configurable": {"plan_mode": True}}), {"mode": "plan"}
        )

    def test_toggle_off_seeds_normal(self):
        self.assertEqual(self._seed({"configurable": {}}), {"mode": "normal"})
        self.assertEqual(self._seed({}), {"mode": "normal"})


if __name__ == "__main__":
    unittest.main()
