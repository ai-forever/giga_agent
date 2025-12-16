import aiohttp
from langchain_core.tools import tool

from giga_agent.settings import settings

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _map_units(units: str) -> tuple[str, str]:
    """Преобразует пользовательские единицы измерения из {c|f|k}
    в значения API OpenWeatherMap и возвращает (owm_units, unit_symbol).
    """
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
            ],
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
            ],
        )
    return "\n".join(lines) + ("\n" if lines else "")


@tool(parse_docstring=True)
async def weather(city: str, units: str = "c", lang: str = "en") -> str:
    """Получает текущую погоду и 5‑дневный прогноз по городу через OpenWeatherMap.
    Требуется переменная окружения `OWM_API_KEY`.

    Args:
        city: Город для получения погоды. Если есть пробел, оберни название в кавычки.
        units: Единицы измерения температуры (c - celsius | f - fahrenheit | k - kelvin). По умолчанию: c
        lang: Язык описаний погоды. По умолчанию: en

    """
    api_key = settings.external.owm_api_key
    if not api_key:
        return (
            "Не задан OWM_API_KEY. "
            "Установи переменную окружения OWM_API_KEY со своим ключом OpenWeatherMap."
        )
    owm_units, unit_symbol = _map_units(units)

    params = {"q": city, "appid": api_key, "units": owm_units, "lang": lang}
    async with aiohttp.ClientSession() as session:
        # Current weather
        async with session.get(
            OWM_CURRENT_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            current_json = await resp.json()
            if resp.status != 200:
                message = current_json.get("message") or str(current_json)
                return f"Ошибка получения текущей погоды: {message}"

        # Forecast
        async with session.get(
            OWM_FORECAST_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            forecast_json = await resp.json()
            if resp.status != 200:
                message = forecast_json.get("message") or str(forecast_json)
                return f"Ошибка получения прогноза: {message}"

    parts = [
        _format_current(current_json, unit_symbol),
        _format_forecast(forecast_json, unit_symbol),
    ]
    return "".join(parts)
