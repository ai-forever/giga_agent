from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, TypeAlias

from pydantic import BaseModel, Field
from sqlalchemy import (
    DateTime,
    Text,
    Uuid,
    UniqueConstraint,
    and_,
    delete,
    exists,
    literal,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql import func

from giga_agent.core.db import Base

RESOURCE_TYPES = {
    "llm",
    "connector",
    "embedding",
    "file",
    "image_generator",
    "rag_collection",
    "sandbox",
    "search_engine",
}
OWNER_TYPES = {"user", "group"}
PERMISSIONS = {"read", "write"}


class ResourcePermission(Base):
    __tablename__ = "core_resource_permissions"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "owner_type",
            "owner_id",
            "permission",
            name="uq_core_resource_permissions_resource_owner_perm",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


ResourceModelType: TypeAlias = type[Base]


class ResourcePermissionsPayload(BaseModel):
    read_user_ids: list[uuid.UUID] = Field(default_factory=list)
    read_group_ids: list[uuid.UUID] = Field(default_factory=list)
    public_read: bool = False


@dataclass(frozen=True)
class AccessFlags:
    can_read: ColumnElement[bool]
    can_edit: ColumnElement[bool]


@dataclass(frozen=True)
class PermissionGrantItem:
    resource_type: str
    resource_id: uuid.UUID
    owner_type: str
    owner_id: uuid.UUID | str
    permission: str


@dataclass(frozen=True)
class PermissionGrantError:
    index: int
    item: PermissionGrantItem
    error: str


@dataclass(frozen=True)
class BulkGrantPermissionsResult:
    created: list["ResourcePermission"]
    existing: list["ResourcePermission"]
    errors: list[PermissionGrantError]


class ResourcePermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize(kind: str, value: str, allowed: set[str]) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in allowed:
            raise ValueError(f"Invalid {kind}: {value!r}. Allowed: {sorted(allowed)}")
        return normalized

    @classmethod
    def _normalize_resource_type(cls, value: str) -> str:
        return cls._normalize("resource_type", value, RESOURCE_TYPES)

    @classmethod
    def _normalize_owner_type(cls, value: str) -> str:
        return cls._normalize("owner_type", value, OWNER_TYPES)

    @classmethod
    def _normalize_permission(cls, value: str) -> str:
        return cls._normalize("permission", value, PERMISSIONS)

    @staticmethod
    def _normalize_owner_id(value: uuid.UUID | str) -> str:
        if isinstance(value, uuid.UUID):
            return str(value)
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("owner_id must not be empty")
        if normalized == "*":
            return normalized
        try:
            return str(uuid.UUID(normalized))
        except ValueError as exc:
            raise ValueError("owner_id must be UUID or '*'") from exc

    @staticmethod
    def _permissions_for_check(permission: str) -> tuple[str, ...]:
        if permission == "read":
            return ("read", "write")
        return ("write",)

    @staticmethod
    def _resource_model_by_type(resource_type: str) -> ResourceModelType:
        # Lazy imports avoid circular import chains in module initialization.
        if resource_type == "llm":
            from giga_agent.models.llm import LLM

            return LLM
        if resource_type == "connector":
            from giga_agent.models.connector import Connector

            return Connector
        if resource_type == "embedding":
            from giga_agent.models.embedding import Embedding

            return Embedding
        if resource_type == "file":
            from giga_agent.models.file import File

            return File
        if resource_type == "image_generator":
            from giga_agent.models.image_generator import ImageGenerator

            return ImageGenerator
        if resource_type == "rag_collection":
            from giga_agent.models.rag import RagCollection

            return RagCollection
        if resource_type == "sandbox":
            from giga_agent.models.sandbox import SandboxProvider

            return SandboxProvider
        if resource_type == "search_engine":
            from giga_agent.models.search_engine import SearchEngine

            return SearchEngine

        raise ValueError(f"Unsupported resource_type: {resource_type!r}")

    async def _resolve_group_ids(
        self,
        *,
        user_id: uuid.UUID,
        user_group_ids: Sequence[uuid.UUID] | None,
    ) -> list[uuid.UUID]:
        if user_group_ids is not None:
            return list(dict.fromkeys(user_group_ids))
        from giga_agent.models.group import GroupRepository

        return await GroupRepository(self.db).get_group_ids_by_user_id(user_id)

    @staticmethod
    def _permission_exists_clause(
        *,
        resource_type: str,
        resource_id_expr: uuid.UUID | ColumnElement[uuid.UUID],
        owner_id: str,
        permission: str,
        group_ids: Sequence[uuid.UUID],
    ) -> ColumnElement[bool]:
        allowed_permissions = ResourcePermissionRepository._permissions_for_check(permission)
        owner_conditions: list[ColumnElement[bool]] = [
            and_(
                ResourcePermission.owner_type == "user",
                ResourcePermission.owner_id == owner_id,
            )
        ]
        if group_ids:
            owner_conditions.append(
                and_(
                    ResourcePermission.owner_type == "group",
                    ResourcePermission.owner_id.in_([str(group_id) for group_id in group_ids]),
                )
            )
        owner_conditions.append(ResourcePermission.owner_id == "*")

        return exists(
            select(ResourcePermission.id).where(
                ResourcePermission.resource_type == resource_type,
                ResourcePermission.resource_id == resource_id_expr,
                ResourcePermission.permission.in_(allowed_permissions),
                or_(*owner_conditions),
            )
        )

    async def grant_permission(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        owner_type: str,
        owner_id: uuid.UUID | str,
        permission: str,
        no_commit: bool = False,
    ) -> ResourcePermission:
        result = await self.grant_permissions(
            items=[
                PermissionGrantItem(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    permission=permission,
                )
            ],
            no_commit=no_commit,
        )
        if result.created:
            return result.created[0]
        if result.existing:
            return result.existing[0]
        if result.errors:
            raise ValueError(result.errors[0].error)
        raise RuntimeError("grant_permission produced no result")

    async def grant_permissions(
        self,
        *,
        items: Sequence[PermissionGrantItem],
        no_commit: bool = False,
    ) -> BulkGrantPermissionsResult:
        if not items:
            return BulkGrantPermissionsResult(created=[], existing=[], errors=[])

        errors: list[PermissionGrantError] = []
        unique_items: dict[
            tuple[str, uuid.UUID, str, str, str],
            tuple[int, PermissionGrantItem, PermissionGrantItem],
        ] = {}

        for index, item in enumerate(items):
            try:
                normalized_resource_type = self._normalize_resource_type(item.resource_type)
                normalized_owner_id = self._normalize_owner_id(item.owner_id)
                normalized_permission = self._normalize_permission(item.permission)
                normalized_owner_type = self._normalize_owner_type(item.owner_type)
                if normalized_owner_id == "*":
                    if normalized_permission != "read":
                        raise ValueError("public owner_id='*' supports only read permission")
                    normalized_owner_type = "user"
            except ValueError as exc:
                errors.append(
                    PermissionGrantError(
                        index=index,
                        item=item,
                        error=str(exc),
                    )
                )
                continue

            normalized_item = PermissionGrantItem(
                resource_type=normalized_resource_type,
                resource_id=item.resource_id,
                owner_type=normalized_owner_type,
                owner_id=normalized_owner_id,
                permission=normalized_permission,
            )
            key = (
                normalized_item.resource_type,
                normalized_item.resource_id,
                normalized_item.owner_type,
                str(normalized_item.owner_id),
                normalized_item.permission,
            )
            if key not in unique_items:
                unique_items[key] = (index, item, normalized_item)

        if not unique_items:
            return BulkGrantPermissionsResult(created=[], existing=[], errors=errors)

        conditions = [
            and_(
                ResourcePermission.resource_type == key[0],
                ResourcePermission.resource_id == key[1],
                ResourcePermission.owner_type == key[2],
                ResourcePermission.owner_id == key[3],
                ResourcePermission.permission == key[4],
            )
            for key in unique_items
        ]
        existing_rows = await self.db.execute(
            select(ResourcePermission).where(or_(*conditions))
        )
        existing_by_key = {
            (
                row.resource_type,
                row.resource_id,
                row.owner_type,
                row.owner_id,
                row.permission,
            ): row
            for row in existing_rows.scalars().all()
        }

        candidates: list[
            tuple[tuple[str, uuid.UUID, str, str, str], int, PermissionGrantItem, ResourcePermission]
        ] = []
        for key, (index, original_item, normalized_item) in unique_items.items():
            if key in existing_by_key:
                continue
            entity = ResourcePermission(
                resource_type=normalized_item.resource_type,
                resource_id=normalized_item.resource_id,
                owner_type=normalized_item.owner_type,
                owner_id=str(normalized_item.owner_id),
                permission=normalized_item.permission,
            )
            candidates.append((key, index, original_item, entity))
            self.db.add(entity)

        if not candidates:
            ordered_existing = [
                existing_by_key[key]
                for key in unique_items
                if key in existing_by_key
            ]
            return BulkGrantPermissionsResult(
                created=[],
                existing=ordered_existing,
                errors=errors,
            )

        try:
            if no_commit:
                await self.db.flush()
            else:
                await self.db.commit()
            for _, _, _, entity in candidates:
                await self.db.refresh(entity)
            ordered_created = [entity for _, _, _, entity in candidates]
            ordered_existing = [
                existing_by_key[key]
                for key in unique_items
                if key in existing_by_key
            ]
            return BulkGrantPermissionsResult(
                created=ordered_created,
                existing=ordered_existing,
                errors=errors,
            )
        except IntegrityError as exc:
            if no_commit:
                raise
            await self.db.rollback()
            candidate_keys = [key for key, _, _, _ in candidates]
            race_conditions = [
                and_(
                    ResourcePermission.resource_type == key[0],
                    ResourcePermission.resource_id == key[1],
                    ResourcePermission.owner_type == key[2],
                    ResourcePermission.owner_id == key[3],
                    ResourcePermission.permission == key[4],
                )
                for key in candidate_keys
            ]
            raced_rows = await self.db.execute(
                select(ResourcePermission).where(or_(*race_conditions))
            )
            raced_by_key = {
                (
                    row.resource_type,
                    row.resource_id,
                    row.owner_type,
                    row.owner_id,
                    row.permission,
                ): row
                for row in raced_rows.scalars().all()
            }

            for key, index, original_item, _ in candidates:
                if key in raced_by_key:
                    existing_by_key[key] = raced_by_key[key]
                    continue
                errors.append(
                    PermissionGrantError(
                        index=index,
                        item=original_item,
                        error=f"Failed to grant permission: {exc}",
                    )
                )

            ordered_existing = [
                existing_by_key[key]
                for key in unique_items
                if key in existing_by_key
            ]
            return BulkGrantPermissionsResult(
                created=[],
                existing=ordered_existing,
                errors=errors,
            )

    async def revoke_permission(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        owner_type: str,
        owner_id: uuid.UUID | str,
        permission: str,
    ) -> bool:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        normalized_owner_id = self._normalize_owner_id(owner_id)
        normalized_permission = self._normalize_permission(permission)
        normalized_owner_type = self._normalize_owner_type(owner_type)
        if normalized_owner_id == "*":
            normalized_owner_type = "user"

        stmt = (
            delete(ResourcePermission)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id == resource_id)
            .where(ResourcePermission.owner_type == normalized_owner_type)
            .where(ResourcePermission.owner_id == normalized_owner_id)
            .where(ResourcePermission.permission == normalized_permission)
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return bool(res.rowcount)

    async def revoke_all_for_resource(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        no_commit: bool = False,
    ) -> int:
        return await self.revoke_all_for_resources(
            resource_type=resource_type,
            resource_ids=[resource_id],
            no_commit=no_commit,
        )

    async def revoke_all_for_resources(
        self,
        *,
        resource_type: str,
        resource_ids: Sequence[uuid.UUID],
        no_commit: bool = False,
    ) -> int:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        normalized_resource_ids = list(dict.fromkeys(resource_ids))
        if not normalized_resource_ids:
            return 0

        stmt = (
            delete(ResourcePermission)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id.in_(normalized_resource_ids))
        )
        res = await self.db.execute(stmt)
        if no_commit:
            await self.db.flush()
        else:
            await self.db.commit()
        return int(res.rowcount or 0)

    async def list_permissions_for_resource(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> list[ResourcePermission]:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        result = await self.db.execute(
            select(ResourcePermission)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id == resource_id)
            .order_by(ResourcePermission.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_permissions_for_resources(
        self,
        *,
        resource_type: str,
        resource_ids: Sequence[uuid.UUID],
    ) -> list[ResourcePermission]:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        normalized_resource_ids = list(dict.fromkeys(resource_ids))
        if not normalized_resource_ids:
            return []

        result = await self.db.execute(
            select(ResourcePermission)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id.in_(normalized_resource_ids))
            .order_by(ResourcePermission.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_read_acl(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> ResourcePermissionsPayload:
        rows = await self.list_permissions_for_resource(
            resource_type=resource_type,
            resource_id=resource_id,
        )

        read_user_ids: list[uuid.UUID] = []
        read_group_ids: list[uuid.UUID] = []
        public_read = False

        for row in rows:
            if row.permission not in {"read", "write"}:
                continue
            if row.owner_id == "*":
                public_read = True
                continue
            if row.owner_type == "user":
                read_user_ids.append(uuid.UUID(row.owner_id))
                continue
            if row.owner_type == "group":
                read_group_ids.append(uuid.UUID(row.owner_id))

        dedup_user_ids = list(dict.fromkeys(read_user_ids))
        dedup_group_ids = list(dict.fromkeys(read_group_ids))

        return ResourcePermissionsPayload(
            read_user_ids=dedup_user_ids,
            read_group_ids=dedup_group_ids,
            public_read=public_read,
        )

    async def set_read_acl(
        self,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        read_user_ids: Sequence[uuid.UUID],
        read_group_ids: Sequence[uuid.UUID],
        public_read: bool,
    ) -> None:
        normalized_resource_type = self._normalize_resource_type(resource_type)

        dedup_user_ids = list(dict.fromkeys(read_user_ids))
        dedup_group_ids = list(dict.fromkeys(read_group_ids))

        await self.db.execute(
            delete(ResourcePermission)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id == resource_id)
            .where(ResourcePermission.permission.in_(("read", "write")))
        )

        for user_id in dedup_user_ids:
            self.db.add(
                ResourcePermission(
                    resource_type=normalized_resource_type,
                    resource_id=resource_id,
                    owner_type="user",
                    owner_id=self._normalize_owner_id(user_id),
                    permission="read",
                )
            )

        for group_id in dedup_group_ids:
            self.db.add(
                ResourcePermission(
                    resource_type=normalized_resource_type,
                    resource_id=resource_id,
                    owner_type="group",
                    owner_id=self._normalize_owner_id(group_id),
                    permission="read",
                )
            )

        if public_read:
            self.db.add(
                ResourcePermission(
                    resource_type=normalized_resource_type,
                    resource_id=resource_id,
                    owner_type="user",
                    owner_id="*",
                    permission="read",
                )
            )

        await self.db.commit()

    async def build_access_clause(
        self,
        resource_model: ResourceModelType,
        *,
        user_id: uuid.UUID,
        resource_type: str,
        permission: str = "read",
        user_group_ids: Sequence[uuid.UUID] | None = None,
    ) -> ColumnElement[bool]:
        access_flags = await self.build_access_flags(
            resource_model,
            user_id=user_id,
            resource_type=resource_type,
            user_group_ids=user_group_ids,
        )
        normalized_permission = self._normalize_permission(permission)
        if normalized_permission == "write":
            return access_flags.can_edit
        return access_flags.can_read

    async def build_access_flags(
        self,
        resource_model: ResourceModelType,
        *,
        user_id: uuid.UUID,
        resource_type: str,
        user_group_ids: Sequence[uuid.UUID] | None = None,
    ) -> AccessFlags:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        group_ids = await self._resolve_group_ids(
            user_id=user_id,
            user_group_ids=user_group_ids,
        )

        model_id = getattr(resource_model, "id", None)
        model_owner_id = getattr(resource_model, "owner_id", None)
        if model_id is None or model_owner_id is None:
            raise ValueError("resource_model must define id and owner_id columns")

        return AccessFlags(
            can_read=or_(
                model_owner_id == user_id,
                self._permission_exists_clause(
                    resource_type=normalized_resource_type,
                    resource_id_expr=model_id,
                    owner_id=str(user_id),
                    permission="read",
                    group_ids=group_ids,
                ),
            ),
            can_edit=or_(
                model_owner_id == user_id,
                self._permission_exists_clause(
                    resource_type=normalized_resource_type,
                    resource_id_expr=model_id,
                    owner_id=str(user_id),
                    permission="write",
                    group_ids=group_ids,
                ),
            ),
        )

    @staticmethod
    def select_with_access_flags(
        resource_model: ResourceModelType,
        *,
        access_flags: AccessFlags,
    ):
        return select(
            resource_model,
            access_flags.can_edit.label("can_edit"),
            access_flags.can_read.label("can_read"),
        )

    async def has_access(
        self,
        *,
        user_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        permission: str = "read",
        user_group_ids: Sequence[uuid.UUID] | None = None,
    ) -> bool:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        normalized_permission = self._normalize_permission(permission)

        resource_model = self._resource_model_by_type(normalized_resource_type)
        owner_query = await self.db.execute(
            select(resource_model.owner_id).where(resource_model.id == resource_id).limit(1)
        )
        resource_owner_id = owner_query.scalar_one_or_none()
        if resource_owner_id is None:
            return False
        if resource_owner_id == user_id:
            return True

        group_ids = await self._resolve_group_ids(
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        permission_exists = self._permission_exists_clause(
            resource_type=normalized_resource_type,
            resource_id_expr=literal(resource_id),
            owner_id=str(user_id),
            permission=normalized_permission,
            group_ids=group_ids,
        )
        result = await self.db.execute(select(permission_exists))
        return bool(result.scalar())

    async def list_resource_ids_with_access(
        self,
        *,
        user_id: uuid.UUID,
        resource_type: str,
        resource_ids: Sequence[uuid.UUID],
        permission: str = "read",
        user_group_ids: Sequence[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        normalized_resource_type = self._normalize_resource_type(resource_type)
        normalized_permission = self._normalize_permission(permission)
        normalized_resource_ids = list(dict.fromkeys(resource_ids))
        if not normalized_resource_ids:
            return set()

        group_ids = await self._resolve_group_ids(
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        allowed_permissions = self._permissions_for_check(normalized_permission)

        owner_conditions: list[ColumnElement[bool]] = [
            and_(
                ResourcePermission.owner_type == "user",
                ResourcePermission.owner_id == str(user_id),
            )
        ]
        if group_ids:
            owner_conditions.append(
                and_(
                    ResourcePermission.owner_type == "group",
                    ResourcePermission.owner_id.in_([str(group_id) for group_id in group_ids]),
                )
            )
        owner_conditions.append(ResourcePermission.owner_id == "*")

        result = await self.db.execute(
            select(ResourcePermission.resource_id)
            .where(ResourcePermission.resource_type == normalized_resource_type)
            .where(ResourcePermission.resource_id.in_(normalized_resource_ids))
            .where(ResourcePermission.permission.in_(allowed_permissions))
            .where(or_(*owner_conditions))
            .distinct()
        )
        return {row[0] for row in result.all()}
