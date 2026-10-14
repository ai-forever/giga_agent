"""E2E plan approval и последующего прогресса через write_todo."""

import asyncio
import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from giga_agent.core.agent.types import AgentState
from giga_agent.modules.planning.tools import present_plan, update_plan, write_todo

PLAN_CONTENT = "# Цель\n\nСделать результат.\n\n## Проверка\n\nПроверить итог."


def _route(state: AgentState):
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def _model(state: AgentState):
    if state.get("mode") == "plan" and not state.get("plan_content"):
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "update",
                            "name": "update_plan",
                            "args": {
                                "find_string": "",
                                "replace_string": PLAN_CONTENT,
                                "todos": [
                                    {"content": "Шаг 1"},
                                    {"content": "Шаг 2"},
                                ],
                            },
                        }
                    ],
                )
            ]
        }
    if state.get("mode") == "plan":
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "present", "name": "present_plan", "args": {}}],
                )
            ]
        }
    if state.get("plan_approved") and state["todos"][0]["status"] == "pending":
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "progress",
                            "name": "write_todo",
                            "args": {
                                "merge": True,
                                "todos": [
                                    {
                                        "id": "1",
                                        "status": "completed",
                                        "note": "готово",
                                    }
                                ],
                            },
                        }
                    ],
                )
            ]
        }
    return {"messages": [AIMessage(content="исполнение продолжается")]}


def _build():
    graph = StateGraph(AgentState)
    graph.add_node("model", _model)
    graph.add_node("tools", ToolNode([write_todo, update_plan, present_plan]))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", _route, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=InMemorySaver())


class PlanningE2ETests(unittest.TestCase):
    def test_interrupt_payload_and_approved_progress(self):
        app = _build()
        config = {"configurable": {"thread_id": "plan-e2e"}}
        initial = {
            "messages": [HumanMessage("сделай")],
            "mode": "plan",
            "plan_content": "",
            "todos": [],
            "todo_id_seq": 0,
            "plan_approved": False,
        }
        paused = asyncio.run(app.ainvoke(initial, config))
        payload = paused["__interrupt__"][0].value
        self.assertEqual(payload["type"], "plan_approval")
        self.assertEqual(payload["plan_content"], PLAN_CONTENT)
        self.assertEqual([todo["id"] for todo in payload["todos"]], ["1", "2"])

        result = asyncio.run(app.ainvoke(Command(resume={"action": "approve"}), config))
        self.assertEqual(result["mode"], "normal")
        self.assertTrue(result["plan_approved"])
        self.assertEqual(result["todos"][0]["status"], "completed")
        self.assertEqual(result["todos"][0]["note"], "готово")
        self.assertEqual(result["messages"][-1].content, "исполнение продолжается")


if __name__ == "__main__":
    unittest.main()
