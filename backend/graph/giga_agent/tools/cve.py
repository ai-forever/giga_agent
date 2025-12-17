from typing import Any

import httpx
from langchain_core.tools import tool


@tool(parse_docstring=True)
async def get_cve_for_package(
    package_name: str,
    package_version: str,
) -> dict[str, Any]:
    """Получает cve для пакета и его версии по OSV.dev API (Google OSV)

    Args:
        package_name: Название пакета
        package_version: Версия пакета

    """
    url = "https://api.osv.dev/v1/query"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"version": package_version, "package": {"name": package_name}},
        )
        response.raise_for_status()
        return response.json()
