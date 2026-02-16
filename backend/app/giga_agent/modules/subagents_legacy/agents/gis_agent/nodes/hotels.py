import asyncio
import random

from langchain_core.runnables import RunnableConfig

from giga_agent.modules.subagents_legacy.agents.gis_agent.config import MapState
from giga_agent.modules.subagents_legacy.agents.gis_agent.utils.gis_client import (
    fetch_branches,
    location_to_description,
)


async def hotels_node(state: MapState, config: RunnableConfig):
    branches = await fetch_branches("отели", state["city_point"])
    try:
        branches = random.sample(branches, 3)
    except ValueError:
        pass
    if not config["configurable"].get("skip_search", False):
        tasks = []
        for branch in branches:
            tasks.append(location_to_description(branch, state["city_name"]))
        results = await asyncio.gather(*tasks)
        for branch, result in zip(branches, results):
            branch["description"] = result
    return {"hotels": branches}
