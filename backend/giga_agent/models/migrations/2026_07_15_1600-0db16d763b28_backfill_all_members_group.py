"""backfill_all_members_group

Создаёт системную группу «All Members» и наполняет её всеми существующими
пользователями — то, что раньше делал ``ensure_all_members_group`` при старте.

Идемпотентно: если системная группа уже есть, только добивает недостающих
участников. На пустой базе (пользователей ещё нет) не делает ничего — группа
будет создана в рантайме при появлении первого пользователя.

Строковые маркеры продублированы из ``giga_agent.core.team`` намеренно:
миграция — застывший снимок и не должна импортировать код приложения.

Revision ID: 0db16d763b28
Revises: c3d4e5f60718
Create Date: 2026-07-15 16:00:00.000000

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0db16d763b28"
down_revision: Union[str, None] = "c3d4e5f60718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Маркер системной группы в core_groups.data (см. core.team).
SYSTEM_GROUP_ALL_MEMBERS = "all_members"
ALL_MEMBERS_NAME = "All Members"
ALL_MEMBERS_DESCRIPTION = "Все участники команды (системная группа)"


def _tables():
    users = sa.table(
        "core_users",
        sa.column("id", sa.Uuid()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    groups = sa.table(
        "core_groups",
        sa.column("id", sa.Uuid()),
        sa.column("owner_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
        ),
    )
    members = sa.table(
        "core_group_members",
        sa.column("group_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
    )
    return users, groups, members


def _find_system_group_id(bind, groups):
    for row in bind.execute(sa.select(groups.c.id, groups.c.data)):
        data = row.data if isinstance(row.data, dict) else {}
        if data.get("system") == SYSTEM_GROUP_ALL_MEMBERS:
            return row.id
    return None


def upgrade() -> None:
    bind = op.get_bind()
    users, groups, members = _tables()

    group_id = _find_system_group_id(bind, groups)

    if group_id is None:
        # Владелец группы — owner инстанса, иначе самый ранний пользователь.
        owner_id = bind.execute(
            sa.select(users.c.id)
            .order_by(
                sa.case((users.c.role == "owner", 0), else_=1),
                users.c.created_at.asc(),
                users.c.id.asc(),
            )
            .limit(1)
        ).scalar()
        if owner_id is None:
            # Пустая база: группу создаст рантайм при первом пользователе.
            return
        group_id = uuid.uuid4()
        bind.execute(
            sa.insert(groups).values(
                id=group_id,
                owner_id=owner_id,
                name=ALL_MEMBERS_NAME,
                description=ALL_MEMBERS_DESCRIPTION,
                data={"system": SYSTEM_GROUP_ALL_MEMBERS},
            )
        )

    existing = {
        row.user_id
        for row in bind.execute(
            sa.select(members.c.user_id).where(members.c.group_id == group_id)
        )
    }
    all_ids = [row.id for row in bind.execute(sa.select(users.c.id))]
    missing = [uid for uid in all_ids if uid not in existing]
    if missing:
        bind.execute(
            sa.insert(members),
            [{"group_id": group_id, "user_id": uid} for uid in missing],
        )


def downgrade() -> None:
    bind = op.get_bind()
    _, groups, members = _tables()

    group_id = _find_system_group_id(bind, groups)
    if group_id is None:
        return
    # Явно чистим членство перед группой (CASCADE на SQLite не гарантирован).
    bind.execute(sa.delete(members).where(members.c.group_id == group_id))
    bind.execute(sa.delete(groups).where(groups.c.id == group_id))
