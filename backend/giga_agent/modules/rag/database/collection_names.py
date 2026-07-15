from __future__ import annotations

import uuid


def rag_qdrant_collection_name_for_embedding(embedding_id: uuid.UUID) -> str:
    """
    Qdrant collection name for RAG chunks for a given embedding model.

    Keep names simple ASCII for compatibility.
    """
    return f"rag_chunks__{embedding_id.hex}"
