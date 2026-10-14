from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage

from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.agent.tool_results import build_error_tool_message
from giga_agent.core.agent.types import Collection
from giga_agent.core.db import get_session_factory
from giga_agent.embeddings.manager import EmbeddingManager
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.modules.rag.database.collection_names import (
    rag_qdrant_collection_name_for_embedding,
)
from giga_agent.modules.rag.database.qdrant_store import build_filter, search_chunks
from giga_agent.utils.langgraph_sdk import get_user_id_from_config
from giga_agent.vectorstores.qdrant import (
    get_qdrant_client,
    resolve_qdrant_collection,
)


@tool(
    description="""Семантический поиск по базе знаний пользователя через векторный поиск.

Используй для поиска информации из документов пользователя. Формулируй query как естественный вопрос.
При недостатке информации делай повторные запросы с другими формулировками.
Всегда цитируй источники (ID документа) в ответах.""",
    extras=tool_extras(ToolEffect.READ),
)
async def get_documents(
    collection_uuid: Annotated[str, "UUID-коллекции"],
    query: Annotated[str, "Поисковый запрос для поиска релевантных документов"],
    runtime: ToolRuntime,
    limit: Annotated[int, "Количество документов, которые возвращаются"] = 10,
) -> str | ToolMessage:
    def _error(message: str) -> ToolMessage:
        return build_error_tool_message(
            content=f"<all-documents>\n  <error>{message}</error>\n</all-documents>",
            runtime=runtime,
            tool_name="get_documents",
        )

    if runtime is None:
        return _error("ToolRuntime is required")

    user_id = get_user_id_from_config(runtime.config)
    owner_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    try:
        collection_id = uuid.UUID(collection_uuid)
    except ValueError:
        return _error("Invalid collection UUID")

    factory = await get_session_factory()
    async with factory() as session:
        collection = await RagCollectionsRepository(session).get_by_id(
            owner_id=owner_id,
            collection_id=collection_id,
        )
        if collection is None:
            return _error("Collection not found")

        embedding_runtime = await EmbeddingManager.resolve_by_id(
            collection.embedding_id,
            session=session,
        )
        embeddings = await embedding_runtime.get_embeddings()

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
            collection_name=rag_qdrant_collection_name_for_embedding(
                collection.embedding_id
            ),
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
        return _error(str(e))

    formatted_docs = "Найденные части документов:\n"
    for p in points:
        payload = p.payload or {}
        chunk_id = str(p.id)
        doc_id = str(payload.get("document_id") or payload.get("file_id") or "")
        name = str(payload.get("document_name") or payload.get("name") or "")
        start_index = payload.get("start_index")
        end_index = payload.get("end_index")
        sandbox_path = str(payload.get("sandbox_path") or "")
        content = str(payload.get("page_content") or "")

        attrs = [
            f'id="{chunk_id}"',
            f'document_id="{doc_id}"' if doc_id else "",
            f'name="{name}"' if name else "",
            f'start_index="{start_index}"' if start_index is not None else "",
            f'end_index="{end_index}"' if end_index is not None else "",
            f'sandbox_path="{sandbox_path}"' if sandbox_path else "",
        ]
        attrs_str = " ".join(a for a in attrs if a)
        formatted_docs += f"  <document {attrs_str}>\n    {content}\n  </document>\n"

    return (
        formatted_docs
        + "Если информации недостаточно, попробуй расширить запрос и вызвать get_documents повторно"
    )


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
