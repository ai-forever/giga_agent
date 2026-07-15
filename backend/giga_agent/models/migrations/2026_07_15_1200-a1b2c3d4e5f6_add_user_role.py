"""add_user_role

Роль пользователя в команде (owner/admin/member). is_superuser сохраняется и
поддерживается синхронно с ролью для обратной совместимости существующих
проверок.

Backfill: is_superuser=true → admin; самый ранний из них → owner;
остальные → member.

Revision ID: a1b2c3d4e5f6
Revises: 9c1b5f7e4d23
Create Date: 2026-07-08 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.String(length=16),
                nullable=False,
                server_default="member",
            )
        )

    # Существующие суперюзеры становятся админами…
    op.execute("UPDATE core_users SET role = 'admin' WHERE is_superuser")
    # …а самый ранний из них — владельцем инстанса.
    op.execute(
        """
        UPDATE core_users SET role = 'owner'
        WHERE id = (
            SELECT id FROM core_users
            WHERE is_superuser
            ORDER BY created_at ASC, id ASC
            LIMIT 1
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_column("role")
