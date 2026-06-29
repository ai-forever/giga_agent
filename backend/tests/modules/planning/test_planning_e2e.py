"""E2E режима планирования: реальный interrupt/resume против чекпойнтера.

Собираем минимальный StateGraph с настоящими тулами (update_plan / present_plan)
через prebuilt ToolNode + InMemorySaver и скриптуем узел модели (без реального LLM).
Это покрывает то, что юниты с замоканным interrupt не могут: что пауза и
возобновление реально работают через чекпойнтер.
"""

import asyncio
import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from giga_agent.core.agent.types import AgentState
from giga_agent.modules.planning.tools import present_plan, update_plan

PLAN = [
    {"id": "1", "title": "шаг 1", "status": "pending"},
    {"id": "2", "title": "шаг 2", "status": "pending"},
]


def _route(state: AgentState):
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def _build(model_fn):
    g = StateGraph(AgentState)
    g.add_node("model", model_fn)
    g.add_node("tools", ToolNode([update_plan, present_plan]))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", _route, {"tools": "tools", END: END})
    g.add_edge("tools", "model")
    return g.compile(checkpointer=InMemorySaver())


def _present_plan_model(state: AgentState):
    """В plan mode предлагает план; в normal — завершает. Ограничен 2 попытками."""
    msgs = state["messages"]
    pp_calls = sum(
        1
        for m in msgs
        if getattr(m, "tool_calls", None)
        and any(tc["name"] == "present_plan" for tc in m.tool_calls)
    )
    if state.get("mode") == "normal":
        return {"messages": [AIMessage(content="исполняю план")]}
    if pp_calls >= 2:
        return {"messages": [AIMessage(content="достаточно планирования")]}
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"pp{pp_calls}",
                        "name": "present_plan",
                        "args": {"todos": PLAN},
                    }
                ],
            )
        ]
    }


class PresentPlanE2ETests(unittest.TestCase):
    def test_interrupts_with_plan_approval_payload(self):
        app = _build(_present_plan_model)
        cfg = {"configurable": {"thread_id": "t-int"}}
        out = asyncio.run(
            app.ainvoke({"messages": [HumanMessage("сделай")], "mode": "plan"}, cfg)
        )
        interrupts = out.get("__interrupt__")
        self.assertTrue(interrupts)
        payload = interrupts[0].value
        self.assertEqual(payload["type"], "plan_approval")
        self.assertEqual(len(payload["plan"]), 2)

    def test_approve_flips_to_normal_and_continues(self):
        app = _build(_present_plan_model)
        cfg = {"configurable": {"thread_id": "t-approve"}}
        asyncio.run(
            app.ainvoke({"messages": [HumanMessage("сделай")], "mode": "plan"}, cfg)
        )
        out = asyncio.run(app.ainvoke(Command(resume={"action": "approve"}), cfg))
        self.assertIsNone(out.get("__interrupt__"))  # паузы больше нет
        self.assertEqual(out.get("mode"), "normal")
        self.assertEqual(len(out.get("plan") or []), 2)
        self.assertEqual(out["messages"][-1].content, "исполняю план")

    def test_edit_applies_edited_plan(self):
        app = _build(_present_plan_model)
        cfg = {"configurable": {"thread_id": "t-edit"}}
        asyncio.run(
            app.ainvoke({"messages": [HumanMessage("сделай")], "mode": "plan"}, cfg)
        )
        edited = [{"id": "1", "title": "ИЗМЕНЁННЫЙ", "status": "pending"}]
        out = asyncio.run(
            app.ainvoke(Command(resume={"action": "edit", "plan": edited}), cfg)
        )
        self.assertEqual(out.get("mode"), "normal")
        self.assertEqual(out["plan"], edited)

    def test_reject_stays_in_plan_and_appends_feedback(self):
        app = _build(_present_plan_model)
        cfg = {"configurable": {"thread_id": "t-reject"}}
        asyncio.run(
            app.ainvoke({"messages": [HumanMessage("сделай")], "mode": "plan"}, cfg)
        )
        out = asyncio.run(
            app.ainvoke(
                Command(resume={"action": "reject", "feedback": "сделай иначе"}), cfg
            )
        )
        self.assertNotEqual(out.get("mode"), "normal")  # остаёмся в plan
        contents = [getattr(m, "content", "") for m in out["messages"]]
        self.assertIn("сделай иначе", contents)  # фидбек попал в историю
        self.assertTrue(out.get("__interrupt__"))  # агент перепланировал → новая пауза


def _update_plan_model(state: AgentState):
    """Один раз обновляет план, потом завершает."""
    if state.get("plan"):
        return {"messages": [AIMessage(content="план зафиксирован")]}
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "up0", "name": "update_plan", "args": {"todos": PLAN}}
                ],
            )
        ]
    }


class UpdatePlanE2ETests(unittest.TestCase):
    def test_update_plan_writes_to_state(self):
        app = _build(_update_plan_model)
        cfg = {"configurable": {"thread_id": "t-update"}}
        out = asyncio.run(
            app.ainvoke({"messages": [HumanMessage("сделай")], "mode": "normal"}, cfg)
        )
        self.assertIsNone(out.get("__interrupt__"))
        self.assertEqual(len(out.get("plan") or []), 2)
        self.assertEqual(out["messages"][-1].content, "план зафиксирован")


if __name__ == "__main__":
    unittest.main()
