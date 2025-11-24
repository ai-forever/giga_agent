import json
import asyncio
import httpx
from typing import TypedDict, Optional, List
from langchain_tavily import TavilySearch
from markdownify import markdownify as md
from giga_agent.settings import settings


class GISException(Exception):
    pass


class Point(TypedDict):
    lat: str
    lon: str


class Location(TypedDict):
    id: str
    address: str
    name: str
    tags: str
    icon: Optional[str]
    photos: List[str]
    point: Point
    description: str


class Attraction(TypedDict):
    id: str
    name: str
    description: str
    photos: List[str]
    point: Point


async def fetch_city_cords(city_name: str) -> Point:
    url = "https://catalog.api.2gis.com/3.0/items"
    params = {
        "q": city_name.strip(),
        "type": "adm_div",
        "page_size": 10,
        "page": 1,
        "key": settings.external.twogis_token,
        "fields": "items.external_content,items.point",
    }
    headers = {}
    # Если payload на GET не нужен, можно убрать data; параметры переданы в params
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()  # выбросит исключение при ошибке
        data = response.json()
        response_code = data["meta"]["code"]
        if response_code != 200:
            if response_code == 404:
                raise GISException(f"City '{city_name}' not found")
            else:
                raise GISException(
                    json.dumps(data["meta"]["error"], ensure_ascii=False)
                )
        return data["result"]["items"][0]["point"]


async def fetch_branches(q: str, point: Point, district_id=None):
    url = "https://catalog.api.2gis.com/3.0/items"
    params = {
        "q": q,
        "type": "branch",
        "page_size": 20,
        "radius": 4000,
        "search_nearby": True,
        "page": 1,
        "sort": "rating",
        "key": settings.external.twogis_token,
        "fields": "items.context,items.rubrics,items.external_content,items.attribute_groups,items.point",
        "location": f"{point['lon']},{point['lat']}",
        "point": f"{point['lon']},{point['lat']}",
    }
    if district_id is not None:
        params["district_id"] = district_id
    headers = {}
    result_items: list[Location] = []
    names = []
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()  # выбросит исключение при ошибке
        data = response.json()
        response_code = data["meta"]["code"]
        if response_code != 200:
            if response_code == 404:
                raise GISException(f"Results not found")
            else:
                raise GISException(
                    json.dumps(data["meta"]["error"], ensure_ascii=False)
                )
        for item in data["result"]["items"]:
            if item["name"] in names:
                continue
            icon_url = None
            for a_g in item.get("attribute_groups", []):
                if "icon_url" in a_g:
                    icon_url = a_g["icon_url"]
            tags = set()
            for stop_factor in item.get("context", {}).get("stop_factors", []):
                if stop_factor.get("name"):
                    tags.add(stop_factor["name"])
            for rubric in item.get("rubrics", []):
                if rubric.get("name"):
                    tags.add(rubric["name"])
            photos = []
            for content in item.get("external_content", []):
                if content.get("main_photo_url"):
                    photos.append(content["main_photo_url"])

            result_items.append(
                {
                    "id": item["id"],
                    "address": item.get("address_name", ""),
                    "name": item["name"],
                    "tags": ", ".join(tags),
                    "icon": icon_url,
                    "photos": photos,
                    "point": item["point"],
                    "description": "",
                }
            )
            names.append(item["name"])
    return result_items


async def fetch_attractions(point: Point):
    url = "https://catalog.api.2gis.com/3.0/items"
    params = {
        "q": "достопримечательности",
        "type": "attraction",
        "page_size": 15,
        "radius": 3000,
        "sort": "rating",
        "page": 1,
        "key": settings.external.twogis_token,
        "fields": "items.description,items.context,items.rubrics,items.external_content,items.attribute_groups,items.point",
        "point": f"{point['lon']},{point['lat']}",
    }
    headers = {}
    result_items: list[Attraction] = []
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()  # выбросит исключение при ошибке
        data = response.json()
        response_code = data["meta"]["code"]
        if response_code != 200:
            if response_code == 404:
                raise GISException(f"Results not found")
            else:
                raise GISException(
                    json.dumps(data["meta"]["error"], ensure_ascii=False)
                )
        for item in data["result"]["items"]:
            if not item.get("description"):
                continue
            photos = []
            for content in item.get("external_content", []):
                if content.get("main_photo_url"):
                    photos.append(content["main_photo_url"])
            since = item.get("since", "")
            if since:
                since = "\n\n" + since
            result_items.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "photos": photos,
                    "point": item["point"],
                    "description": md(item["description"]) + since,
                }
            )
    return result_items


async def location_to_description(location: Location, city: str) -> Optional[str]:
    search = TavilySearch(include_answer="advanced")
    result = await search.ainvoke(
        {
            "query": f"{location['name']} номер телефона; {city}, {location['address']}",
        }
    )
    return result["answer"]


if __name__ == "__main__":

    async def main():
        city = "мурино"
        cords = await fetch_city_cords(city)
        print(cords)
        # branches = await fetch_branches("поесть", cords)
        # attractions = await fetch_attractions(cords)
        # print(await location_to_description(branches[0], city))

    asyncio.run(main())
