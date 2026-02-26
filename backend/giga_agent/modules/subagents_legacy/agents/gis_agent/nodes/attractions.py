import random

from langchain_core.runnables import RunnableConfig

from giga_agent.modules.subagents_legacy.agents.gis_agent.config import MapState
from giga_agent.modules.subagents_legacy.agents.gis_agent.utils.gis_client import (
    fetch_attractions,
    fetch_city_cords,
)


async def attractions_node(state: MapState, config: RunnableConfig):
    cords = await fetch_city_cords(state["city_name"], config)
    attractions = await fetch_attractions(cords, config)
    try:
        attractions = random.sample(attractions, 3)
    except ValueError:
        pass
    return {"city_point": cords, "attractions": attractions}
