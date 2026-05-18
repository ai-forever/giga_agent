from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from cashews import cache
from langchain_core.messages import HumanMessage, SystemMessage
from qdrant_client.http import models as qmodels

from giga_agent.core.logging import get_logger
from giga_agent.embeddings.base import BaseEmbeddingRuntime
from giga_agent.memory.backends.base import (
    MemoryBackend,
    MemoryFileDTO,
    MemoryFileExistsError,
    MemoryFileNotFoundError,
)
from giga_agent.memory.chunking import chunk_text
from giga_agent.memory.frontmatter import (
    parse_frontmatter,
    serialize_frontmatter,
    strip_frontmatter,
)
from giga_agent.memory.paths import (
    is_about_file,
    parse_memory_path,
)
from giga_agent.vectorstores.qdrant import (
    QdrantAnyClient,
    ensure_qdrant_collection,
    get_qdrant_client,
    qdrant_call,
)


logger = get_logger(__name__)


MAX_MEMORY_FILE_LINES = 200
DESCRIPTION_MAX_CHARS = 256
SEARCH_DEFAULT_N = 5


class MemoryFileTooLargeError(ValueError):
    """Raised when a memory file exceeds the line limit."""

    def __init__(self, line_count: int, path: str):
        self.line_count = line_count
        self.path = path
        super().__init__(
            f"Файл памяти {path} содержит {line_count} строк, лимит — "
            f"{MAX_MEMORY_FILE_LINES}. Разбей содержимое на несколько файлов: "
            "перенеси старые/менее актуальные записи в отдельный файл "
            "(например, рядом создай archive.md или вынеси отдельные темы "
            "в собственные файлы), а в текущем оставь только ключевую "
            "и свежую информацию."
        )


@dataclass(frozen=True)
class SearchHit:
    path: str
    snippet: str
    score: float


@dataclass(frozen=True)
class WriteResult:
    file: MemoryFileDTO
    description_repaired: bool
    repaired_description: str | None


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _collection_name(embedding_id: uuid.UUID) -> str:
    return f"memories__{embedding_id.hex}"


def _count_lines(content: str) -> int:
    if not content:
        return 0
    if content.endswith("\n"):
        return content.count("\n")
    return content.count("\n") + 1


def validate_size(content: str, *, path: str) -> None:
    lines = _count_lines(content)
    if lines > MAX_MEMORY_FILE_LINES:
        raise MemoryFileTooLargeError(line_count=lines, path=path)


def _fallback_description(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:DESCRIPTION_MAX_CHARS]
    return "Файл памяти без описания"


async def _generate_description_with_llm(body: str, *, fast_llm) -> str | None:
    if fast_llm is None:
        return None
    instructions = (
        "Ты помогаешь поддерживать memory-файлы. Дай однострочное описание "
        "(до 200 символов, на русском) того, какая информация в файле и для "
        "чего его читать. Не повторяй содержимое дословно, не используй "
        "кавычки. Только описание, без префиксов."
    )
    snippet = body[:2000]
    try:
        result = await fast_llm.ainvoke(
            [
                SystemMessage(content=instructions),
                HumanMessage(content=snippet or "(файл пустой)"),
            ]
        )
        text = getattr(result, "content", None)
        if isinstance(text, list):
            text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in text
            )
        if not isinstance(text, str):
            return None
        clean = text.strip().splitlines()[0].strip() if text.strip() else ""
        return clean[:DESCRIPTION_MAX_CHARS] or None
    except Exception:
        logger.exception("Failed to generate description via fast_llm")
        return None


async def ensure_description(
    content: str,
    *,
    path: str,
    fast_llm,
) -> tuple[str, bool, str | None]:
    """Return (normalized_content, was_repaired, repaired_description).

    For ABOUT.md (global or per-tag) description is not required — returned
    content/flags reflect no repair.
    """
    parsed = parse_memory_path(path)
    fm = parse_frontmatter(content)

    if is_about_file(parsed):
        return content, False, None

    if fm.valid and fm.description:
        return content, False, None

    body = fm.body if fm.had_block else content
    description = await _generate_description_with_llm(body, fast_llm=fast_llm)
    if not description:
        description = _fallback_description(body)

    new_content = serialize_frontmatter(description, body)
    return new_content, True, description


