from typing import TypedDict

from giga_agent.modules.subagents_legacy.agents.gis_agent.utils.gis_client import (
    Attraction,
    Location,
    Point,
)


class ConfigSchema(TypedDict):
    fetch_descriptions: bool
    print_messages: bool
    skip_search: bool


class MapState(TypedDict):
    city_name: str
    city_point: Point
    hotels: list[Location]
    food: list[Location]
    attractions: list[Attraction]
