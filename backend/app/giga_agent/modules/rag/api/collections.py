from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from giga_agent.models import UserShort
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.rag.database.collections import CollectionsManager
from giga_agent.modules.rag.models.collection import (
    CollectionResponse,
    CollectionCreate,
    CollectionUpdate,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collections_create(
    collection_data: CollectionCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    """Creates a new PGVector collection by name with optional metadata."""
    collection_info = await CollectionsManager(str(current_user.id)).create(
        collection_data.name, collection_data.metadata
    )
    if not collection_info:
        raise HTTPException(status_code=500, detail="Failed to create collection")
    return CollectionResponse(**collection_info)


@router.get("", response_model=list[CollectionResponse])
async def collections_list(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
):
    """Lists all available PGVector collections (name and UUID)."""
    return [
        CollectionResponse(**c)
        for c in await CollectionsManager(str(current_user.id)).list()
    ]


@router.get("/{collection_id}", response_model=CollectionResponse)
async def collections_get(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
):
    """Retrieves details (name and UUID) of a specific PGVector collection."""
    collection = await CollectionsManager(str(current_user.id)).get(str(collection_id))
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found",
        )
    return CollectionResponse(**collection)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def collections_delete(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
):
    """Deletes a specific PGVector collection by name."""
    await CollectionsManager(str(current_user.id)).delete(str(collection_id))
    return "Collection deleted successfully."


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def collections_update(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    collection_data: CollectionUpdate,
):
    """Updates a specific PGVector collection's name and/or metadata."""
    updated_collection = await CollectionsManager(str(current_user.id)).update(
        str(collection_id),
        name=collection_data.name,
        metadata=collection_data.metadata,
    )

    if not updated_collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to update collection '{collection_id}'",
        )

    return CollectionResponse(**updated_collection)
