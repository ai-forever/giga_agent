from __future__ import annotations

import uuid
from typing import Any, Literal

import httpx
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort

GITHUB_SECRET_KEY = "GITHUB_PERSONAL_ACCESS_TOKEN"


def remove_url_keys(obj: Any) -> Any:
    """Recursively remove keys containing '_url' from dictionaries if their value is not a dict."""
    if isinstance(obj, dict):
        result: dict[Any, Any] = {}
        for key, value in obj.items():
            if "_url" in key and not isinstance(value, dict):
                continue
            result[key] = remove_url_keys(value)
        return result
    if isinstance(obj, list):
        return [remove_url_keys(item) for item in obj]
    return obj


def _get_user_secret(user: UserShort, key: str) -> str | None:
    raw = getattr(user, "secrets", None)
    secrets = raw if isinstance(raw, dict) else {}
    value = secrets.get(key)
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


async def _get_current_user(runtime: ToolRuntime) -> UserShort:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {owner_id} не найден")
    return user


async def _get_github_token(runtime: ToolRuntime) -> str:
    user = await _get_current_user(runtime)
    token = _get_user_secret(user, GITHUB_SECRET_KEY)
    if token is None:
        raise ValueError(f"Missing required user secret: {GITHUB_SECRET_KEY}")
    return token


@tool(parse_docstring=True)
async def get_workflow_runs(
    owner: str,
    repo: str,
    runtime: ToolRuntime,
    actor: str | None = None,
    branch: str | None = None,
    event: str | None = None,
    status: (
        Literal[
            "completed",
            "action_required",
            "cancelled",
            "failure",
            "neutral",
            "skipped",
            "stale",
            "success",
            "timed_out",
            "in_progress",
            "queued",
            "requested",
            "waiting",
            "pending",
        ]
        | None
    ) = None,
    per_page: int = 30,
    page: int = 1,
    created: str | None = None,
    exclude_pull_requests: bool = False,
) -> dict[str, Any]:
    """Получает CI Runs из GitHub репозитория

    Args:
        owner: Repository owner (case-insensitive).
        repo: Repository name without .git extension (case-insensitive).
        actor: Filter by the user who triggered the run.
        branch: Filter by branch name.
        event: Filter by event (e.g., push, pull_request).
        status: Filter by run status or conclusion.
        per_page: Results per page (max 100). If you need to get more call this method in loop
        page: Page number to fetch.
        created: Date-time range filter (see GitHub search syntax).
        exclude_pull_requests: If True, omit pull request runs.
    """
    if per_page > 100:
        raise ValueError("Maximum per_page value is 100")
    token = await _get_github_token(runtime)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params: dict[str, str | int | bool] = {
        "per_page": per_page,
        "page": page,
        "exclude_pull_requests": str(exclude_pull_requests).lower(),
    }
    if actor:
        params["actor"] = actor
    if branch:
        params["branch"] = branch
    if event:
        params["event"] = event
    if status:
        params["status"] = status
    if created:
        params["created"] = created

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return remove_url_keys(response.json())


@tool(parse_docstring=True)
async def list_pull_requests(
    owner: str,
    repo: str,
    runtime: ToolRuntime,
    state: Literal["open", "closed", "all"] | None = "open",
    head: str | None = None,
    base: str | None = None,
    sort: Literal["created", "updated", "popularity", "long-running"] | None = None,
    direction: Literal["asc", "desc"] | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """Список Pull Requests репозитория

    Args:
        owner: Владелец репозитория (без .git)
        repo: Имя репозитория (без .git)
        state: Статус PR: open|closed|all (по умолчанию open)
        head: Фильтр по head ("user:branch")
        base: Фильтр по base ветке
        sort: Порядок сортировки: created|updated|popularity|long-running
        direction: Направление сортировки: asc|desc
        per_page: Результатов на страницу (макс 100)
        page: Номер страницы
    """
    if per_page > 100:
        raise ValueError("Maximum per_page value is 100")
    token = await _get_github_token(runtime)
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params: dict[str, Any] = {"per_page": per_page, "page": page}
    if state:
        params["state"] = state
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    if sort:
        params["sort"] = sort
    if direction:
        params["direction"] = direction

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return remove_url_keys(response.json())


@tool(parse_docstring=True)
async def get_pull_request(
    owner: str,
    repo: str,
    pull_number: int,
    runtime: ToolRuntime,
) -> dict[str, Any]:
    """Получает Pull Request по номеру

    Args:
        owner: Владелец репозитория (без .git)
        repo: Имя репозитория (без .git)
        pull_number: Номер PR
    """
    token = await _get_github_token(runtime)
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return remove_url_keys(response.json())
