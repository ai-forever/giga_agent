from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from langchain.tools import ToolRuntime, tool

from giga_agent.core.db import get_session_factory
from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.modules.rag.database.collection_names import (
    rag_qdrant_collection_name_for_embedding,
)
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    resolve_qdrant_collection,
)
from giga_agent.modules.rag.database.qdrant_store import build_filter, search_chunks
from giga_agent.modules.rag.database.repositories import RagCollectionsRepository
from giga_agent.core.agent.types import Collection


@tool(
    description="""Семантический поиск по базе знаний пользователя через векторный поиск.

Используй для поиска информации из документов пользователя. Формулируй query как естественный вопрос.
При недостатке информации делай повторные запросы с другими формулировками.
Всегда цитируй источники (ID документа) в ответах.""",
)
async def get_documents(
    collection_uuid: Annotated[str, "UUID-коллекции"],
    query: Annotated[str, "Поисковый запрос для поиска релевантных документов"],
    runtime: ToolRuntime,
    limit: Annotated[int, "Количество документов, которые возвращаются"] = 10,
) -> dict:
    def _json(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    hint = (
        "Чтобы изучить документ подробнее, прочитай исходный файл по `sandbox_path` "
        "и возьми фрагмент между `start_index` и `end_index` (при необходимости расширь диапазон)."
    )

    if runtime is None:
        return {"error": "ToolRuntime is required", "documents": [], "hint": hint}

    user_id = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    try:
        collection_id = uuid.UUID(collection_uuid)
    except ValueError:
        return {"error": "Invalid collection UUID", "documents": [], "hint": hint}

    factory = await get_session_factory()
    async with factory() as session:
        collection = await RagCollectionsRepository(session).get_by_id(
            owner_id=owner_id,
            collection_id=collection_id,
        )
        if collection is None:
            return _json({"error": "Collection not found", "documents": [], "hint": hint})

        embedding_runtime = await EmbeddingManager.resolve_by_id(
            collection.embedding_id,
            session=session,
        )
        embeddings = embedding_runtime.embeddings

    qdrant_client = get_qdrant_client()
    try:
        qfilter = build_filter(owner_id=owner_id, collection_id=collection_id)
        query_vector = (
            await embeddings.aembed_query(query)
            if hasattr(embeddings, "aembed_query")
            else await asyncio.to_thread(embeddings.embed_query, query)
        )
        qdrant_collection = await resolve_qdrant_collection(
            client=qdrant_client,
            collection_name=rag_qdrant_collection_name_for_embedding(collection.embedding_id),
            vector_size=len(query_vector),
        )
        points = await search_chunks(
            client=qdrant_client,
            collection_name=qdrant_collection,
            query_vector=query_vector,
            query_filter=qfilter,
            limit=limit,
        )
    except Exception as e:
        return {"error": str(e), "documents": [], "hint": hint}

    documents: list[dict] = []
    for p in points:
        payload = p.payload or {}
        chunk_id = str(p.id)
        doc_id = payload.get("document_id") or payload.get("file_id")
        name = payload.get("document_name") or payload.get("name")
        start_index = payload.get("start_index")
        end_index = payload.get("end_index")
        sandbox_path = payload.get("sandbox_path")
        content = payload.get("page_content")

        documents.append(
            {
                "chunk_id": chunk_id,
                "document_id": str(doc_id) if doc_id else None,
                "name": str(name) if name else None,
                "start_index": start_index,
                "end_index": end_index,
                "sandbox_path": str(sandbox_path) if sandbox_path else None,
                "content": str(content) if content else "",
                "score": getattr(p, "score", None),
            }
        )

    return {
        "collection_uuid": str(collection_id),
        "query": query,
        "limit": limit,
        "documents": documents,
        "hint": hint,
        "next_step": "Если информации недостаточно, переформулируй запрос и вызови get_documents ещё раз.",
    }


def has_collections(state):
    return len(state.get("collections", [])) > 0


RAG_PROMPT = """
====
БАЗА ЗНАНИЙ

У тебя есть доступ к документам пользователя через инструмент get_documents.
ВСЕГДА проверяй информацию в базе знаний перед ответом, даже если уверен в своих знаниях.

ДОСТУПНЫЕ КОЛЛЕКЦИИ:
{0}

СТРАТЕГИЯ РАБОТЫ:

1. ПРОСТЫЕ ЗАПРОСЫ (конкретный факт/процедура):
   * Сформулируй query как естественный вопрос с ключевыми терминами
   * Начни с limit=5-10
   * Если результат неполный → переформулируй (синонимы, другой угол)
   * Для смежных коллекций делай отдельные запросы

2. ГЛУБОКИЙ АНАЛИЗ:
   * Шаг 1: Обзорный запрос -> определи структуру и ключевые термины
   * Шаг 2: Декомпозиция на аспекты (условия, ограничения, обязательства, риски, процедуры, стоимость)
   * Шаг 3: Серия целевых запросов по каждому аспекту к базе знаний
   * Шаг 4: Структурированный отчет:
     - Резюме и выводы
     - Ключевые условия/риски с цитатами
     - Вопросы для уточнения
     - Таблица основных параметров

ЦИТИРОВАНИЕ: Всегда указывай ID документа и, если есть, раздел/пункт/страницу.

"""


def get_rag_info(collections: list[Collection]):
    if not collections:
        return ""
    descriptions = []
    for collection in collections:
        description = (
            f"Название коллекции: {collection['name']}\nUUID: {collection['uuid']}"
        )
        if collection.get("metadata", {}).get("description"):
            description += (
                f"\nОписание коллекции: {collection['metadata']['description']}"
            )
        descriptions.append(description)
    return RAG_PROMPT.format("\n---\n".join(descriptions))
