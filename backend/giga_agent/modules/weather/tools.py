from __future__ import annotations

import uuid

import aiohttp
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

WEATHER_SECRET_KEY = "OWM_API_KEY"

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _map_units(units: str) -> tuple[str, str]:
    normalized = (units or "c").strip().lower()[:1]
    if normalized == "f":
        return "imperial", "°F"
    if normalized == "k":
        return "standard", "K"
    return "metric", "°C"


def _format_current(data: dict, unit_symbol: str) -> str:
    name = data.get("name", "")
    weather_desc = " ".join([w.get("description", "") for w in data.get("weather", [])])
    main = data.get("main", {})
    wind = data.get("wind", {})
    sys = data.get("sys", {})
    return (
        f"Current weather for {name}:\n"
        f"    Conditions: {weather_desc}\n"
        f"    Now:         {main.get('temp', '')} {unit_symbol}\n"
        f"    High:        {main.get('temp_max', '')} {unit_symbol}\n"
        f"    Low:         {main.get('temp_min', '')} {unit_symbol}\n"
        f"    Pressure:    {main.get('pressure', '')}\n"
        f"    Humidity:    {main.get('humidity', '')}\n"
        f"    FeelsLike:   {main.get('feels_like', '')}\n"
        f"    Wind Speed:  {wind.get('speed', '')}\n"
        f"    Wind Degree: {wind.get('deg', '')}\n"
        f"    Sunrise:     {sys.get('sunrise', '')} Unixtime\n"
        f"    Sunset:      {sys.get('sunset', '')} Unixtime\n"
    )


def _format_forecast(data: dict, unit_symbol: str) -> str:
    city_name = (data.get("city") or {}).get("name", "")
    lines: list[str] = [f"Weather Forecast for {city_name}:"]
    for item in data.get("list", []):
        dt_txt = item.get("dt_txt", "")
        weather_desc = " ".join(
            [
                f"{w.get('main', '')} {w.get('description', '')}"
                for w in item.get("weather", [])
            ]
        ).strip()
        main = item.get("main", {})
        lines.extend(
            [
                f"Date & Time: {dt_txt}",
                f"Conditions:  {weather_desc}",
                f"Temp:        {main.get('temp', '')} {unit_symbol}",
                f"High:        {main.get('temp_max', '')} {unit_symbol}",
                f"Low:         {main.get('temp_min', '')} {unit_symbol}",
                "",
            ]
        )
    return "\n".join(lines) + ("\n" if lines else "")


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
    user_id = get_user_id_from_config(runtime.config)
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository.get_cached_or_db(owner_id, session=session)
    if user is None:
        raise ValueError(f"Пользователь {owner_id} не найден")
    return user


async def _get_owm_api_key(runtime: ToolRuntime | None) -> str:
    user = await _get_current_user(runtime)
    api_key = _get_user_secret(user, WEATHER_SECRET_KEY)
    if api_key is None:
        raise ValueError(f"Missing required user secret: {WEATHER_SECRET_KEY}")
    return api_key


@tool(parse_docstring=True, extras=tool_extras(ToolEffect.READ))
async def weather(
    city: str,
    runtime: ToolRuntime,
    units: str = "c",
    lang: str = "en",
) -> str:
    """Получает текущую погоду и 5‑дневный прогноз по городу через OpenWeatherMap.

    Args:
        city: Город для получения погоды. Если есть пробел, оберни название в кавычки.
        units: Единицы измерения температуры (c|f|k). По умолчанию: c
        lang: Язык описаний погоды. По умолчанию: en
    """
    api_key = await _get_owm_api_key(runtime)
    owm_units, unit_symbol = _map_units(units)
    params = {"q": city, "appid": api_key, "units": owm_units, "lang": lang}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            OWM_CURRENT_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            current_json = await resp.json()
            if resp.status != 200:
                message = current_json.get("message") or str(current_json)
                return f"Ошибка получения текущей погоды: {message}"
        async with session.get(
            OWM_FORECAST_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            forecast_json = await resp.json()
            if resp.status != 200:
                message = forecast_json.get("message") or str(forecast_json)
                return f"Ошибка получения прогноза: {message}"
    return "".join(
        [
            _format_current(current_json, unit_symbol),
            _format_forecast(forecast_json, unit_symbol),
        ]
    )
