from typing import TypedDict

from giga_agent.agents.gis_agent.utils.gis_client import Attraction, Location, Point
from giga_agent.utils.llm import load_llm

llm = load_llm().with_config(tags=["nostream"])


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
