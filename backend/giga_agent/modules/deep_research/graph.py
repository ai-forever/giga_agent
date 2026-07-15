"""Deep research — StateGraph + tool-обёртка `run_deep_research`."""

from __future__ import annotations

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.models.file import FileResponse
from giga_agent.modules.deep_research.config import (
    ConfigSchema,
    DeepResearchState,
    default_budget,
)
from giga_agent.modules.deep_research.nodes.compose import compose_node
from giga_agent.modules.deep_research.nodes.critique import (
    critique_node,
    route_after_critique,
)
from giga_agent.modules.deep_research.nodes.finalize import finalize_node
from giga_agent.modules.deep_research.nodes.planner import planner_node
from giga_agent.modules.deep_research.nodes.read import read_node
from giga_agent.modules.deep_research.nodes.reflect import (
    reflect_node,
    route_after_reflect,
)
from giga_agent.modules.deep_research.nodes.search import search_node
from giga_agent.modules.subagents_legacy.uploads import build_tool_message
from giga_agent.utils.langgraph_sdk import client_session


workflow = StateGraph(DeepResearchState, ConfigSchema)

workflow.add_node("planner", planner_node)
workflow.add_node("search", search_node)
workflow.add_node("read", read_node)
workflow.add_node("reflect", reflect_node)
workflow.add_node("compose", compose_node)
workflow.add_node("critique", critique_node)
workflow.add_node("finalize", finalize_node)

workflow.add_edge(START, "planner")
workflow.add_edge("planner", "search")
workflow.add_edge("search", "read")
workflow.add_edge("read", "reflect")
workflow.add_conditional_edges(
    "reflect",
    route_after_reflect,
    {"search": "search", "compose": "compose"},
)
workflow.add_edge("compose", "critique")
workflow.add_conditional_edges(
    "critique",
    route_after_critique,
    {"compose": "compose", "finalize": "finalize"},
)
workflow.add_edge("finalize", END)

graph = workflow.compile()


@tool(parse_docstring=True)
async def run_deep_research(
    research_topic: str,
    max_iterations: int | None = None,
    thread_id: str | None = None,
    runtime: ToolRuntime = None,
):
    """Проводит глубокое исследование: декомпозирует тему на подвопросы, генерирует 3–4 разных поисковых запроса на разных языках для каждого подвопроса, ищет и читает несколько веб-источников, возвращает markdown-отчёт с нумерованными цитатами.

    Используй для сложных вопросов, где нужен сбор и синтез из нескольких источников (обзоры, сравнения, текущее состояние темы). Для простых «найди X» — обычный search.

    Args:
        research_topic: Развёрнутая формулировка ТЕМЫ исследования (не поисковый запрос) с учётом предыдущих сообщений пользователя. Реальные поисковые запросы генерируются внутри инструмента автоматически на нескольких языках.
        max_iterations: Максимум итераций цикла search→read→reflect. По умолчанию 3.
        thread_id: Предыдущий thread_id, если пользователь хочет продолжить исследование.
    """
    budget = default_budget()
    if max_iterations is not None:
        budget["max_iterations"] = int(max_iterations)

    result_state: dict = {}
    async with client_session(runtime.config) as client:
        if not thread_id:
            thread = await client.threads.create()
            thread_id = thread["thread_id"]

        push_ui_message(
            "agent_execution",
            {
                "agent": "run_deep_research",
                "node": "__start__",
                "tool_call_id": runtime.tool_call_id,
            },
        )

        async for chunk in client.runs.stream(
            thread_id=thread_id,
            if_not_exists="create",
            assistant_id="deep_research",
            input={
                "task": research_topic,
                "iteration": 0,
                "budget": budget,
            },
            stream_mode=["values", "updates"],
            on_disconnect="cancel",
        ):
            if chunk.event == "values":
                result_state = chunk.data
            elif chunk.event == "updates":
                for node_name, node_data in chunk.data.items():
                    push_ui_message(
                        "agent_execution",
                        {
                            "agent": "run_deep_research",
                            "node": node_name,
                            "tool_call_id": runtime.tool_call_id,
                            "plan": (node_data or {}).get("plan"),
                            "sources": (node_data or {}).get("sources"),
                            "iteration": (node_data or {}).get("iteration"),
                        },
                    )

    report_raw = result_state.get("report")
    if not report_raw:
        return build_tool_message(
            runtime,
            tool_name="run_deep_research",
            payload={
                "message": "Отчёт не сгенерировался. Попробуйте переформулировать запрос.",
            },
        )

    report = FileResponse.model_validate(report_raw)
    message = (
        f"Готов отчёт по исследованию. Покажи его пользователю через "
        f'"![отчёт](attachment:{report.sandbox_path})"\n'
        f'Текущий thread_id: "{thread_id}" — используй его, если пользователь '
        "захочет продолжить исследование. Ни в коем случае не пиши thread_id пользователю."
    )

    plan_payload = []
    for sub in result_state.get("plan") or []:
        if not isinstance(sub, dict):
            continue
        plan_payload.append(
            {
                "id": sub.get("id"),
                "text": sub.get("text", ""),
                "status": sub.get("status", "pending"),
                "queries": list(sub.get("queries") or []),
            }
        )

    sources_payload = []
    for src in result_state.get("sources") or []:
        if not isinstance(src, dict):
            continue
        summary = (src.get("summary") or "").strip()
        sources_payload.append(
            {
                "id": src.get("id"),
                "url": src.get("url", ""),
                "title": src.get("title", ""),
                "relevant": bool(summary) and not summary.startswith("Нерелевантно"),
            }
        )

    return build_tool_message(
        runtime,
        tool_name="run_deep_research",
        payload={
            "text": result_state.get("done", "Отчёт готов"),
            "message": message,
            "thread_id": thread_id,
            "plan": plan_payload,
            "sources": sources_payload,
        },
        attachments=[report],
    )
