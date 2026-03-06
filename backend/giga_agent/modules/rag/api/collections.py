from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models import UserShort
from giga_agent.core.db import get_session
from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.rag.database.collection_names import (
    rag_qdrant_collection_name_for_embedding,
)
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    resolve_qdrant_collection,
)
from giga_agent.modules.rag.database.qdrant_store import build_filter, delete_by_filter
from giga_agent.models.rag import (
    RagCollectionsRepository,
    RagDocumentsRepository,
)
from giga_agent.modules.rag.schemas.collection import (
    CollectionResponse,
    CollectionCreate,
    CollectionUpdate,
)
from giga_agent.sandbox.manager import SandboxManager

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collections_create(
    collection_data: CollectionCreate,
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Creates a new collection with optional metadata."""
    if current_user.embedding_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User embedding model is not configured",
        )

    # Ensure Qdrant tech collection exists for this embedding model.
    runtime = await EmbeddingManager.resolve_by_id(
        current_user.embedding_id,
        session=db,
    )
    vector_size = int(runtime.vector_size)

    client = get_qdrant_client()
    await resolve_qdrant_collection(
        client=client,
        collection_name=rag_qdrant_collection_name_for_embedding(current_user.embedding_id),
        vector_size=vector_size,
    )

    repo = RagCollectionsRepository(db)
    try:
        created = await repo.create(
            owner_id=current_user.id,
            name=collection_data.name,
            embedding_id=current_user.embedding_id,
            metadata=collection_data.metadata,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collection with this name already exists",
        )

    return CollectionResponse(
        uuid=str(created.id),
        name=created.name,
        can_edit=True,
        metadata=created.metadata_ or {},
    )


@router.get("", response_model=list[CollectionResponse])
async def collections_list(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Lists all available collections (name and UUID)."""
    repo = RagCollectionsRepository(db)
    rows = await repo.list_readable_with_edit_for_user(user_id=current_user.id)
    return [
        CollectionResponse(
            uuid=str(collection.id),
            name=collection.name,
            can_edit=can_edit,
            metadata=collection.metadata_ or {},
        )
        for collection, can_edit in rows
    ]


@router.get("/{collection_id}", response_model=CollectionResponse)
async def collections_get(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Retrieves details (name and UUID) of a specific collection."""
    repo = RagCollectionsRepository(db)
    row = await repo.get_by_id_with_access_for_user(
        user_id=current_user.id,
        collection_id=collection_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found",
        )
    collection, can_read, can_edit = row
    if not can_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    return CollectionResponse(
        uuid=str(collection.id),
        name=collection.name,
        can_edit=can_edit,
        metadata=collection.metadata_ or {},
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def collections_delete(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Deletes a specific collection by id."""
    repo = RagCollectionsRepository(db)
    row = await repo.get_by_id_with_access_for_user(
        user_id=current_user.id,
        collection_id=collection_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found",
        )
    collection, _, can_edit = row
    if not can_edit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Best-effort delete all files from sandbox storage (S3) + remove core_files metadata.
    docs_repo = RagDocumentsRepository(db)
    offset = 0
    limit = 200
    while True:
        docs = await docs_repo.list_by_collection(
            owner_id=collection.owner_id,
            collection_id=collection_id,
            limit=limit,
            offset=offset,
        )
        if not docs:
            break
        for d in docs:
            if not d.sandbox_path:
                continue
            await SandboxManager(db).delete_file_by_path_for_user(
                user_id=collection.owner_id,
                sandbox_path=d.sandbox_path,
            )
        offset += len(docs)

    # Remove all chunks belonging to this collection from the vector DB.
    qdrant_client = get_qdrant_client()
    runtime = await EmbeddingManager.resolve_by_id(collection.embedding_id, session=db)
    vector_size = int(runtime.vector_size)
    qdrant_collection = await resolve_qdrant_collection(
        client=qdrant_client,
        collection_name=rag_qdrant_collection_name_for_embedding(collection.embedding_id),
        vector_size=vector_size,
    )
    qfilter = build_filter(owner_id=collection.owner_id, collection_id=collection_id)
    await delete_by_filter(
        client=qdrant_client,
        collection_name=qdrant_collection,
        query_filter=qfilter,
    )

    await repo.delete(owner_id=collection.owner_id, collection_id=collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def collections_update(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    collection_data: CollectionUpdate,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Updates a specific collection's name and/or metadata."""
    repo = RagCollectionsRepository(db)
    row = await repo.get_by_id_with_access_for_user(
        user_id=current_user.id,
        collection_id=collection_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_id}' not found",
        )
    collection, _, can_edit = row
    if not can_edit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    updated_collection = await RagCollectionsRepository(db).update(
        owner_id=collection.owner_id,
        collection_id=collection_id,
        name=collection_data.name,
        metadata=collection_data.metadata,
    )

    if updated_collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to update collection '{collection_id}'",
        )

    return CollectionResponse(
        uuid=str(updated_collection.id),
        name=updated_collection.name,
        can_edit=True,
        metadata=updated_collection.metadata_ or {},
    )
