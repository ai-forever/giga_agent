from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.models.resource_permission import ResourcePermissionRepository

ResourceT = TypeVar("ResourceT")


class ACLResourceRepositoryMixin(Generic[ResourceT]):
    db: AsyncSession
    resource_model: type[ResourceT]
    resource_type: str
    supports_only_active: bool = True
    active_field_name: str = "is_active"

    def _apply_acl_only_active_filter(self, query: Any, *, only_active: bool) -> Any:
        if not only_active or not self.supports_only_active:
            return query
        active_column = getattr(self.resource_model, self.active_field_name, None)
        if active_column is None:
            return query
        return query.where(active_column == True)  # noqa: E712

    def _apply_acl_default_order(self, query: Any) -> Any:
        created_at_column = getattr(self.resource_model, "created_at", None)
        if created_at_column is None:
            return query
        return query.order_by(created_at_column.desc())

    async def list_readable_with_edit_for_user(
        self,
        *,
        user_id: uuid.UUID,
        only_active: bool = False,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[ResourceT, bool]]:
        permission_repo = ResourcePermissionRepository(self.db)
        access_flags = await permission_repo.build_access_flags(
            self.resource_model,
            user_id=user_id,
            resource_type=self.resource_type,
            user_group_ids=user_group_ids,
        )
        query = permission_repo.select_with_access_flags(
            self.resource_model,
            access_flags=access_flags,
        ).where(access_flags.can_read)
        query = self._apply_acl_only_active_filter(query, only_active=only_active)
        query = self._apply_acl_default_order(query)
        result = await self.db.execute(query)
        return [(item, bool(can_edit)) for item, can_edit, _ in result.all()]

    async def get_by_id_with_access_for_user(
        self,
        resource_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        user_group_ids: list[uuid.UUID] | None = None,
    ) -> tuple[ResourceT, bool, bool] | None:
        permission_repo = ResourcePermissionRepository(self.db)
        access_flags = await permission_repo.build_access_flags(
            self.resource_model,
            user_id=user_id,
            resource_type=self.resource_type,
            user_group_ids=user_group_ids,
        )
        resource_id_column = getattr(self.resource_model, "id")
        result = await self.db.execute(
            permission_repo.select_with_access_flags(
                self.resource_model,
                access_flags=access_flags,
            ).where(resource_id_column == resource_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        resource, can_edit, can_read = row
        return resource, bool(can_read), bool(can_edit)