class MemoryService:
    def __init__(
        self,
        *,
        backend: MemoryBackend,
        owner_id: uuid.UUID,
        embedding_runtime: BaseEmbeddingRuntime | None,
        embedding_id: uuid.UUID | None,
        fast_llm=None,
    ):
        if (embedding_runtime is None) != (embedding_id is None):
            raise ValueError(
                "embedding_runtime and embedding_id must be provided together"
            )
        self._backend = backend
        self._owner_id = owner_id
        self._embedding_runtime = embedding_runtime
        self._embedding_id = embedding_id
        self._fast_llm = fast_llm

    @property
    def owner_id(self) -> uuid.UUID:
        return self._owner_id

    @property
    def has_embeddings(self) -> bool:
        return self._embedding_runtime is not None

    @property
    def fast_llm(self):
        return self._fast_llm

    # ------------------------------------------------------------------
    # CRUD wrappers (used by io tools)
    # ------------------------------------------------------------------

    async def get(self, path: str) -> MemoryFileDTO | None:
        return await self._backend.get(owner_id=self._owner_id, path=path)

    async def create(
        self, *, path: str, content: str
    ) -> WriteResult:
        parsed = parse_memory_path(path)
        validate_size(content, path=path)
        normalized, repaired, repaired_desc = await ensure_description(
            content, path=path, fast_llm=self._fast_llm
        )
        fm = parse_frontmatter(normalized)
        description = fm.description if not is_about_file(parsed) else None
        try:
            row = await self._backend.create(
                owner_id=self._owner_id,
                path=path,
                tag=parsed.tag,
                content=normalized,
                description=description,
            )
        except MemoryFileExistsError:
            raise
        await self._invalidate_cache()
        return WriteResult(
            file=row,
            description_repaired=repaired,
            repaired_description=repaired_desc,
        )

    async def update(
        self, *, path: str, content: str
    ) -> WriteResult:
        parsed = parse_memory_path(path)
        validate_size(content, path=path)
        normalized, repaired, repaired_desc = await ensure_description(
            content, path=path, fast_llm=self._fast_llm
        )
        fm = parse_frontmatter(normalized)
        description = fm.description if not is_about_file(parsed) else None
        row = await self._backend.update(
            owner_id=self._owner_id,
            path=path,
            content=normalized,
            description=description,
        )
        await self._invalidate_cache()
        return WriteResult(
            file=row,
            description_repaired=repaired,
            repaired_description=repaired_desc,
        )

    async def delete(self, *, path: str) -> bool:
        # Best-effort remove vectors first; if no embeddings configured we
        # silently skip — the points (if any) become orphaned but harmless.
        existing = await self._backend.get(owner_id=self._owner_id, path=path)
        result = await self._backend.delete(owner_id=self._owner_id, path=path)
        if existing is not None and self._embedding_runtime is not None:
            try:
                await self._delete_points_for_file(existing.id)
            except Exception:
                logger.exception("Failed to delete qdrant points for %s", path)
        if result:
            await self._invalidate_cache()
        return result

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def _ensure_collection(self) -> tuple[QdrantAnyClient, str, int]:
        if self._embedding_runtime is None or self._embedding_id is None:
            raise RuntimeError("embedding_runtime is required for vector ops")
        vector_size = int(self._embedding_runtime.vector_size)
        collection = _collection_name(self._embedding_id)
        client = get_qdrant_client()
        await ensure_qdrant_collection(
            client=client,
            collection_name=collection,
            vector_size=vector_size,
        )
        return client, collection, vector_size

    async def _delete_points_for_file(self, memory_file_id: uuid.UUID) -> None:
        client, collection, _ = await self._ensure_collection()
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="memory_file_id",
                    match=qmodels.MatchValue(value=str(memory_file_id)),
                ),
                qmodels.FieldCondition(
                    key="owner_id",
                    match=qmodels.MatchValue(value=str(self._owner_id)),
                ),
            ]
        )
        await qdrant_call(
            client,
            "delete",
            collection_name=collection,
            points_selector=qmodels.FilterSelector(filter=flt),
        )

    async def index_file(self, file: MemoryFileDTO) -> bool:
        if self._embedding_runtime is None:
            return False
        client, collection, _ = await self._ensure_collection()

        await self._delete_points_for_file(file.id)

        body = strip_frontmatter(file.content)
        chunks = chunk_text(body)
        if chunks:
            embeddings = await self._embedding_runtime.get_embeddings()
            texts = [c.text for c in chunks]
            vectors = await embeddings.aembed_documents(texts)
            points = [
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={
                        "owner_id": str(self._owner_id),
                        "memory_file_id": str(file.id),
                        "path": file.path,
                        "tag": file.tag,
                        "chunk_index": c.index,
                        "chunk_text": c.text,
                        "content_hash": file.content_hash,
                    },
                )
                for c, vec in zip(chunks, vectors)
            ]
            await qdrant_call(
                client, "upsert", collection_name=collection, points=points
            )

        await self._backend.mark_indexed(
            owner_id=self._owner_id,
            path=file.path,
            content_hash=file.content_hash,
            embedding_id=self._embedding_id,
        )
        return True

    async def reindex_changed(self) -> int:
        if self._embedding_runtime is None or self._embedding_id is None:
            return 0
        files = await self._backend.list_needs_reindex(
            owner_id=self._owner_id,
            current_embedding_id=self._embedding_id,
        )
        count = 0
        for file in files:
            try:
                if await self.index_file(file):
                    count += 1
            except Exception:
                logger.exception("Failed to index memory file %s", file.path)
        return count

    async def drop_indexed_data(self) -> None:
        """Delete all qdrant points for the owner in the current collection."""
        if self._embedding_runtime is None:
            return
        client, collection, _ = await self._ensure_collection()
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="owner_id",
                    match=qmodels.MatchValue(value=str(self._owner_id)),
                ),
            ]
        )
        await qdrant_call(
            client,
            "delete",
            collection_name=collection,
            points_selector=qmodels.FilterSelector(filter=flt),
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        n: int,
        visible_tags: list[str] | None,
        include_global: bool,
    ) -> list[SearchHit]:
        if self._embedding_runtime is None:
            return []
        if not query.strip():
            return []
        # Make sure latest changes are indexed before searching.
        await self.reindex_changed()

        client, collection, _ = await self._ensure_collection()
        embeddings = await self._embedding_runtime.get_embeddings()
        vector = await embeddings.aembed_query(query)

        must: list[qmodels.Condition] = [
            qmodels.FieldCondition(
                key="owner_id",
                match=qmodels.MatchValue(value=str(self._owner_id)),
            )
        ]
        scope_conditions: list[qmodels.Condition] = []
        if include_global:
            scope_conditions.append(
                qmodels.IsNullCondition(is_null=qmodels.PayloadField(key="tag"))
            )
        if visible_tags:
            scope_conditions.append(
                qmodels.FieldCondition(
                    key="tag",
                    match=qmodels.MatchAny(any=list(visible_tags)),
                )
            )
        if not scope_conditions:
            return []

        if len(scope_conditions) == 1:
            must.extend(scope_conditions)
            flt = qmodels.Filter(must=must)
        else:
            flt = qmodels.Filter(
                must=must,
                min_should=qmodels.MinShould(
                    conditions=scope_conditions, min_count=1
                ),
            )

        resp = await qdrant_call(
            client,
            "query_points",
            collection_name=collection,
            query=vector,
            query_filter=flt,
            limit=n,
            with_payload=True,
        )
        hits: list[SearchHit] = []
        for point in resp.points:
            payload = point.payload or {}
            hits.append(
                SearchHit(
                    path=str(payload.get("path") or ""),
                    snippet=str(payload.get("chunk_text") or ""),
                    score=float(point.score or 0.0),
                )
            )
        return hits

    # ------------------------------------------------------------------
    # Visible listing
    # ------------------------------------------------------------------

    async def list_visible(
        self,
        *,
        visible_tags: list[str] | None,
        include_global: bool,
    ) -> list[MemoryFileDTO]:
        tags_sorted = sorted(visible_tags or [])
        key = self._list_cache_key(tags_sorted, include_global)
        try:
            cached = await cache.get(key)
        except Exception:
            cached = None
        if cached is not None:
            return cached

        rows = await self._backend.list(
            owner_id=self._owner_id,
            tags=tags_sorted or None,
            include_global=include_global,
        )
        try:
            await cache.set(key, rows, expire=120)
        except Exception:
            pass
        return rows

    def _list_cache_key(
        self, tags_sorted: list[str], include_global: bool
    ) -> str:
        tag_part = ",".join(tags_sorted) if tags_sorted else "_"
        return (
            f"memory:list_visible:{self._owner_id}:{tag_part}:"
            f"{int(include_global)}"
        )

    async def _invalidate_cache(self) -> None:
        try:
            await cache.delete_match(f"memory:list_visible:{self._owner_id}:*")
        except Exception as exc:
            logger.debug("Memory list cache invalidate skipped: %s", exc)


__all__ = [
    "MemoryService",
    "MemoryFileTooLargeError",
    "SearchHit",
    "WriteResult",
    "ensure_description",
    "validate_size",
    "MAX_MEMORY_FILE_LINES",
]
