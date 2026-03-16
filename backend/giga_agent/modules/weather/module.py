from __future__ import annotations

from typing import Any, List

from langchain_core.tools import BaseTool

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.module import BaseModule, SecretMetadata
from giga_agent.models.users import UserShort
from giga_agent.modules.weather.tools import weather, WEATHER_SECRET_KEY


def _has_secret(user: UserShort | None, key: str) -> bool:
    if user is None:
        return False
    raw = getattr(user, "secrets", None)
    if not isinstance(raw, dict):
        return False
    value = raw.get(key)
    if value is None:
        return False
    return bool(str(value).strip())


class WeatherModule(BaseModule):
    id: str = "weather"

    def get_secrets(self, **kwargs: Any) -> list[SecretMetadata]:
        _ = kwargs
        return [
            {
                "name": WEATHER_SECRET_KEY,
                "description": "API key OpenWeatherMap для текущей и прогнозной погоды.",
                "type": "pass",
            }
        ]

    async def get_tools(
        self, user: UserShort | None, agent: BaseAgent
    ) -> List[BaseTool]:
        _ = agent
        if not _has_secret(user, WEATHER_SECRET_KEY):
            return []
        return [weather]
