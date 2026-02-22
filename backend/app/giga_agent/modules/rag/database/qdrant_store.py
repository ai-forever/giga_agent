from __future__ import annotations

import uuid
from typing import Any, Iterable

from qdrant_client.http import models as qmodels

from giga_agent.vectorstores.qdrant import QdrantAnyClient, qdrant_call


def _match_value(value: Any) -> qmodels.Match:
    return qmodels.MatchValue(value=value)


def build_filter(
    *,
    owner_id: uuid.UUID,
    collection_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
) -> qmodels.Filter:
    must: list[qmodels.FieldCondition] = [
        qmodels.FieldCondition(key="owner_id", match=_match_value(str(owner_id))),
        qmodels.FieldCondition(
            key="collection_id", match=_match_value(str(collection_id))
        ),
    ]
    if document_id is not None:
        must.append(
            qmodels.FieldCondition(
                key="document_id", match=_match_value(str(document_id))
            )
        )
    return qmodels.Filter(must=must)


async def upsert_chunks(
    *,
    client: QdrantAnyClient,
    collection_name: str,
    points: Iterable[qmodels.PointStruct],
) -> None:
    await qdrant_call(
        client,
        "upsert",
        collection_name=collection_name,
        points=list(points),
    )


async def search_chunks(
    *,
    client: QdrantAnyClient,
    collection_name: str,
    query_vector: list[float],
    query_filter: qmodels.Filter,
    limit: int,
) -> list[qmodels.ScoredPoint]:
    resp = await qdrant_call(
        client,
        "query_points",
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    return list(resp.points)


async def delete_by_filter(
    *,
    client: QdrantAnyClient,
    collection_name: str,
    query_filter: qmodels.Filter,
) -> None:
    await qdrant_call(
        client,
        "delete",
        collection_name=collection_name,
        points_selector=qmodels.FilterSelector(filter=query_filter),
    )

