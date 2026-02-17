import json
import math
import os
import uuid

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import START
from langgraph.graph import StateGraph
from langgraph.graph.ui import push_ui_message

from giga_agent.modules.subagents_legacy.agents.gis_agent.config import MapState
from giga_agent.modules.subagents_legacy.agents.gis_agent.nodes.attractions import (
    attractions_node,
)
from giga_agent.modules.subagents_legacy.agents.gis_agent.nodes.food import food_node
from giga_agent.modules.subagents_legacy.agents.gis_agent.nodes.hotels import (
    hotels_node,
)
from giga_agent.modules.subagents_legacy.agents.gis_agent.utils.gis_client import (
    Attraction,
    Location,
    Point,
)

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

from giga_agent.utils.jupyter import REPLUploader, RunUploadFile

with open(os.path.join(__location__, "page.html")) as f:
    map_html = f.read()


def mercator_lat(rad: float) -> float:
    """Перевод широты в координату Меркатора (в радианах)"""
    return math.log(math.tan(math.pi / 4 + rad / 2))


def get_bounds(points: list[Point]) -> tuple[float, float, float, float]:
    lats = [float(p["lat"]) for p in points]
    lons = [float(p["lon"]) for p in points]
    return min(lats), max(lats), min(lons), max(lons)


def get_center(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> tuple[float, float]:
    """Центр — среднее по каждому измерению"""
    return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2


workflow = StateGraph(MapState)

workflow.add_node("attractions_node", attractions_node)
workflow.add_node("hotels_node", hotels_node)
workflow.add_node("food_node", food_node)

workflow.add_edge(START, "attractions_node")
workflow.add_edge("attractions_node", "hotels_node")
workflow.add_edge("hotels_node", "food_node")
workflow.add_edge("food_node", "__end__")


def get_bbox(points: list[Point]) -> dict:
    # преобразуем строки в числа
    lats = [float(p["lat"]) for p in points]
    lons = [float(p["lon"]) for p in points]

    # минимальная и максимальная широта/долгота
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # в формате [lon, lat]
    southWest = [min_lon, min_lat]
    northEast = [max_lon, max_lat]

    return {"southWest": southWest, "northEast": northEast}


memory = MemorySaver()
graph = workflow.compile(checkpointer=memory)


@tool
async def city_explore(city: str, runtime: ToolRuntime):
    """Получает интересные локации в городе.
    Может быть полезным,
    если пользователь хочет куда-то поехать и просит посоветовать места
    Также используй, когда пользователю нужно распланировать поездку в город

    Args:
        city: Полное название города

    """
    thread_id = str(uuid.uuid4())
    conf = {
        "configurable": {
            "thread_id": thread_id,
            "skip_search": False if settings.external.tavily_api_key else True,
        },
    }
    push_ui_message(
        "agent_execution",
        {
            "agent": "city_explore",
            "node": "__start__",
            "tool_call_id": runtime.tool_call_id,
        },
    )
    input_ = {"city_name": city}
    async for event in graph.astream(
        input_,
        config=conf,
    ):
        push_ui_message(
            "agent_execution",
            {
                "agent": "city_explore",
                "node": list(event.keys())[0],
                "tool_call_id": runtime.tool_call_id,
            },
        )
    state = graph.get_state(config=conf).values
    hotels_message = []
    food_message = []
    attractions_message = []
    markers = []
    points = []
    for hotel in state["hotels"]:
        hotels_message.append(location_to_string(hotel))
        markers.append(
            {
                "coordinates": [hotel["point"]["lon"], hotel["point"]["lat"]],
                "icon": "/public/hotel.svg",
                "userData": {"text": hotel["name"]},
            },
        )
        points.append(hotel["point"])
    for food in state["food"]:
        food_message.append(location_to_string(food))
        markers.append(
            {
                "coordinates": [food["point"]["lon"], food["point"]["lat"]],
                "icon": "/public/food.svg",
                "userData": {"text": food["name"]},
            },
        )
        points.append(food["point"])
    for attraction in state["attractions"]:
        attractions_message.append(attraction_to_string(attraction))
        markers.append(
            {
                "coordinates": [attraction["point"]["lon"], attraction["point"]["lat"]],
                "icon": "/public/bust.svg",
                "userData": {"text": attraction["name"]},
            },
        )
        points.append(attraction["point"])

    min_lat, max_lat, min_lon, max_lon = get_bounds(points)
    center_lat, center_lon = get_center(min_lat, max_lat, min_lon, max_lon)
    markers_data = json.dumps(
        {
            "markers": markers,
            "coords": [center_lon, center_lat],
            "zoom": 8,
            "bounds": get_bbox(points),
            "key": settings.external.twogis_token,
        },
        ensure_ascii=False,
    )
    new_map_html = map_html.replace("<<MARKERS>>", markers_data)

    data_message = (
        "## Достопримечательности\n\n"
        + "\n\n".join(attractions_message)
        + "-------\n## Отели\n\n"
        + "\n\n".join(hotels_message)
        + "-------\n## Где покушать\n\n"
        + "\n\n".join(food_message)
    )

    uploader = REPLUploader()
    upload_files = [
        RunUploadFile(
            path="map.html",
            file_type="html",
            content=new_map_html,
        ),
    ]
    upload_resp = await uploader.upload_run_files(upload_files, thread_id)
    uploaded = upload_resp[0]

    return {
        "data": data_message,
        "message": (
            f"В результате была получена информация о городе и "
            f"страница с картой {uploaded['path']}. Покажи её пользователю через "
            f'"![alt-описание](attachment:{uploaded["path"]})".'
        ),
        "giga_attachments": upload_resp,
    }


def location_to_string(location: Location):
    photo_messages = []
    for photo in location["photos"][:1]:
        photo_messages.append(f"![фото]({photo})")
    photo_string = "\n".join(photo_messages)
    message = f"""### {location["name"]}
Адрес: {location["address"]}
Описание: {location["description"]}
Теги: {location["tags"]}
Фото: {photo_string}"""
    return message


def attraction_to_string(attraction: Attraction):
    return f"""### {attraction["name"]}
Описание: {attraction["description"]}"""


# async def main():
#     config = {"configurable": {"thread_id": str(uuid.uuid4())}}
#     async for event in graph.astream(
#         {"city_name": "Москва"},
#         config=config,
#     ):
#         print(event)
#     state = graph.get_state(config=config).values
#     hotels_message = []
#     food_message = []
#     attractions_message = []
#     for hotel in state["hotels"]:
#         hotels_message.append(location_to_string(hotel))
#     for food in state["food"]:
#         food_message.append(location_to_string(food))
#     for attraction in state["attractions"]:
#         attractions_message.append(attraction_to_string(attraction))
#     print("\n".join(hotels_message))
#     print("\n".join(food_message))
#     print("\n".join(attractions_message))
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
