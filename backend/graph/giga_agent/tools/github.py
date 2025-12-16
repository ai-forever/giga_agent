from typing import Any, Literal

import httpx
from langchain_core.tools import tool

from giga_agent.settings import settings


@tool(parse_docstring=True)
async def get_workflow_runs(
    owner: str,
    repo: str,
    actor: str | None = None,
    branch: str | None = None,
    event: str | None = None,
    status: Literal[
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
    | None = None,
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
        status: Filter by run status or conclusion. Can be one of: completed, action_required, cancelled, failure, neutral, skipped, stale, success, timed_out, in_progress, queued, requested, waiting, pending.
        per_page: Results per page (max 100). If you need to get more call this method in loop
        page: Page number to fetch.
        created: Date-time range filter (see GitHub search syntax).
        exclude_pull_requests: If True, omit pull request runs.

    """
    if per_page > 100:
        raise Exception("Maximum per_page value is 100")
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.external.github_personal_access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    params: dict[str, str | int | bool] = {
        "per_page": per_page,
        "page": page,
        "exclude_pull_requests": str(exclude_pull_requests).lower(),
    }

    # Optional filters
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
        raise Exception("Maximum per_page value is 100")
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.external.github_personal_access_token}",
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
) -> dict[str, Any]:
    """Получает Pull Request по номеру

    Args:
        owner: Владелец репозитория (без .git)
        repo: Имя репозитория (без .git)
        pull_number: Номер PR

    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.external.github_personal_access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return remove_url_keys(response.json())


def remove_url_keys(obj: Any) -> Any:
    """Recursively remove keys containing '_url' from dictionaries if their value is not a dict.

    Parameters
    ----------
        obj: The input data, which can be a dict, list, or any other type.

    Returns
    -------
        A new data structure with keys matching the criteria removed.

    """
    if isinstance(obj, dict):
        result: dict[Any, Any] = {}
        for key, value in obj.items():
            # Skip keys containing '_url' when value is not a dict
            if "_url" in key and not isinstance(value, dict):
                continue
            result[key] = remove_url_keys(value)
        return result
    if isinstance(obj, list):
        return [remove_url_keys(item) for item in obj]
    return obj
