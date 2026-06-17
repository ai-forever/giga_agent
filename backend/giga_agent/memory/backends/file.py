from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.memory.backends.base import (
    MemoryFileDTO,
    MemoryFileExistsError,
    MemoryFileNotFoundError,
)
from giga_agent.memory.frontmatter import parse_frontmatter
from giga_agent.memory.paths import MEMORY_ROOT, parse_memory_path


_META_SUFFIX = ".meta.json"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _owner_root(owner_id: uuid.UUID) -> Path:
    root = ensure_giga_agent_dir() / "memories" / str(owner_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _virtual_to_disk(owner_id: uuid.UUID, virtual_path: str) -> Path:
    parsed = parse_memory_path(virtual_path)
    root = _owner_root(owner_id)
    if parsed.tag is None:
        return root / parsed.filename
    tag_dir = root / parsed.tag
    tag_dir.mkdir(parents=True, exist_ok=True)
    return tag_dir / parsed.filename


def _meta_path(disk_path: Path) -> Path:
    return disk_path.with_name(disk_path.name + _META_SUFFIX)


def _read_meta(disk_path: Path) -> dict:
    meta_path = _meta_path(disk_path)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(disk_path: Path, meta: dict) -> None:
    meta_path = _meta_path(disk_path)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _disk_to_virtual(owner_id: uuid.UUID, disk_path: Path) -> str:
    root = _owner_root(owner_id)
    rel = disk_path.relative_to(root)
    return f"{MEMORY_ROOT}/" + str(rel).replace("\\", "/")


def _load_dto(owner_id: uuid.UUID, disk_path: Path) -> MemoryFileDTO:
    content = disk_path.read_text(encoding="utf-8")
    meta = _read_meta(disk_path)
    file_id_raw = meta.get("id")
    file_id = uuid.UUID(file_id_raw) if file_id_raw else uuid.uuid4()
    if file_id_raw is None:
        meta["id"] = str(file_id)
        _write_meta(disk_path, meta)

    indexed_emb_raw = meta.get("indexed_embedding_id")
    indexed_emb = uuid.UUID(indexed_emb_raw) if indexed_emb_raw else None

    parsed = parse_memory_path(_disk_to_virtual(owner_id, disk_path))
    fm = parse_frontmatter(content)

    stat = disk_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    return MemoryFileDTO(
        id=file_id,
        owner_id=owner_id,
        path=parsed.path,
        tag=parsed.tag,
        content=content,
        description=fm.description,
        content_hash=_hash(content),
        indexed_hash=meta.get("indexed_hash"),
        indexed_embedding_id=indexed_emb,
        updated_at=updated_at,
    )


class FileBackend:
    async def get(
        self, *, owner_id: uuid.UUID, path: str
    ) -> MemoryFileDTO | None:
        disk = _virtual_to_disk(owner_id, path)
        if not disk.exists():
            return None
        return await asyncio.to_thread(_load_dto, owner_id, disk)

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        tag: str | None,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO:
        disk = _virtual_to_disk(owner_id, path)
        if disk.exists():
            raise MemoryFileExistsError(f"Memory file already exists: {path}")

        def _write():
            disk.parent.mkdir(parents=True, exist_ok=True)
            disk.write_text(content, encoding="utf-8")
            meta = {
                "id": str(uuid.uuid4()),
                "indexed_hash": None,
                "indexed_embedding_id": None,
            }
            _write_meta(disk, meta)

        await asyncio.to_thread(_write)
        return await asyncio.to_thread(_load_dto, owner_id, disk)

    async def update(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content: str,
        description: str | None,
    ) -> MemoryFileDTO:
        disk = _virtual_to_disk(owner_id, path)
        if not disk.exists():
            raise MemoryFileNotFoundError(f"Memory file not found: {path}")

        def _write():
            old_content = disk.read_text(encoding="utf-8")
            new_hash = _hash(content)
            disk.write_text(content, encoding="utf-8")
            meta = _read_meta(disk)
            if old_content and meta.get("indexed_hash"):
                # invalidate index if content changed
                if _hash(old_content) != new_hash:
                    meta["indexed_hash"] = None
                    meta["indexed_embedding_id"] = None
            meta.setdefault("id", str(uuid.uuid4()))
            _write_meta(disk, meta)

        await asyncio.to_thread(_write)
        return await asyncio.to_thread(_load_dto, owner_id, disk)

    async def delete(self, *, owner_id: uuid.UUID, path: str) -> bool:
        disk = _virtual_to_disk(owner_id, path)
        if not disk.exists():
            return False

        def _do():
            disk.unlink(missing_ok=True)
            meta = _meta_path(disk)
            meta.unlink(missing_ok=True)
            # clean up empty tag directory
            parent = disk.parent
            owner_root = _owner_root(owner_id)
            if parent != owner_root and not any(parent.iterdir()):
                try:
                    parent.rmdir()
                except OSError:
                    pass

        await asyncio.to_thread(_do)
        return True

    async def list(
        self,
        *,
        owner_id: uuid.UUID,
        tags: list[str] | None,
        include_global: bool,
    ) -> list[MemoryFileDTO]:
        def _scan():
            root = _owner_root(owner_id)
            results: list[MemoryFileDTO] = []
            if not root.exists():
                return results

            if include_global:
                for entry in sorted(root.iterdir()):
                    if entry.is_file() and not entry.name.endswith(_META_SUFFIX):
                        results.append(_load_dto(owner_id, entry))

            if tags:
                for tag in tags:
                    tag_dir = root / tag
                    if not tag_dir.is_dir():
                        continue
                    for entry in sorted(tag_dir.iterdir()):
                        if entry.is_file() and not entry.name.endswith(_META_SUFFIX):
                            results.append(_load_dto(owner_id, entry))

            return results

        return await asyncio.to_thread(_scan)

    async def list_all(
        self, *, owner_id: uuid.UUID
    ) -> list[MemoryFileDTO]:
        def _scan():
            root = _owner_root(owner_id)
            results: list[MemoryFileDTO] = []
            if not root.exists():
                return results
            for entry in sorted(root.rglob("*")):
                if not entry.is_file():
                    continue
                if entry.name.endswith(_META_SUFFIX):
                    continue
                results.append(_load_dto(owner_id, entry))
            return results

        return await asyncio.to_thread(_scan)

    async def list_needs_reindex(
        self,
        *,
        owner_id: uuid.UUID,
        current_embedding_id: uuid.UUID,
    ) -> list[MemoryFileDTO]:
        def _scan():
            root = _owner_root(owner_id)
            results: list[MemoryFileDTO] = []
            if not root.exists():
                return results
            for entry in root.rglob("*"):
                if not entry.is_file():
                    continue
                if entry.name.endswith(_META_SUFFIX):
                    continue
                dto = _load_dto(owner_id, entry)
                if (
                    dto.indexed_hash is None
                    or dto.indexed_hash != dto.content_hash
                    or dto.indexed_embedding_id != current_embedding_id
                ):
                    results.append(dto)
            return results

        return await asyncio.to_thread(_scan)

    async def mark_indexed(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        content_hash: str,
        embedding_id: uuid.UUID,
    ) -> None:
        disk = _virtual_to_disk(owner_id, path)
        if not disk.exists():
            return

        def _update():
            meta = _read_meta(disk)
            meta["indexed_hash"] = content_hash
            meta["indexed_embedding_id"] = str(embedding_id)
            meta.setdefault("id", str(uuid.uuid4()))
            _write_meta(disk, meta)

        await asyncio.to_thread(_update)

    async def reset_indexed_for_owner(self, *, owner_id: uuid.UUID) -> int:
        def _do():
            root = _owner_root(owner_id)
            count = 0
            if not root.exists():
                return 0
            for entry in root.rglob("*" + _META_SUFFIX):
                try:
                    meta = json.loads(entry.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if meta.get("indexed_hash") is not None or meta.get("indexed_embedding_id") is not None:
                    meta["indexed_hash"] = None
                    meta["indexed_embedding_id"] = None
                    entry.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                    count += 1
            return count

        return await asyncio.to_thread(_do)


__all__ = ["FileBackend"]
