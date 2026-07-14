"""add_user_experimental_mode

Revision ID: a1c2e3f4b5d6
Revises: 9c1b5f7e4d23
Create Date: 2026-07-14 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, None] = "9c1b5f7e4d23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # recreate="never" форсит нативный ALTER TABLE ... ADD COLUMN на SQLite.
    # Иначе batch пересоздаёт core_users (copy → DROP → rename), а DROP падает
    # с "FOREIGN KEY constraint failed": на core_users ссылаются ~19 таблиц, а
    # миграции идут при PRAGMA foreign_keys=ON. Нативный ADD COLUMN дочерние
    # таблицы не трогает. SQLite позволяет NOT NULL при наличии DEFAULT.
    with op.batch_alter_table(
        "core_users", schema=None, recreate="never"
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "experimental_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "core_users", schema=None, recreate="never"
    ) as batch_op:
        batch_op.drop_column("experimental_mode")
