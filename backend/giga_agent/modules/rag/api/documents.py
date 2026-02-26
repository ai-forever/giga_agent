from giga_agent.core.logging import get_logger
from typing import Annotated, Any
import uuid
from uuid import UUID

import asyncio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client.http import models as qmodels

from giga_agent.core.db import get_session
from giga_agent.models.users import UserShort
from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.rag.database.collection_names import (
    rag_qdrant_collection_name_for_embedding,
)
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    resolve_qdrant_collection,
)
from giga_agent.modules.rag.database.qdrant_store import (
    build_filter,
    delete_by_filter,
    search_chunks as qdrant_search_chunks,
    upsert_chunks,
)
from giga_agent.models.rag import (
    RagCollectionsRepository,
    RagDocumentsRepository,
)
from giga_agent.modules.rag.schemas.document import (
    DocumentResponse,
    SearchQuery,
    SearchResult,
)
from giga_agent.modules.rag.services import process_document
from giga_agent.sandbox.manager import SandboxManager

# Create a TypeAdapter that enforces “list of dict”
_metadata_adapter = TypeAdapter(list[dict[str, Any]])

logger = get_logger(__name__)

router = APIRouter(tags=["documents"])


@router.post("/collections/{collection_id}/documents", response_model=dict[str, Any])
async def documents_create(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    files: list[UploadFile] = File(...),
    metadatas_json: str | None = Form(None),
):
    """Processes and indexes (adds) new document files with optional metadata."""
    # If no metadata JSON is provided, fill with None
    if not metadatas_json:
        metadatas: list[dict] | list[None] = [None] * len(files)
    else:
        try:
            # This will both parse the JSON and check the Python types
            # (i.e. that it's a list, and every item is a dict)
            metadatas = _metadata_adapter.validate_json(metadatas_json)
        except ValidationError as e:
            # Pydantic errors include exactly what went wrong
            raise HTTPException(status_code=400, detail=e.errors())
        # Now just check that the list length matches
        if len(metadatas) != len(files):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Number of metadata objects ({len(metadatas)}) "
                    f"does not match number of files ({len(files)})."
                ),
            )

    processed_files_count = 0
    failed_files = []
    added_chunk_ids: list[str] = []

    collection = await RagCollectionsRepository(db).get_by_id(
        owner_id=current_user.id,
        collection_id=collection_id,
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    runtime = await EmbeddingManager.resolve_by_id(collection.embedding_id, session=db)
    embeddings = runtime.embeddings
    vector_size = int(runtime.vector_size)
    qdrant_client = get_qdrant_client()
    qdrant_collection = await resolve_qdrant_collection(
        client=qdrant_client,
        collection_name=rag_qdrant_collection_name_for_embedding(collection.embedding_id),
        vector_size=vector_size,
    )

    # Pair files with their corresponding metadata
    for file, metadata in zip(files, metadatas, strict=False):
        try:
            file_id, full_text, chunk_docs = await process_document(file, metadata=metadata)
            if not chunk_docs:
                logger.warning(
                    f"Warning: File {file.filename} resulted in no processable documents."
                )
                continue

            file_uuid = UUID(file_id)
            sandbox_rel_path = f"rag/{collection_id}/{file_uuid}.txt"
            sandbox_file = await SandboxManager(db).upload_file_for_user(
                owner_id=current_user.id,
                file_name=sandbox_rel_path,
                content=(full_text or "").encode("utf-8"),
                file_type="text",
            )
            await RagDocumentsRepository(db).create(
                owner_id=current_user.id,
                collection_id=collection_id,
                document_id=file_uuid,
                original_name=(metadata or {}).get("name") or file.filename or "document",
                sandbox_path=sandbox_file.sandbox_path,
            )

            # Embed + upsert into Qdrant
            texts = [d.page_content for d in chunk_docs]
            vectors = await asyncio.to_thread(embeddings.embed_documents, texts)
            if not vectors:
                continue
            if len(vectors[0]) != vector_size:
                raise ValueError(
                    f"Embeddings vector size mismatch: got {len(vectors[0])}, expected {vector_size}"
                )

            points = []
            for idx, (doc, vector) in enumerate(zip(chunk_docs, vectors, strict=False)):
                chunk_id = uuid.uuid4().hex
                payload = dict(doc.metadata or {})
                payload.update(
                    {
                        "owner_id": str(current_user.id),
                        "collection_id": str(collection_id),
                        "embedding_id": str(collection.embedding_id),
                        "document_id": str(file_uuid),
                        "document_name": (metadata or {}).get("name")
                        or file.filename
                        or "document",
                        "sandbox_path": sandbox_file.sandbox_path,
                        "chunk_index": idx,
                        "page_content": doc.page_content,
                    }
                )
                points.append(
                    qmodels.PointStruct(id=chunk_id, vector=vector, payload=payload)  # type: ignore[name-defined]
                )
                added_chunk_ids.append(chunk_id)

            await upsert_chunks(
                client=qdrant_client,
                collection_name=qdrant_collection,
                points=points,
            )

            processed_files_count += 1

        except Exception:
            logger.exception("Error processing file", filename=file.filename)
            failed_files.append(file.filename)
            # Decide on behavior: continue processing others or fail fast?
            # For now, let's collect failures and report them, but continue processing.

    if processed_files_count == 0:
        error_detail = "Failed to process any documents from the provided files."
        if failed_files:
            error_detail += f" Files that failed processing: {', '.join(failed_files)}."
        raise HTTPException(status_code=400, detail=error_detail)

    response_data = {
        "success": True,
        "message": (
            f"{len(added_chunk_ids)} document chunk(s) from "
            f"{processed_files_count} file(s) added successfully."
        ),
        "added_chunk_ids": added_chunk_ids,
    }
    if failed_files:
        response_data["warnings"] = (
            f"Processing failed for files: {', '.join(failed_files)}"
        )
    return response_data


@router.get(
    "/collections/{collection_id}/documents", response_model=list[DocumentResponse]
)
async def documents_list(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Lists documents within a specific collection."""
    docs = await RagDocumentsRepository(db).list_by_collection(
        owner_id=current_user.id,
        collection_id=collection_id,
        limit=limit,
        offset=offset,
    )
    return [
        DocumentResponse(
            id=str(d.id),
            collection_id=str(d.collection_id),
            content=None,
            metadata={
                "file_id": str(d.id),
                "name": d.original_name,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "sandbox_path": d.sandbox_path,
            },
            created_at=d.created_at.isoformat() if d.created_at else None,
            updated_at=d.updated_at.isoformat() if d.updated_at else None,
        )
        for d in docs
    ]


@router.delete(
    "/collections/{collection_id}/documents/{document_id}",
    response_model=dict[str, bool],
)
async def documents_delete(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    document_id: str,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Deletes a specific document from a collection by its ID."""
    collection = await RagCollectionsRepository(db).get_by_id(
        owner_id=current_user.id,
        collection_id=collection_id,
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document_id")

    doc = await RagDocumentsRepository(db).get_by_id(
        owner_id=current_user.id,
        collection_id=collection_id,
        document_id=doc_uuid,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    qdrant_client = get_qdrant_client()
    runtime = await EmbeddingManager.resolve_by_id(collection.embedding_id, session=db)
    vector_size = int(runtime.vector_size)
    qdrant_collection = await resolve_qdrant_collection(
        client=qdrant_client,
        collection_name=rag_qdrant_collection_name_for_embedding(collection.embedding_id),
        vector_size=vector_size,
    )
    qfilter = build_filter(
        owner_id=current_user.id,
        collection_id=collection_id,
        document_id=doc_uuid,
    )
    await delete_by_filter(
        client=qdrant_client,
        collection_name=qdrant_collection,
        query_filter=qfilter,
    )

    # Best-effort delete file from sandbox storage (S3) + remove core_files metadata.
    await SandboxManager(db).delete_file_by_path_for_user(
        owner_id=current_user.id,
        sandbox_path=doc.sandbox_path,
    )

    ok = await RagDocumentsRepository(db).delete(
        owner_id=current_user.id,
        collection_id=collection_id,
        document_id=doc_uuid,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Failed to delete document.")

    return {"success": True}


@router.post(
    "/collections/{collection_id}/documents/search", response_model=list[SearchResult]
)
async def documents_search(
    current_user: Annotated[UserShort, Depends(get_current_active_user)],
    collection_id: UUID,
    search_query: SearchQuery,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Search for documents within a specific collection."""
    if not search_query.query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty")

    collection = await RagCollectionsRepository(db).get_by_id(
        owner_id=current_user.id,
        collection_id=collection_id,
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    runtime = await EmbeddingManager.resolve_by_id(collection.embedding_id, session=db)
    embeddings = runtime.embeddings
    query_vector = (
        await embeddings.aembed_query(search_query.query)
        if hasattr(embeddings, "aembed_query")
        else await asyncio.to_thread(embeddings.embed_query, search_query.query)
    )

    qdrant_client = get_qdrant_client()
    qdrant_collection = await resolve_qdrant_collection(
        client=qdrant_client,
        collection_name=rag_qdrant_collection_name_for_embedding(collection.embedding_id),
        vector_size=len(query_vector),
    )
    qfilter = build_filter(owner_id=current_user.id, collection_id=collection_id)
    points = await qdrant_search_chunks(
        client=qdrant_client,
        collection_name=qdrant_collection,
        query_vector=query_vector,
        query_filter=qfilter,
        limit=search_query.limit or 10,
    )

    results: list[SearchResult] = []
    for p in points:
        payload = p.payload or {}
        results.append(
            SearchResult(
                id=str(p.id),
                page_content=str(payload.get("page_content") or ""),
                metadata=payload,
                score=float(p.score),
            )
        )
    return results
