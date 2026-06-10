"""In-memory фейковые данные демо-трекера + нормализованный контракт.

Цель — доказать расширяемость: новый провайдер приводит свои данные к
нормализованному виду `{widget:"issue_board", provider, issues:[Issue]}`, и
фронт-кит рендерит их БЕЗ единой правки. Здесь нет внешнего API — только память.
"""

from __future__ import annotations

from typing import Any

PROVIDER = "mock_tracker"

# Стартовый статус каждой задачи (мутируется переходами в рамках процесса).
_STATUS: dict[str, str] = {
    "DEMO-1": "Открыт",
    "DEMO-2": "В работе",
    "DEMO-3": "Открыт",
}

_ISSUES: dict[str, dict[str, Any]] = {
    "DEMO-1": {
        "key": "DEMO-1",
        "title": "Подключить Jira как провайдер",
        "assignee": "Алиса",
        "priority": "Высокий",
        "project": "DEMO",
        "description": "Демонстрация: тот же кит рисует чужой трекер. Этот текст "
        "длиннее ста шестидесяти символов нарочно, чтобы проверить сворачивание "
        "описания в карточке — кнопка «Показать описание» должна появиться.",
    },
    "DEMO-2": {
        "key": "DEMO-2",
        "title": "Нормализовать контракт Issue",
        "assignee": "Боб",
        "priority": "Средний",
        "project": "DEMO",
        "description": "Короткое описание без сворачивания.",
    },
    "DEMO-3": {
        "key": "DEMO-3",
        "title": "Проверить смену статуса из карточки",
        "assignee": "Алиса",
        "priority": "Низкий",
        "project": "DEMO",
    },
}

# Доступные переходы по текущему статусу (display → целевой статус).
_TRANSITIONS: dict[str, list[dict[str, str]]] = {
    "Открыт": [
        {"id": "start", "display": "В работу", "to": "В работе"},
        {"id": "close", "display": "Закрыть", "to": "Закрыт"},
    ],
    "В работе": [
        {"id": "resolve", "display": "Завершить", "to": "Закрыт"},
        {"id": "stop", "display": "Вернуть в открытые", "to": "Открыт"},
    ],
    "Закрыт": [
        {"id": "reopen", "display": "Переоткрыть", "to": "Открыт"},
    ],
}


def _to_issue(key: str, *, with_description: bool = False) -> dict[str, Any]:
    """Нормализованный Issue под фронт-контракт (provider, fields, tag…)."""
    raw = _ISSUES[key]
    fields = [
        {"icon": "user", "label": "Исполнитель", "value": raw["assignee"]},
        {"icon": "flag", "label": "Приоритет", "value": raw["priority"]},
    ]
    issue: dict[str, Any] = {
        "id": key,
        "key": key,
        "title": raw["title"],
        "status": _STATUS[key],
        "provider": PROVIDER,
        "tag": raw.get("project"),
        "fields": fields,
    }
    if with_description and raw.get("description"):
        issue["description"] = raw["description"]
    return issue


def board_payload(with_description: bool = False) -> dict[str, Any]:
    """Полный нормализованный payload доски — то, что рендерит кит."""
    return {
        "widget": "issue_board",
        "provider": PROVIDER,
        "issues": [_to_issue(k, with_description=with_description) for k in _ISSUES],
    }


def single_payload(key: str) -> dict[str, Any]:
    if key not in _ISSUES:
        return {"widget": "issue_board", "provider": PROVIDER, "issues": []}
    return {
        "widget": "issue_board",
        "provider": PROVIDER,
        "issues": [_to_issue(key, with_description=True)],
    }


def get_issue(key: str) -> dict[str, Any] | None:
    """Нормализованный Issue по ключу (для REST-refresh виджета)."""
    if key not in _ISSUES:
        return None
    return _to_issue(key, with_description=True)


_ACCENTS = {"В работе": "info", "Закрыт": "success"}


def grouped(group_by: str) -> list[dict[str, Any]]:
    """Группы для генеративной доски: по статусу/исполнителю/приоритету."""
    field_map = {
        "status": lambda k: _STATUS[k],
        "assignee": lambda k: _ISSUES[k]["assignee"],
        "priority": lambda k: _ISSUES[k]["priority"],
    }
    pick = field_map.get(group_by, field_map["status"])
    buckets: dict[str, list[str]] = {}
    for key in _ISSUES:
        buckets.setdefault(pick(key), []).append(key)
    groups: list[dict[str, Any]] = []
    for label, keys in buckets.items():
        g: dict[str, Any] = {"label": label, "issues": [_to_issue(k) for k in keys]}
        if group_by == "status" and label in _ACCENTS:
            g["accent"] = _ACCENTS[label]
        groups.append(g)
    groups.sort(key=lambda x: len(x["issues"]), reverse=True)
    return groups


def transitions_for(key: str) -> list[dict[str, str]]:
    if key not in _STATUS:
        return []
    return _TRANSITIONS.get(_STATUS[key], [])


def apply_transition(key: str, transition_id: str) -> dict[str, Any] | None:
    """Меняет статус по переходу, возвращает свежий Issue (или None)."""
    if key not in _STATUS:
        return None
    for t in _TRANSITIONS.get(_STATUS[key], []):
        if t["id"] == transition_id:
            _STATUS[key] = t["to"]
            return _to_issue(key, with_description=True)
    return None
