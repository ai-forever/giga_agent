from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.modules.mock_tracker import data


@tool(parse_docstring=True)
async def mock_search_issues(runtime: ToolRuntime, query: str = "") -> dict[str, Any]:
    """Возвращает список задач демо-трекера (фейкового второго провайдера).

    Демонстрирует расширяемость: ответ уже в нормализованном виде
    (widget=issue_board), его рисует тот же фронт-кит, что и Яндекс.Трекер.

    Args:
        query: Поисковая строка (в демо игнорируется).
    """
    _ = runtime, query
    return data.board_payload()


@tool(parse_docstring=True)
async def mock_get_issue(runtime: ToolRuntime, issue_key: str) -> dict[str, Any]:
    """Возвращает одну задачу демо-трекера с описанием.

    Args:
        issue_key: Ключ задачи, например DEMO-1.
    """
    _ = runtime
    return data.single_payload(issue_key)
