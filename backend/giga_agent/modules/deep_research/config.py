from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from giga_agent.models import FileResponse


def merge_sources(existing: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Custom reducer: merge sources by id — обновляет поля существующих и добавляет новых."""
    existing = existing or []
    new = new or []
    by_id: dict = {}
    order: list = []
    for src in existing + new:
        if not isinstance(src, dict):
            continue
        sid = src.get("id")
        if sid is None:
            continue
        if sid in by_id:
            # Обновляем только непустыми значениями, чтобы не затирать старое пустым.
            for k, v in src.items():
                if v in (None, "", [], {}):
                    continue
                by_id[sid][k] = v
        else:
            by_id[sid] = dict(src)
            order.append(sid)
    return [by_id[sid] for sid in order]


DEFAULT_MAX_ITERATIONS = 3
DEFAULT_MAX_SUBQUESTIONS = 6
DEFAULT_QUERIES_PER_SUBQ = 4
DEFAULT_SOURCES_PER_SUBQ = 3
DEFAULT_MAX_SOURCES = 40
DEFAULT_MAX_READ_PER_ITERATION = 15
DEFAULT_MAX_REVISIONS = 1


SubQuestionStatus = Literal["pending", "searched", "read", "covered", "gap"]


class Source(TypedDict, total=False):
    id: int
    url: str
    title: str
    snippet: str
    summary: str
    sub_question_ids: list[int]
    score: float


class SubQuestion(TypedDict, total=False):
    id: int
    text: str
    status: SubQuestionStatus
    queries: list[str]


class Finding(TypedDict, total=False):
    sub_question_id: int
    text: str
    source_ids: list[int]


class Budget(TypedDict, total=False):
    max_iterations: int
    max_subquestions: int
    queries_per_subq: int
    sources_per_subq: int
    max_sources: int
    max_read_per_iteration: int
    max_revisions: int


class ConfigSchema(TypedDict, total=False):
    print_messages: bool


def union_strings(
    existing: list[str] | None, new: list[str] | None
) -> list[str]:
    """Reducer: union сохраняя порядок первого появления."""
    existing = existing or []
    new = new or []
    seen: set[str] = set()
    out: list[str] = []
    for s in existing + new:
        if not isinstance(s, str):
            continue
        key = s.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


class DeepResearchState(TypedDict, total=False):
    task: str
    plan: list[SubQuestion]
    sources: Annotated[list[Source], merge_sources]
    findings: Annotated[list[Finding], add]
    searched_queries: Annotated[list[str], union_strings]
    iteration: int
    should_stop: bool
    budget: Budget
    report_draft: str | None
    critique: str | None
    critique_verdict: Literal["accept", "revise"] | None
    revision_count: int
    report: FileResponse | None
    agent_messages: Annotated[list[AnyMessage], add_messages]
    done: str | None


def default_budget() -> Budget:
    return {
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "max_subquestions": DEFAULT_MAX_SUBQUESTIONS,
        "queries_per_subq": DEFAULT_QUERIES_PER_SUBQ,
        "sources_per_subq": DEFAULT_SOURCES_PER_SUBQ,
        "max_sources": DEFAULT_MAX_SOURCES,
        "max_read_per_iteration": DEFAULT_MAX_READ_PER_ITERATION,
        "max_revisions": DEFAULT_MAX_REVISIONS,
    }